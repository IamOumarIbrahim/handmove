import urllib.request
import re
import sys

sys.stdout.reconfigure(encoding='utf-8')

url = 'https://www.youtube.com/playlist?list=PLFbzd0m6AcmKQXnUMtlDg2mmfjs2FYYHh'
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
try:
    html = urllib.request.urlopen(req).read().decode('utf-8', errors='ignore')
    vids = list(dict.fromkeys(re.findall(r'/watch\?v=([a-zA-Z0-9_-]{11})', html)))
    print(f"Unique video IDs found: {len(vids)}")
    for v in vids[:15]:
        # fetch video page title
        try:
            v_url = f"https://www.youtube.com/watch?v={v}"
            v_html = urllib.request.urlopen(urllib.request.Request(v_url, headers={'User-Agent': 'Mozilla/5.0'})).read().decode('utf-8', errors='ignore')
            m = re.search(r'<title>(.*?)</title>', v_html)
            title = m.group(1).replace(' - YouTube', '') if m else v
            print(f"  {v}: {title}")
        except Exception as e:
            print(f"  {v}: {e}")
except Exception as e:
    print(e)
