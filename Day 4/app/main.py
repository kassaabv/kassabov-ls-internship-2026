import os
import logging
from typing import List, Optional
from fastapi import FastAPI, BackgroundTasks, HTTPException, status
from pydantic import BaseModel, Field
from supabase import create_client
from .processor import NoteProcessor
from .settings import settings, logger
from .google_docs import GoogleDocsService

app = FastAPI(
    title="Meeting Notes API",
    description="API to automatically generate meeting notes using Gemini."
)

if not settings.SUPABASE_URL or not settings.SUPABASE_KEY:
    logger.error("SUPABASE_URL or SUPABASE_KEY not set.")
    supabase_client = None
    processor = None
else:
    supabase_client = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
    processor = NoteProcessor(supabase_client)

google_docs_service = GoogleDocsService()

class MeetingCreate(BaseModel):
    title: str
    project: str
    raw_transcript: str
    meeting_date: Optional[str] = None

class ProjectImport(BaseModel):
    name: str
    urls: List[str]

class GoogleDocBulkImport(BaseModel):
    projects: List[ProjectImport]

import re

def get_canonical_id(meeting_id: str):
    res = supabase_client.table("meetings").select("title, project, meeting_date").eq("id", meeting_id).single().execute()
    if not res.data:
        return meeting_id
    
    title = res.data['title']
    project = res.data['project']
    meeting_date = res.data['meeting_date']
    base_title = re.sub(r" \[Part \d+\]$", "", title)
    
    parts_res = supabase_client.table("meetings") \
        .select("id, title") \
        .eq("project", project) \
        .eq("meeting_date", meeting_date) \
        .ilike("title", f"{base_title}%") \
        .execute()
    
    parts = []
    for m in parts_res.data:
        m_base = re.sub(r" \[Part \d+\]$", "", m['title'])
        if m_base == base_title:
            parts.append(m)
    
    if not parts:
        return meeting_id
        
    parts.sort(key=lambda x: x['title'])
    return parts[0]['id']

def chunk_transcript_recursive(text: str, max_chars: int = 5000, overlap: int = 500):
    if not text:
        return []

    chunks = []
    start = 0
    text_len = len(text)

    while start < text_len:
        end = min(start + max_chars, text_len)
        if end == text_len:
            chunks.append(text[start:].strip())
            break

        segment = text[start:end]
        split_at = -1
        for sep in ["\n\n", "\n", ". ", "? ", "! "]:
            split_at = segment.rfind(sep)
            if split_at != -1:
                split_at += len(sep)
                break

        if split_at <= 0:
            split_at = max_chars

        current_chunk = text[start : start + split_at].strip()
        chunks.append(current_chunk)

        target_overlap_start = (start + split_at) - overlap

        sentence_match = re.search(r'[.?!]\s+', text[target_overlap_start:])

        if sentence_match:
            start = target_overlap_start + sentence_match.end()
        else:
            next_space = text.find(" ", target_overlap_start)
            start = next_space + 1 if next_space != -1 else target_overlap_start

    return chunks

def extract_date_from_title(title: str, default_year: int = 2025) -> str:
    from datetime import datetime
    import re
    pattern = r"(?i)(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sept|sep|oct|nov|dec)\s+(\d{1,2})"
    match = re.search(pattern, title)
    if match:
        month_str = match.group(1).capitalize()
        if month_str == 'Sept':
            month_str = 'Sep'
        day_str = match.group(2)
        for fmt in ("%B %d %Y", "%b %d %Y"):
            try:
                dt = datetime.strptime(f"{month_str} {day_str} {default_year}", fmt)
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                continue
    return datetime.now().replace(year=default_year).strftime("%Y-%m-%d")

def process_bulk_import_background(payload: GoogleDocBulkImport):
    from datetime import datetime
    
    for project in payload.projects:
        for url in project.urls:
            doc_id = google_docs_service.extract_doc_id(url)
            if not doc_id:
                continue
                
            title, content, error = google_docs_service.fetch_doc_content(doc_id)
            if error or not content:
                logger.error(f"Failed to fetch doc {url}: {error}")
                continue
                
            meeting_date = extract_date_from_title(title)
            
            chunks = chunk_transcript_recursive(content)
            
            for i, chunk in enumerate(chunks):
                part_num = i + 1
                display_title = f"{title} [Part {part_num}]" if len(chunks) > 1 else title
                
                existing = supabase_client.table("meetings").select("id").eq("source_url", url).eq("title", display_title).execute()
                if existing.data:
                    continue
                    
                meeting_data = {
                    "title": display_title,
                    "project": project.name,
                    "meeting_date": meeting_date,
                    "source": "google_docs",
                    "source_url": url,
                    "external_id": f"{doc_id}_part_{part_num}",
                    "raw_transcript": chunk
                }
                
                try:
                    supabase_client.table("meetings").insert(meeting_data).execute()
                    logger.info(f"Saved chunk {part_num} for {title}")
                except Exception as e:
                    logger.error(f"Error saving chunk {part_num} for {title}: {e}")


