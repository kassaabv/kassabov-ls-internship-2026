import os
import json
import time
from google import genai
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

class ActionItem(BaseModel):
    text: str
    owner: Optional[str] = None
    due_date: Optional[str] = None

class MeetingNotes(BaseModel):
    summary: str
    action_items: List[ActionItem]
    key_takeaways: List[str]
    topics: List[str]
    next_steps: List[str]

class NoteProcessor:
    def __init__(self, supabase):
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY must be set")
        self.client = genai.Client(api_key=api_key)
        self.supabase = supabase

    def generate_notes(self, transcript: str) -> Dict[str, Any]:
        if not transcript or len(transcript.strip()) < 50:
            print("Transcript too short. Returning default empty notes.")
            empty_notes = {
                "summary": "Transcript too short to generate meaningful notes.",
                "action_items": [],
                "key_takeaways": [],
                "topics": [],
                "next_steps": []
            }
            return empty_notes, "{}"

        max_chars = 400000
        if len(transcript) > max_chars:
            print(f"Transcript too long ({len(transcript)} chars). Truncating to {max_chars} chars.")
            transcript = transcript[:max_chars] + "\n...[TRUNCATED]"

        prompt = f"""
        Analyze the following meeting transcript and provide structured notes in JSON format.

        Transcript:
        {transcript}

        The JSON must follow this schema:
        {{
            "summary": "A concise summary of the meeting",
            "action_items": [
                {{ "text": "The task description", "owner": "Name of person responsible or null", "due_date": "YYYY-MM-DD or null" }}
            ],
            "key_takeaways": ["List of main points to remember"],
            "topics": ["List of topics discussed"],
            "next_steps": ["A small recommendation based on the summary created in the notes"]
        }}

        Ensure the output is valid JSON.
        CRITICAL RULES:
        - DO NOT leave any array empty. You MUST provide at least one item for `action_items`, `key_takeaways`, `topics`, and `next_steps`.
        - If the transcript lacks explicit action items, takeaways, or topics, infer the most likely logical points based on the discussion.
        - Deduplicate action items.
        - Infer owners and dates from context if possible.
        """

        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = self.client.models.generate_content(
                    model='gemini-2.5-flash',
                    contents=prompt
                )
                raw_text = response.text.strip()

                if raw_text.startswith("```json"):
                    raw_text = raw_text[7:-3].strip()
                elif raw_text.startswith("```"):
                    raw_text = raw_text[3:-3].strip()

                data = json.loads(raw_text)
                validated = MeetingNotes(**data)
                return validated.model_dump(), raw_text
            except json.JSONDecodeError as e:
                print(f"Attempt {attempt + 1} failed: Invalid JSON returned by LLM. Error: {e}")
                time.sleep(2)
            except Exception as e:
                error_str = str(e)
                print(f"Attempt {attempt + 1} failed: Error: {error_str}")
                if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                    print("Rate limit hit. Sleeping for 35 seconds before retrying...")
                    time.sleep(35)
                else:
                    time.sleep(2)

        print("Failed to generate valid JSON after multiple attempts.")
        return None, ""

    def process_meeting(self, meeting_id: str):
        res = self.supabase.table("meetings").select("*").eq("id", meeting_id).single().execute()
        if not res.data:
            print(f"Meeting {meeting_id} not found.")
            return

        meeting = res.data
        print(f"Processing: {meeting['title']}...")

        existing = self.supabase.table("notes").select("id").eq("meeting_id", meeting_id).execute()
        if existing.data:
            print(f"Notes already exist for meeting {meeting_id}. Skipping.")
            return

        structured_notes, raw_llm = self.generate_notes(meeting['raw_transcript'])

        if structured_notes:
            note_data = {
                "meeting_id": meeting_id,
                "summary": structured_notes['summary'],
                "action_items": structured_notes['action_items'],
                "key_takeaways": structured_notes['key_takeaways'],
                "topics": structured_notes['topics'],
                "next_steps": structured_notes['next_steps']
            }
            self.supabase.table("notes").insert(note_data).execute()
            print(f"Successfully generated notes for {meeting['title']}.")
        else:
            print(f"Failed to generate valid notes for {meeting['title']}.")

    def process_all_pending(self):
        meetings_res = self.supabase.table("meetings").select("id, title").execute()
        notes_res = self.supabase.table("notes").select("meeting_id").execute()

        processed_ids = {n['meeting_id'] for n in notes_res.data}
        pending = [m for m in meetings_res.data if m['id'] not in processed_ids]

        print(f"Found {len(pending)} meetings without notes.")
        for m in pending:
            self.process_meeting(m['id'])
            time.sleep(4)

if __name__ == "__main__":
    import argparse
    from dotenv import load_dotenv
    from supabase import create_client

    load_dotenv()
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_KEY", "")
    if not url or not key:
        raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set in environment")

    client = create_client(url, key)

    parser = argparse.ArgumentParser(description="Generate meeting notes")
    parser.add_argument("--id", help="Specific meeting ID to process")
    parser.add_argument("--all", action="store_true", help="Process all meetings without notes")
    args = parser.parse_args()

    processor = NoteProcessor(client)
    if args.id:
        processor.process_meeting(args.id)
    elif args.all:
        processor.process_all_pending()
    else:
        parser.print_help()
