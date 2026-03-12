import os
import json
import time
from google import genai
from typing import List, Optional, Dict, Any, Tuple
from pydantic import BaseModel, Field
from .settings import settings, logger

class ActionItem(BaseModel):
    text: str
    owner: Optional[str] = None
    due_date: Optional[str] = None

class Topic(BaseModel):
    title: str
    points: List[str]

class MeetingNotes(BaseModel):
    summary: str
    action_items: List[ActionItem]
    key_takeaways: List[str]
    topics: List[Topic]
    next_steps: List[str]

class NoteProcessor:
    def __init__(self, supabase):
        api_key = settings.GEMINI_API_KEY
        if not api_key:
            raise ValueError("GEMINI_API_KEY must be set")
        self.client = genai.Client(api_key=api_key)
        self.supabase = supabase

    def generate_notes(self, transcript: str) -> Tuple[Optional[Dict[str, Any]], str]:
        if not transcript or len(transcript.strip()) < 50:
            logger.warning("Transcript too short. Returning default empty notes.")
            empty_notes = {
                "summary": "Transcript too short to generate meaningful notes.",
                "action_items": [],
                "key_takeaways": [],
                "topics": [],
                "next_steps": []
            }
            return empty_notes, "{}"

        prompt = f"""
        Analyze the following meeting transcript and provide structured notes in JSON format.
        The transcript may be composed of multiple parts that have been joined together.

        Transcript:
        {transcript}

        The JSON must follow this schema:
        {{
            "summary": "A concise summary of the meeting",
            "action_items": [
                {{ "text": "The task description", "owner": "Name of person responsible or null", "due_date": "YYYY-MM-DD or null" }}
            ],
            "key_takeaways": ["List of main points to remember"],
            "topics": [
                {{ "title": "Topic Name", "points": ["Detail 1", "Detail 2"] }}
            ],
            "next_steps": ["A small recommendation based on the summary created in the notes"]
        }}

        Ensure the output is valid JSON.
        CRITICAL RULES:
        - DO NOT leave any array empty. You MUST provide at least one item for `action_items`, `key_takeaways`, `topics`, and `next_steps`.
        - If the transcript lacks explicit action items, takeaways, or topics, infer the most likely logical points based on the discussion.
        - Deduplicate action items.
        - Infer owners and dates from context if possible.
        - For 'topics', group related discussion points under clear headings.
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
                logger.error(f"Attempt {attempt + 1} failed: Invalid JSON returned by LLM. Error: {e}")
                time.sleep(2)
            except Exception as e:
                error_str = str(e)
                logger.error(f"Attempt {attempt + 1} failed: Error: {error_str}")
                if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                    logger.warning("Rate limit hit. Sleeping for 35 seconds before retrying...")
                    time.sleep(35)
                else:
                    time.sleep(2)

        logger.error("Failed to generate valid JSON after multiple attempts.")
        return None, ""

    def process_meeting(self, meeting_id: str, force: bool = False) -> Optional[Dict[str, Any]]:
        res = self.supabase.table("meetings").select("*").eq("id", meeting_id).single().execute()
        if not res.data:
            logger.error(f"Meeting {meeting_id} not found.")
            return None

        target_meeting = res.data
        title = target_meeting['title']
        project = target_meeting['project']

        import re
        base_title = re.sub(r" \[Part \d+\]$", "", title)

        all_parts_res = self.supabase.table("meetings") \
            .select("id, title, raw_transcript") \
            .eq("project", project) \
            .ilike("title", f"{base_title}%") \
            .execute()

        parts = []
        for m in all_parts_res.data:
            m_base = re.sub(r" \[Part \d+\]$", "", m['title'])
            if m_base == base_title:
                parts.append(m)

        parts.sort(key=lambda x: x['title'])

        full_transcript = "\n\n".join([p['raw_transcript'] for p in parts])
        logger.info(f"Processing aggregated meeting: {base_title} ({len(parts)} parts)...")

        canonical_id = parts[0]['id']

        existing = self.supabase.table("notes").select("*").eq("meeting_id", canonical_id).execute()
        if existing.data and not force:
            logger.info(f"Notes already exist for canonical meeting {canonical_id}. Skipping.")
            return existing.data[0]

        structured_notes, raw_llm = self.generate_notes(full_transcript)

        if structured_notes:
            note_data = {
                "meeting_id": canonical_id,
                "project": project,
                "summary": structured_notes['summary'],
                "action_items": structured_notes['action_items'],
                "key_takeaways": structured_notes['key_takeaways'],
                "topics": structured_notes['topics'],
                "next_steps": structured_notes['next_steps'],
                "llm_raw": raw_llm
            }

            if existing.data:
                self.supabase.table("notes").update(note_data).eq("meeting_id", canonical_id).execute()
                logger.info(f"Successfully updated notes for {base_title}.")
            else:
                self.supabase.table("notes").insert(note_data).execute()
                logger.info(f"Successfully generated notes for {base_title}.")

            return note_data
        else:
            logger.error(f"Failed to generate valid notes for {base_title}.")
            return None

    def process_all_pending(self):
        meetings_res = self.supabase.table("meetings").select("id, title, project").execute()
        notes_res = self.supabase.table("notes").select("meeting_id").execute()
        processed_ids = {n['meeting_id'] for n in notes_res.data}

        import re
        groups = {}
        for m in meetings_res.data:
            base_title = re.sub(r" \[Part \d+\]$", "", m['title'])
            key = (base_title, m['project'])
            if key not in groups:
                groups[key] = []
            groups[key].append(m)

        pending_groups = []
        for key, members in groups.items():
            members.sort(key=lambda x: x['title'])
            canonical_id = members[0]['id']
            if canonical_id not in processed_ids:
                pending_groups.append(members[0])

        logger.info(f"Found {len(pending_groups)} meeting groups without notes.")
        for m in pending_groups:
            self.process_meeting(m['id'])
            time.sleep(4)

if __name__ == "__main__":
    import argparse
    from supabase import create_client

    url = settings.SUPABASE_URL
    key = settings.SUPABASE_KEY
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