@app.get("/meetings")
async def list_meetings():
    if not supabase_client:
        raise HTTPException(status_code=500, detail="Database connection error")
    
    meetings_res = supabase_client.table("meetings").select("*").execute()
    notes_res = supabase_client.table("notes").select("meeting_id").execute()
    note_ids = {n['meeting_id'] for n in notes_res.data}
    
    groups = {}
    for m in meetings_res.data:
        base_title = re.sub(r" \[Part \d+\]$", "", m['title'])
        key = (base_title, m['project'], m['meeting_date'])
        if key not in groups:
            groups[key] = []
        groups[key].append(m)
    
    results = []
    for key, members in groups.items():
        members.sort(key=lambda x: x['title'])
        canonical = members[0]
        results.append({
            "id": canonical['id'],
            "title": key[0],
            "project": key[1],
            "meeting_date": key[2],
            "parts_count": len(members),
            "has_notes": canonical['id'] in note_ids,
            "chunk_ids": [m['id'] for m in members]
        })
        
    results.sort(key=lambda x: x['meeting_date'] or "", reverse=True)
    return results

@app.get("/meetings/{meeting_id}")
async def get_meeting(meeting_id: str):
    if not supabase_client:
        raise HTTPException(status_code=500, detail="Database connection error")
    
    res = supabase_client.table("meetings").select("*").eq("id", meeting_id).single().execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Meeting not found")
    
    target = res.data
    base_title = re.sub(r" \[Part \d+\]$", "", target['title'])
    
    parts_res = supabase_client.table("meetings") \
        .select("*") \
        .eq("project", target['project']) \
        .eq("meeting_date", target['meeting_date']) \
        .ilike("title", f"{base_title}%") \
        .execute()
    
    parts = [p for p in parts_res.data if re.sub(r" \[Part \d+\]$", "", p['title']) == base_title]
    parts.sort(key=lambda x: x['title'])
    
    if not parts:
        raise HTTPException(status_code=404, detail="Meeting parts not found")

    canonical_id = parts[0]['id']
    notes_res = supabase_client.table("notes").select("id").eq("meeting_id", canonical_id).execute()
    
    return {
        "id": canonical_id,
        "title": base_title,
        "project": target['project'],
        "meeting_date": target['meeting_date'],
        "has_notes": len(notes_res.data) > 0,
        "parts_count": len(parts),
        "full_transcript": "\n\n".join([p['raw_transcript'] for p in parts]),
        "chunk_ids": [p['id'] for p in parts]
    }

@app.post("/meetings", status_code=status.HTTP_201_CREATED)
async def create_meeting(meeting: MeetingCreate):
    if not supabase_client:
        raise HTTPException(status_code=500, detail="Database connection error")
    
    data = meeting.model_dump()
    res = supabase_client.table("meetings").insert(data).execute()
    if not res.data:
        raise HTTPException(status_code=400, detail="Failed to create meeting")
    
    return res.data[0]

@app.post("/meetings/{meeting_id}/process")
async def process_meeting_endpoint(meeting_id: str):
    if not processor:
        raise HTTPException(status_code=500, detail="Processor configuration error")
    
    notes = processor.process_meeting(meeting_id, force=True)
    if not notes:
        raise HTTPException(status_code=500, detail="Failed to generate notes")
        
    return notes

@app.get("/meetings/{meeting_id}/notes")
async def get_meeting_notes(meeting_id: str):
    if not supabase_client:
        raise HTTPException(status_code=500, detail="Database connection error")
    
    can_id = get_canonical_id(meeting_id)
    res = supabase_client.table("notes").select("*").eq("meeting_id", can_id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Notes not found for this meeting")
    
    return res.data[0]

@app.post("/api/process-pending")
async def process_pending_meetings(background_tasks: BackgroundTasks):
    if not processor:
        return {"status": "error", "message": "Server configuration error."}

    background_tasks.add_task(processor.process_all_pending)
    return {"status": "success", "message": "Started processing in background."}

@app.post("/meetings/import/bulk")
async def bulk_import_google_docs(payload: GoogleDocBulkImport, background_tasks: BackgroundTasks):
    if not supabase_client:
        raise HTTPException(status_code=500, detail="Database connection error")
    
    background_tasks.add_task(process_bulk_import_background, payload)
    
    return {
        "status": "success", 
        "message": "Import started in the background. Documents will be chunked and appear shortly."
    }

@app.get("/api/health")
async def health_check():
    return {"status": "healthy"}

