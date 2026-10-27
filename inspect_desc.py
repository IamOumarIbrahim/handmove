import urllib.request
import re
import sys

sys.stdout.reconfigure(encoding='utf-8')

for vid in ['mvLtp1NOsW0', 'h6hcJQmmOPM', '4YHYP55NVeU']:
    url = f"https://www.youtube.com/watch?v={vid}"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    html = urllib.request.urlopen(req).read().decode('utf-8', errors='ignore')
    
    # Extract description
    m = re.search(r'"shortDescription":"(.*?)"', html)
    if m:
        desc = m.group(1).encode('utf-8').decode('unicode_escape')
        print(f"=== {vid} DESCRIPTION ===")
        print(desc[:600])
        print("...")
