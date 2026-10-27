import urllib.request
import re

url = 'https://drive.google.com/drive/folders/1-k9yINBCFGpFojViJTvcObI_pFL2pjDQ'
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
}
html = urllib.request.urlopen(urllib.request.Request(url, headers=headers)).read().decode('utf-8', errors='ignore')

# Search for the file ID of '1.2 Wiring and Charging Instruction.pdf'
idx = html.find('1.2 Wiring and Charging Instruction.pdf')
if idx != -1:
    snippet = html[max(0, idx-500):idx+500]
    print("Snippet:")
    print(snippet)
    # Extract file ID (28-33 char base64 string)
    ids = re.findall(r'[a-zA-Z0-9_-]{28,35}', snippet)
    print("Candidate IDs:", ids)
else:
    print("Not found")
