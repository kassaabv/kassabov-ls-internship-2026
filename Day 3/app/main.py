import os
import logging
from typing import List, Optional
from fastapi import FastAPI, BackgroundTasks, HTTPException, status
from pydantic import BaseModel
from supabase import create_client
from .processor import NoteProcessor
from .settings import settings, logger

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

class MeetingCreate(BaseModel):
    title: str
    project: str
    raw_transcript: str
    meeting_date: Optional[str] = None

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

@app.get("/api/health")
async def health_check():
    return {"status": "healthy"}
