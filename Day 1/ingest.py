import os
from docx import Document
from supabase import create_client, Client
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()
url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")
supabase = create_client(url, key)

def read_docx(file_path):
    doc = Document(file_path)
    return "\n".join([para.text for para in doc.paragraphs])

def chunk_transcript(text, max_chars=5000):
    return [text[i:i+max_chars] for i in range(0, len(text), max_chars)]

def run_ingestion():
    base_dir = "transcripts"
    print(f"Starting ingestion from: {base_dir}")

    for root, dirs, files in os.walk(base_dir):
        if root == base_dir:
            continue

        for file in files:
            if file.endswith(".docx"):
                file_path = os.path.join(root, file)
                project_name = os.path.basename(root)
                full_content = read_docx(file_path)

                chunks = chunk_transcript(full_content)

                for i, chunk in enumerate(chunks):
                    display_title = file.replace(".docx", "")
                    if len(chunks) > 1:
                        display_title = f"{display_title} [Part {i+1}]"

                    meeting_data = {
                        "title": display_title,
                        "meeting_date": datetime.now().strftime("%Y-%m-%d"),
                        "source": "google meet",
                        "project": project_name,
                        "raw_transcript": chunk
                    }

                    try:
                        supabase.table("meetings").insert(meeting_data).execute()
                        print(f"Success: Saved {display_title} to project {project_name}")
                    except Exception as e:
                        print(f"Error: Failed to save {display_title}. Detail: {e}")

if __name__ == "__main__":
    run_ingestion()
