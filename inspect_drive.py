import urllib.request
import re
import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

url = 'https://drive.google.com/drive/folders/1-k9yINBCFGpFojViJTvcObI_pFL2pjDQ'
headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
req = urllib.request.Request(url, headers=headers)
try:
    with urllib.request.urlopen(req) as response:
        content = response.read().decode('utf-8', errors='ignore')
        print(f"Content length: {len(content)}")
        
        # Search for folder / file items in drive payload
        pattern = re.compile(r'\["([^"]+)",\["([^"]+)"\]')
        matches = re.findall(r'\["([A-Za-z0-9 _\-\.\(\)]+)",\[', content)
        print("Matches sample:", matches[:20])

        # Find any files
        file_matches = set(re.findall(r'([A-Za-z0-9 _\-\.\(\)]+\.(?:ino|zip|pdf|rar|docx|exe|apk))', content, re.IGNORECASE))
        print("Found files:", file_matches)

        # Look for folder names
        folder_names = set(re.findall(r'\["([0-9]+\.[^"]+)"', content))
        print("Folder names:", folder_names)

        # Look for Arduino / code mentions
        code_mentions = set(re.findall(r'([A-Za-z0-9_\- ]*(?:Arduino|Course|Code|Program|Tutorial|uHand|Knob)[A-Za-z0-9_\- ]*)', content, re.IGNORECASE))
        print("Code mentions:", list(code_mentions)[:25])

except Exception as e:
    print("Error:", e)
