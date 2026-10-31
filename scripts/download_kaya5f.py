"""Download the Kaya et al. 2018 "5F" (five-finger motor imagery) EEG files from figshare."""
import os
import zipfile

import requests

ids = {6818732: "A-160408-HFREQ", 6818777: "B-160311-HFREQ", 6818771: "B-160309-HFREQ",
       6818774: "C-160429-HFREQ", 6818741: "E-160415-HFREQ", 6818744: "E-160429-HFREQ",
       6818765: "E-160321-HFREQ", 6818780: "F-160210-HFREQ", 6818783: "G-160413-HFREQ",
       6818753: "G-160428-HFREQ", 6818789: "H-160804-HFREQ", 6818786: "I-160719-HFREQ",
       6818762: "I-160723-HFREQ", 6818672: "A-160405", 6818681: "B-160316", 6818687: "B-151110",
       6818684: "C-151204", 6818678: "F-151027", 6818675: "F-160209", 5554450: "description"}
out = r"C:\Dev\repos\Other\Reverse-Engineer-anything\HANDMOVE\data\kaya5F"
os.makedirs(out, exist_ok=True)


def fetch(url, path):
    with requests.get(url, stream=True, timeout=600) as r:
        r.raise_for_status()
        with open(path, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    return os.path.getsize(path)


failures = []
for i, n in ids.items():
    # The article-level ndownloader zip returns an empty 200, so download each file via the API.
    try:
        meta = requests.get(f"https://api.figshare.com/v2/articles/{i}", timeout=60)
        meta.raise_for_status()
        for f in meta.json()["files"]:
            p = os.path.join(out, f["name"])
            if os.path.exists(p) and os.path.getsize(p) == f["size"]:
                print("skip", n, f["name"], flush=True)
                continue
            size = fetch(f["download_url"], p)
            if size != f["size"]:
                raise IOError(f"{f['name']}: got {size} bytes, expected {f['size']}")
            if p.endswith(".zip"):
                with zipfile.ZipFile(p) as z:
                    z.extractall(out)
                os.remove(p)
            print("ok", n, f["name"], size, flush=True)
    except Exception as e:
        print("FAILED", n, e, flush=True)
        failures.append(n)

print("failures:", failures)
