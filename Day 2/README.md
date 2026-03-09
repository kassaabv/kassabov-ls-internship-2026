#Setup Steps

1. Created a virtual environment and installed new dependencies.
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt

2. Updated .env file with GEMINI_API_KEY.

3. Ran python3 ingest.py to process .docx files from the /transcripts directory.

4. Ran python3 query.py to verify stored records.

5. Ran python3 processor.py to make a request to Gemini API to fill notes table.

6. Ran python3 -m uvicorn main:app --reload to start the FastAPI server, which exposes an endpoint to process pending meetings.


#Implementation Details

    Mapping: Folders within the /transcripts directory are automatically mapped to the project column in the database.

    Chunking: Included logic in ingest.py to split large transcripts into smaller, overlapping segments to handle LLM token limits without data loss.

    Automated Testing: Included test_ingest.py to verify the database connection and ensure records were successfully inserted.

    LLM Processing: Created processor.py to query the database for meetings without notes, send the transcript to the Gemini 2.5 Flash, and enforce a strict JSON schema using Pydantic.

    Rate Limiting & Retries: Implemented error handling to catch 429 RESOURCE_EXHAUSTED errors from the Gemini API. Script automatically pauses for 35 seconds and retries up to 3 times, while buffering requests to ~15 per minute to respect free-tier limits.

    Background Processing API: Wrapped the processing logic in a FastAPI server (main.py). The /api/process-pending endpoint uses FastAPI BackgroundTasks to process all pending meetings asynchronously, preventing HTTP timeouts.

#SQL Schema

CREATE TABLE meetings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT NOT NULL,
    meeting_date DATE NOT NULL,
    source TEXT NOT NULL,
    project TEXT NOT NULL,
    raw_transcript TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE notes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    meeting_id UUID REFERENCES meetings(id) ON DELETE CASCADE,
    summary TEXT,
    action_items JSONB DEFAULT '[]'::jsonb,
    key_takeaways JSONB DEFAULT '[]'::jsonb,
    topics JSONB DEFAULT '[]'::jsonb,
    next_steps JSONB DEFAULT '[]'::jsonb,
    created_at TIMESTAMP DEFAULT now()
);