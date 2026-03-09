import os
from fastapi import FastAPI, BackgroundTasks
from dotenv import load_dotenv
from supabase import create_client
from processor import NoteProcessor

load_dotenv()

app = FastAPI(
    title="Meeting Notes API",
    description="API to automatically generate meeting notes using Gemini."
)

url = os.environ.get("SUPABASE_URL", "")
key = os.environ.get("SUPABASE_KEY", "")

if not url or not key:
    print("Warning: SUPABASE_URL or SUPABASE_KEY not set. API will fail if called.")
    supabase_client = None
    processor = None
else:
    supabase_client = create_client(url, key)
    processor = NoteProcessor(supabase_client)

@app.post("/api/process-pending")
async def process_pending_meetings(background_tasks: BackgroundTasks):

    if not processor:
        return {"status": "error", "message": "Server configuration error (missing Supabase keys)."}

    background_tasks.add_task(processor.process_all_pending)

    return {
        "status": "success",
        "message": "Started processing pending meetings in the background. Check server logs for progress."
    }

@app.get("/api/health")
async def health_check():
    """Simple health check endpoint."""
    return {"status": "healthy"}
