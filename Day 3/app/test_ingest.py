import os
from supabase import create_client
from dotenv import load_dotenv
from .processor import NoteProcessor

load_dotenv()

def test_supabase_connection():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    client = create_client(url, key)

    res = client.table("meetings").select("id").limit(1).execute()

    assert res.data is not None
    print("Database connection is healthy.")

def test_llm_generation_low_token():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    client = create_client(url, key)

    processor = NoteProcessor(client)

    mock_transcript = (
        "Alice: Let's launch the new website on Friday.\n"
        "Bob: Sounds good. I will email the team today to let them know.\n"
        "Alice: Great. The main takeaway is we are on schedule."
    )

    print("Sending mock transcript to Gemini...")
    result, raw_response = processor.generate_notes(mock_transcript)

    assert result is not None
    assert isinstance(result, dict)

    assert "summary" in result
    assert "action_items" in result
    assert "key_takeaways" in result

    assert len(result["action_items"]) > 0
    assert "Bob" in str(result["action_items"]) or "email" in str(result["action_items"]).lower()

    print("LLM Generation Test Passed!")
    print(f"Summary generated: {result['summary']}")
