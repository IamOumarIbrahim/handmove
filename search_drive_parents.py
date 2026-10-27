import urllib.request
import re

url = 'https://drive.google.com/drive/u/0/mobile/folders/1-k9yINBCFGpFojViJTvcObI_pFL2pjDQ'
headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
html = urllib.request.urlopen(urllib.request.Request(url, headers=headers)).read().decode('utf-8', errors='ignore')

# Search for any parent folder ID or other folder IDs
folder_ids = re.findall(r'folders/([a-zA-Z0-9_-]{25,})', html)
print("Folder IDs found:", set(folder_ids))

# Search for all strings matching Google Drive IDs
all_ids = set(re.findall(r'[a-zA-Z0-9_-]{33}', html))
print("All 33-char IDs found:", len(all_ids))

# Look for text near "uHand" or "Arduino"
for m in re.finditer(r'uHand|Arduino|Knob|Source|Code|Lesson|Program', html, re.IGNORECASE):
    snippet = html[max(0, m.start()-100):min(len(html), m.end()+100)]
    print("--- SNIPPET ---")
    print(snippet)
