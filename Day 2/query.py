import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()
url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")
supabase = create_client(url, key)

def list_meetings():
    print("Fetching meeting records...")
    try:
        res = supabase.table("meetings").select("id, title, meeting_date, source, project").execute()
        meetings = res.data

        if not meetings:
            print("Status: No records found")
            return

        print("-" * 110)
        print(f"{'ID':<38} | {'DATE':<12} | {'SOURCE':<12} | {'PROJECT':<12} | {'TITLE'}")
        print("-" * 110)

        for m in meetings:
            print(f"{m['id']:<38} | {m['meeting_date']:<12} | {m['source']:<12} | {m['project']:<12} | {m['title']}")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    list_meetings()
