# Meeting Notes API - Day 4

API to automatically generate meeting notes using Gemini and Supabase.

## Setup Steps

1. **Create a virtual environment and install dependencies:**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Configure environment variables:**
   Update your `.env` file with the following:
   ```env
   SUPABASE_URL=your_supabase_url
   SUPABASE_KEY=your_supabase_anon_key
   GEMINI_API_KEY=your_gemini_api_key
   ```

3. **Ingest transcripts:**
   Process `.docx` files from the `/transcripts` directory:
   ```bash
   python3 ingest.py
   ```

4. **Verify records:**
   Check stored records in the database:
   ```bash
   python3 query.py
   ```

5. **Process notes (CLI):**
   Manually trigger note generation for all pending meetings:
   ```bash
   python3 app/processor.py --all
   ```

6. **Start the FastAPI server:**
   ```bash
   uvicorn app.main:app --reload --port 3000
   ```

## Implementation Details

- **Mapping:** Folders within the `/transcripts` directory are automatically mapped to the `project` column in the database.
- **Chunking:** Large transcripts are split into smaller, overlapping segments in `ingest.py` and the bulk import API to handle LLM token limits without data loss.
- **Automated Testing:** `app/test_ingest.py` verifies database connections, record creation, and LLM generation.
- **LLM Processing:** `app/processor.py` queries meetings without notes, sends transcripts to Gemini 2.5 Flash, and enforces a strict JSON schema using Pydantic.
- **Rate Limiting & Retries:** Implemented error handling for `429 RESOURCE_EXHAUSTED` errors. The script pauses for 35 seconds and retries up to 3 times.
- **Background Processing API:** The `/api/process-pending` and `/meetings/import/bulk` endpoints use FastAPI `BackgroundTasks` to process meetings and imports asynchronously.
- **Centralized Config:** `app/settings.py` manages environment variables and logging configuration.
- **Google Docs Import:** Isolated service in `app/google_docs.py` to fetch, chunk, and import Google Docs asynchronously via the bulk import API.

## SQL Schema

```sql
CREATE TABLE meetings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT NOT NULL,
    meeting_date DATE NOT NULL,
    source TEXT NOT NULL,
    project TEXT NOT NULL,
    raw_transcript TEXT NOT NULL,
    source_url TEXT,
    external_id TEXT,
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
```

## API Endpoints & Example Curl Commands

### List all meetings
Returns a list of unique meeting sessions (grouped parts) and whether notes exist.
```bash
curl http://127.0.0.1:3000/meetings
```

### Get a single meeting
Returns aggregated meeting session data and full transcript.
```bash
curl http://127.0.0.1:3000/meetings/{meeting_id}
```

### Create a meeting
```bash
curl -X POST http://127.0.0.1:3000/meetings \
     -H "Content-Type: application/json" \
     -d '{
       "title": "Project Kickoff",
       "project": "Alpha",
       "raw_transcript": "Alice: Welcome everyone. Bob: Thanks. Let's start...",
       "meeting_date": "2025-03-12"
     }'
```

### Process a meeting (Generate Notes)
Triggers note generation for a specific meeting (re-runs allowed). Returns the stored notes.
```bash
curl -X POST http://127.0.0.1:3000/meetings/{meeting_id}/process
```

### Get notes for a meeting
```bash
curl http://127.0.0.1:3000/meetings/{meeting_id}/notes
```

### Process all pending meetings (Background)
```bash
curl -X POST http://127.0.0.1:3000/api/process-pending
```

### Bulk Import from Google Docs (Background)
Imports multiple meetings from Google Docs URLs asynchronously, chunks them, and saves them to the database.
```bash
curl -X POST http://127.0.0.1:3000/meetings/import/bulk \
     -H "Content-Type: application/json" \
     -d '{
       "projects": [
         {
           "name": "Edamame",
           "urls": [
             "https://docs.google.com/document/d/1FUZK9e4XkDaq-tiJ7hfOEG9x-SKR6cidAV1LNh6De2s/edit",
             "https://docs.google.com/document/d/1Tk9pYpVzg7diovYmuYo7LoWqDkRbNxEFSEplcIyVbtg/edit"
           ]
         }
       ]
     }'
```

### Health Check
```bash
curl http://127.0.0.1:3000/api/health
```
