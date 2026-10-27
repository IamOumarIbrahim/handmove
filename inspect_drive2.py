import urllib.request
import re
import sys

sys.stdout.reconfigure(encoding='utf-8')

url = 'https://drive.google.com/drive/folders/1-k9yINBCFGpFojViJTvcObI_pFL2pjDQ'
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9'
}
req = urllib.request.Request(url, headers=headers)
try:
    html = urllib.request.urlopen(req).read().decode('utf-8', errors='ignore')
    
    # In Google Drive, items in folder view often appear in _DRIVE_BOOTSTRAP_DATA or similar JS structures
    # Let's search for all file/folder names
    items = re.findall(r'\["([0-9a-zA-Z_\-]{25,})",\["([^"]+)"', html)
    print(f"Items found: {len(items)}")
    for fid, fname in items:
        print(f"  ID: {fid} | Name: {fname}")
        
    # Another pattern: ["Name",null,"id"...]
    names = re.findall(r'\["([A-Za-z0-9\.\-_ \(\)]+\.(?:pdf|zip|ino|rar|docx|xlsx|apk|exe))"', html)
    print("Files found:", set(names))

    # Look for folder titles
    folder_titles = re.findall(r'\["([0-9]+[A-Za-z0-9\.\-_ \(\)]+)"', html)
    print("Folder titles found:", set(folder_titles))

except Exception as e:
    print(e)
