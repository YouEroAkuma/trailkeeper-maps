#!/usr/bin/env python3
"""Finds the download links of all BEV KM50-R map tiles (Austria, CC BY 4.0).

Writes raw responses to out/ for inspection and, when tiles were found,
out/bev-km50-tiles.json: [{"code", "url", "bbox": [w, s, e, n]}].
"""
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request

UA = "TrailKeeper-maps (open-data conversion; github.com/YouEroAkuma/trailkeeper-maps)"
BASE = "https://data.bev.gv.at/download/KM_R/KM50/"
OUT = "out"
os.makedirs(OUT, exist_ok=True)


def get(url: str, timeout: int = 60) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return 0, str(e)


def save(name: str, text: str):
    with open(os.path.join(OUT, name), "w") as f:
        f.write(text)


tifs: set[str] = set()

# 1) directory listing, followed a few levels deep
seen: set[str] = set()


def crawl(url: str, depth: int):
    if depth > 3 or url in seen:
        return
    seen.add(url)
    status, body = get(url)
    save("listing-" + re.sub(r"[^A-Za-z0-9]+", "_", url[len(BASE):] or "root") + ".html", f"{status}\n{body}")
    if status != 200:
        return
    for href in re.findall(r'href="([^"?#]+)"', body):
        full = urllib.parse.urljoin(url, href)
        if not full.startswith(BASE):
            continue
        if full.lower().endswith(".tif"):
            tifs.add(full)
        elif full.endswith("/") and len(full) > len(url):
            crawl(full, depth + 1)


crawl(BASE, 0)

# 2) catalogue (CSW) search
csw = ("https://data.bev.gv.at/geonetwork/srv/ger/csw?service=CSW&version=2.0.2&request=GetRecords"
       "&typeNames=csw:Record&resultType=results&elementSetName=full&maxRecords=500"
       "&constraintLanguage=CQL_TEXT&constraint_language_version=1.1.0"
       "&constraint=" + urllib.parse.quote("AnyText like '%KM50%'"))
status, body = get(csw, 120)
save("csw.xml", f"{status}\n{body}")
for u in re.findall(r"https?://[^\s<\"']+\.tif", body):
    tifs.add(u)

# 3) tile overview PDF as text (tile numbers), for reference
subprocess.run(["curl", "-sS", "-A", UA, "-o", f"{OUT}/overview.pdf",
                "https://data.bev.gv.at/download/KM_R/KM50/KM50R_Kacheln_Uebersicht.pdf"], check=False)
subprocess.run(["pdftotext", "-layout", f"{OUT}/overview.pdf", f"{OUT}/overview.txt"], check=False)

save("all-tifs.txt", "\n".join(sorted(tifs)))

# keep the coloured map with relief shading, newest date per tile
tiles: dict[str, tuple[str, str]] = {}
for u in tifs:
    m = re.search(r"km50_mit_Relief_(\d+_\d+)_(\d{8})\.tif$", u, re.I)
    if not m:
        continue
    code, date = m.group(1), m.group(2)
    if code not in tiles or date > tiles[code][1]:
        tiles[code] = (u, date)

result = []
for code, (url, date) in sorted(tiles.items()):
    info = subprocess.run(["gdalinfo", "-json", "/vsicurl/" + url], capture_output=True, text=True,
                          env={**os.environ, "GDAL_HTTP_USERAGENT": UA})
    try:
        ext = json.loads(info.stdout)["wgs84Extent"]["coordinates"][0]
        xs = [p[0] for p in ext]
        ys = [p[1] for p in ext]
        bbox = [round(min(xs), 5), round(min(ys), 5), round(max(xs), 5), round(max(ys), 5)]
    except Exception:  # noqa: BLE001
        bbox = None
    result.append({"code": code, "date": date, "url": url, "bbox": bbox})
    print(code, date, bbox, flush=True)

with open(os.path.join(OUT, "bev-km50-tiles.json"), "w") as f:
    json.dump(result, f, indent=1)
print(f"{len(result)} tiles", file=sys.stderr)
