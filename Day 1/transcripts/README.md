#Setup Steps

    1. Created a virtual environment and installed dependencies.
        python3 -m venv .venv
        source .venv/bin/activate
        pip install -r requirements.txt

    2. Created a .env file with SUPABASE_URL and SUPABASE_KEY.

    3. Ran the SQL schema provided below in the Supabase SQL editor.

    4. Ran python3 ingest.py to process .docx files from the /transcripts directory.

    5. Ran python3 query.py to verify stored records.
    
#Implementation Details

    Mapping: Folders in the transcripts are mapped to the project column.

    Chunking: Included logic to split transcripts into smaller segments to handle future LLM token limits without data loss.

    Automation Tests: test_ingest.py included to verify text processing logic.
    
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
