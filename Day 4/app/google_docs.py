import re
import time
import requests
from typing import Optional, Tuple
from .settings import logger

class GoogleDocsService:
    @staticmethod
    def extract_doc_id(url: str) -> Optional[str]:
        pattern = r"/document/d/([a-zA-Z0-9-_]+)"
        match = re.search(pattern, url)
        return match.group(1) if match else None

    @staticmethod
    def extract_folder_id(url: str) -> Optional[str]:
        pattern = r"/folders/([a-zA-Z0-9-_]+)"
        match = re.search(pattern, url)
        return match.group(1) if match else None

    def list_files_in_folder(self, folder_id: str) -> Tuple[Optional[List[dict]], Optional[str]]:
        api_key = settings.GEMINI_API_KEY
        if not api_key:
            return None, "GEMINI_API_KEY (Google API Key) is required to list folder contents."
        
        url = "https://www.googleapis.com/drive/v3/files"
        params = {
            "q": f"'{folder_id}' in parents and mimeType = 'application/vnd.google-apps.document' and trashed = false",
            "key": api_key,
            "fields": "files(id, name)"
        }
        
        try:
            response = requests.get(url, params=params, timeout=10)
            if response.status_code == 200:
                return response.json().get('files', []), None
            elif response.status_code == 403:
                return None, "Access denied. Ensure the folder is public and the API Key is valid with Drive API enabled."
            else:
                error_data = response.json()
                error_msg = error_data.get('error', {}).get('message', 'Unknown error')
                return None, f"Failed to list folder. Status: {response.status_code}, Message: {error_msg}"
        except Exception as e:
            logger.error(f"Error listing folder {folder_id}: {e}")
            return None, str(e)

    def fetch_doc_content(self, doc_id: str, retries: int = 3, backoff_factor: float = 1.5) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        export_url = f"https://docs.google.com/document/d/{doc_id}/export?format=txt"
        html_url = f"https://docs.google.com/document/d/{doc_id}/edit"
        
        last_error = None
        for attempt in range(retries):
            try:
                response = requests.get(export_url, timeout=10)
                if response.status_code != 200:
                    last_error = f"Failed to fetch document content. Status: {response.status_code}"
                    if response.status_code in [401, 403, 404]:
                        return None, None, last_error
                    time.sleep(backoff_factor ** attempt)
                    continue
                    
                content = response.text

                title = "Imported Google Doc"
                html_response = requests.get(html_url, timeout=10)
                if html_response.status_code == 200:
                    import re
                    title_match = re.search(r"<title>(.*?)</title>", html_response.text)
                    if title_match:
                        title = title_match.group(1).replace(" - Google Docs", "").strip()
                
                return title, content, None
            except Exception as e:
                logger.error(f"Error fetching Google Doc {doc_id} on attempt {attempt + 1}: {e}")
                last_error = str(e)
                time.sleep(backoff_factor ** attempt)
                
        return None, None, f"Failed after {retries} attempts. Last error: {last_error}"
