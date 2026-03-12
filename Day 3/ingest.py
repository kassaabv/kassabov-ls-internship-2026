import os
import re
from docx import Document
from supabase import create_client, Client
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()
supabase = create_client(os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY"))

def parse_date_from_filename(filename):
    try:
        match = re.search(r"([A-Za-z]+)\s+(\d{1,2})", filename)
        if match:
            date_str = f"{match.group(1)} {match.group(2)} 2025"
            return datetime.strptime(date_str, "%B %d %Y").strftime("%Y-%m-%d")
    except Exception:
        pass
    return datetime.now().strftime("%Y-%m-%d")

def read_docx(file_path):
    doc = Document(file_path)
    return "\n".join([para.text for para in doc.paragraphs])

def chunk_transcript_recursive(text, max_chars=5000, overlap=500):
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

def get_or_create_session(title, project, meeting_date):
    res = supabase.table("sessions").select("id").eq("title", title).eq("project", project).eq("meeting_date", meeting_date).execute()
    if res.data:
        return res.data[0]['id']
    
    session_data = {
        "title": title,
        "project": project,
        "meeting_date": meeting_date
    }
    res = supabase.table("sessions").insert(session_data).execute()
    if res.data:
        return res.data[0]['id']
    return None

def chunk_exists(session_id, part_number):
    res = supabase.table("meetings").select("id").eq("session_id", session_id).eq("part_number", part_number).execute()
    return len(res.data) > 0

def run_ingestion():
    base_dir = "transcripts"
    for root, dirs, files in os.walk(base_dir):
        if root == base_dir: continue
        for file in files:
            if file.endswith(".docx"):
                file_path = os.path.join(root, file)
                project_name = os.path.basename(root)
                meeting_date = parse_date_from_filename(file)
                full_content = read_docx(file_path)
                
                raw_title = file.replace(".docx", "")
                session_id = get_or_create_session(raw_title, project_name, meeting_date)
                
                if not session_id:
                    print(f"Failed to get/create session for {raw_title}")
                    continue

                chunks = chunk_transcript_recursive(full_content)

                for i, chunk in enumerate(chunks):
                    part_num = i + 1
                    if chunk_exists(session_id, part_num):
                        continue

                    display_title = f"{raw_title} [Part {part_num}]" if len(chunks) > 1 else raw_title
                    meeting_data = {
                        "session_id": session_id,
                        "title": display_title,
                        "meeting_date": meeting_date,
                        "source": "google meet",
                        "project": project_name,
                        "raw_transcript": chunk,
                        "part_number": part_num
                    }
                    try:
                        supabase.table("meetings").insert(meeting_data).execute()
                        print(f"Saved: {display_title} ({project_name})")
                    except Exception as e:
                        print(f"Error saving chunk: {e}")

if __name__ == "__main__":
    run_ingestion()

