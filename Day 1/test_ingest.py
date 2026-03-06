import os
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()

def test_supabase_connection():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    client = create_client(url, key)

    res = client.table("meetings").select("id").limit(1).execute()

    assert res.data is not None
    print("Database connection is healthy.")

def test_database_has_records():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    client = create_client(url, key)

    res = client.table("meetings").select("id", count="exact").execute()

    assert len(res.data) >= 3
    print(f"Database contains {len(res.data)} records.")
