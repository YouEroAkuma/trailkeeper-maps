#!/usr/bin/env python3
"""Builds the offline map file of one region.

Usage: build_region.py <region-id> <work-dir> <out-dir>

Writes <out-dir>/<region-id>.pmtiles and <out-dir>/<region-id>.json (catalog entry).
Source sheets are downloaded one at a time, reprojected to Web Mercator at
zoom-15 resolution, cut to the region border (+ buffer) and deleted again, so
disk use stays low.
"""
import datetime as dt
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import urllib.request

from shapely.geometry import box, mapping, shape
from shapely.ops import transform

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = "TrailKeeper-maps (open-data conversion; github.com/YouEroAkuma/trailkeeper-maps)"
NE_URLS = [
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/v5.1.2/geojson/ne_10m_admin_1_states_provinces.geojson",
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_admin_1_states_provinces.geojson",
]
TOP25_FEED = "https://service.pdok.nl/kadaster/brt-topraster/atom/top25raster.xml"
EARTH = 6378137.0
COUNTRY_A3 = {"NL": "NLD", "AT": "AUT"}


def log(*a):
    print(*a, flush=True)


def run(*cmd: str):
    log("+", " ".join(cmd))
    subprocess.run(cmd, check=True)


def fetch(url: str, dest: str):
    run("curl", "-fsSL", "--retry", "5", "--retry-all-errors", "--retry-delay", "10", "-A", UA, "-o", dest, url)


def fetch_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read().decode("utf-8", "replace")


# ------------------------------------------------------------------ geometry

def to_merc(lon, lat, z=None):
    x = math.radians(lon) * EARTH
    y = math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) * EARTH
    return x, y


def from_merc(x, y, z=None):
    lon = math.degrees(x / EARTH)
    lat = math.degrees(2 * math.atan(math.exp(y / EARTH)) - math.pi / 2)
    return lon, lat


def region_polygon(region: dict, buffer_km: float, ne_path: str):
    with open(ne_path) as f:
        ne = json.load(f)
    a3 = COUNTRY_A3[region["country"]]
    feats = [ft for ft in ne["features"] if ft["properties"].get("iso_3166_2") == region["iso"]]
    if not feats:
        names = {n.lower() for n in region["names"]}
        feats = [ft for ft in ne["features"]
                 if ft["properties"].get("adm0_a3") == a3
                 and {str(ft["properties"].get(k, "")).lower() for k in ("name", "name_en", "name_de", "name_nl", "name_alt")} & names]
    if not feats:
        raise SystemExit(f"No border found for {region['id']}")
    geom = shape(feats[0]["geometry"])
    for ft in feats[1:]:
        geom = geom.union(shape(ft["geometry"]))
    lat = geom.centroid.y
    scale = 1 / math.cos(math.radians(lat))  # Web Mercator stretch at this latitude
    merc = transform(to_merc, geom).buffer(buffer_km * 1000 * scale).simplify(50 * scale)
    return transform(from_merc, merc)


# ------------------------------------------------------------------ sources

def nl_top25_sheets() -> list[dict]:
    """Newest TOP25raster GeoTIFF per map sheet, from the PDOK Atom feed."""
    feed = fetch_text(TOP25_FEED)
    sheets: dict[str, dict] = {}
    for tag in re.findall(r"<link\s[^>]*>", feed):
        attrs = dict(re.findall(r'(\w+)="([^"]*)"', tag))
        m = re.search(r"/([0-9]{2}[a-z])-top25raster-(\d{4})\.tif$", attrs.get("href", ""))
        if not m or "bbox" not in attrs:
            continue
        code, year = m.group(1), m.group(2)
        w, s, e, n = (float(v) for v in attrs["bbox"].split())
        if code not in sheets or year > sheets[code]["date"]:
            sheets[code] = {"code": code, "date": year, "url": attrs["href"], "bbox": [w, s, e, n]}
    log(f"TOP25raster: {len(sheets)} sheets in feed")
    return list(sheets.values())


def at_km50_tiles() -> list[dict]:
    with open(os.path.join(ROOT, "data", "bev-km50-tiles.json")) as f:
        return [t for t in json.load(f) if t.get("bbox")]


SOURCES = {"nl-top25": nl_top25_sheets, "at-km50": at_km50_tiles}


# ------------------------------------------------------------------ build

def gtiff_options() -> list[str]:
    formats = subprocess.run(["gdalinfo", "--format", "GTiff"], capture_output=True, text=True).stdout
    comp = ["-co", "COMPRESS=WEBP", "-co", "WEBP_LEVEL=92"] if "WEBP" in formats else ["-co", "COMPRESS=DEFLATE", "-co", "PREDICTOR=2"]
    return ["-co", "TILED=YES", "-co", "BIGTIFF=IF_SAFER", *comp]


def main():
    region_id, work, out = sys.argv[1], sys.argv[2], sys.argv[3]
    os.environ.update({
        "GDAL_HTTP_USERAGENT": UA, "GDAL_HTTP_MAX_RETRY": "8", "GDAL_HTTP_RETRY_DELAY": "10",
        "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR", "GDAL_CACHEMAX": "2048", "VSI_CACHE": "TRUE",
        "CPL_VSIL_CURL_CHUNK_SIZE": "4194304", "GDAL_HTTP_MULTIPLEX": "YES",
    })
    with open(os.path.join(ROOT, "regions.json")) as f:
        cfg = json.load(f)
    region = next(r for r in cfg["regions"] if r["id"] == region_id)
    source = cfg["sources"][region["source"]]
    maxzoom, minzoom = cfg["maxzoom"], cfg["minzoom"]
    res = 2 * math.pi * EARTH / 256 / 2 ** maxzoom

    os.makedirs(work, exist_ok=True)
    os.makedirs(out, exist_ok=True)
    parts = os.path.join(work, "parts")
    os.makedirs(parts, exist_ok=True)

    ne_path = os.path.join(work, "ne_admin1.geojson")
    if not os.path.exists(ne_path):
        for u in NE_URLS:
            try:
                fetch(u, ne_path)
                break
            except subprocess.CalledProcessError:
                continue
    poly = region_polygon(region, cfg["bufferKm"], ne_path)
    cut = os.path.join(work, "cutline.geojson")
    with open(cut, "w") as f:
        json.dump({"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {}, "geometry": mapping(poly)}]}, f)
    log(f"{region['name']}: border bounds {poly.bounds}")

    sheets = [s for s in SOURCES[region["source"]]() if box(*s["bbox"]).intersects(poly)]
    if not sheets:
        raise SystemExit("No source sheets intersect this region")
    log(f"{len(sheets)} source sheets")

    co = gtiff_options()
    for i, s in enumerate(sheets, 1):
        part = os.path.join(parts, f"{s['code']}.tif")
        if os.path.exists(part):
            continue
        log(f"[{i}/{len(sheets)}] {s['code']} {s['date']}")
        src = os.path.join(work, "src.tif")
        if s.get("cog"):
            # Cloud Optimized GeoTIFF: read only the needed parts over HTTP
            src = "/vsicurl/" + s["url"]
        else:
            fetch(s["url"], src)
        info = json.loads(subprocess.run(["gdalinfo", "-json", src], capture_output=True, text=True, check=True).stdout)
        inp = src
        if len(info["bands"]) == 1 and info["bands"][0].get("colorTable"):
            inp = os.path.join(work, "src.vrt")
            run("gdal_translate", "-q", "-of", "VRT", "-expand", "rgb", src, inp)
        # only the part of this sheet that lies inside the region's box
        clip = box(*s["bbox"]).intersection(box(*poly.bounds)).bounds
        x0, y0 = to_merc(clip[0], clip[1])
        x1, y1 = to_merc(clip[2], clip[3])
        run("gdalwarp", "-q", "-overwrite", "-t_srs", "EPSG:3857", "-tr", repr(res), repr(res), "-tap",
            "-te", repr(x0), repr(y0), repr(x1), repr(y1),
            "-r", "average", "-cutline", cut, "-dstalpha", "-multi", "-wo", "NUM_THREADS=ALL_CPUS",
            "-wm", "1024", *co, inp, part)
        for p in (src, os.path.join(work, "src.vrt")):
            if os.path.exists(p):
                os.remove(p)

    # Mosaic with gdalwarp rather than a VRT: the warped sheets have transparent
    # corners, and gdalwarp lets those show the neighbouring sheet underneath.
    # All parts share one pixel grid (-tap), so no resampling happens here.
    vrt = os.path.join(work, "mosaic.tif")
    if os.path.exists(vrt):
        os.remove(vrt)
    run("gdalwarp", "-q", "-r", "near", "-dstalpha", "-multi", "-wo", "NUM_THREADS=ALL_CPUS", "-wm", "1024", *co,
        *sorted(os.path.join(parts, p) for p in os.listdir(parts) if p.endswith(".tif")), vrt)
    shutil.rmtree(parts)
    mbt = os.path.join(work, f"{region_id}.mbtiles")
    if os.path.exists(mbt):
        os.remove(mbt)
    run("gdal_translate", "-q", "-of", "MBTILES", "-co", "TILE_FORMAT=WEBP", "-co", "QUALITY=80",
        "-co", "ZOOM_LEVEL_STRATEGY=AUTO", "-co", f"NAME={region['name']}",
        "-co", f"DESCRIPTION={source['label']}", "-co", "TYPE=baselayer", vrt, mbt)
    factors = [str(2 ** k) for k in range(1, maxzoom - minzoom + 1)]
    run("gdaladdo", "-q", "-r", "average", mbt, *factors)
    os.remove(vrt)

    import sqlite3
    db = sqlite3.connect(mbt)
    db.execute("DELETE FROM metadata WHERE name IN ('attribution', 'bounds')")
    w, s_, e, n = poly.bounds
    db.execute("INSERT INTO metadata (name, value) VALUES ('attribution', ?), ('bounds', ?)",
               (source["attribution"], f"{w:.5f},{s_:.5f},{e:.5f},{n:.5f}"))
    zooms = db.execute("SELECT min(zoom_level), max(zoom_level), count(*) FROM tiles").fetchone()
    db.commit()
    db.close()
    log(f"tiles: zoom {zooms[0]}-{zooms[1]}, {zooms[2]} tiles")

    pm = os.path.join(out, f"{region_id}.pmtiles")
    run("pmtiles", "convert", mbt, pm)
    os.remove(mbt)

    md5 = hashlib.md5()
    with open(pm, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            md5.update(chunk)
    entry = {
        "id": region_id,
        "name": region["name"],
        "country": region["country"],
        "source": source["label"],
        "attribution": source["attribution"],
        "file": f"{region_id}.pmtiles",
        "sizeBytes": os.path.getsize(pm),
        "md5": md5.hexdigest(),
        "bounds": [round(v, 5) for v in poly.bounds],
        "minzoom": zooms[0],
        "maxzoom": zooms[1],
        "tiles": zooms[2],
        "dataDate": max(s["date"] for s in sheets),
        "version": dt.date.today().isoformat(),
    }
    with open(os.path.join(out, f"{region_id}.json"), "w") as f:
        json.dump(entry, f, indent=1, ensure_ascii=False)
    log(json.dumps(entry, ensure_ascii=False))


if __name__ == "__main__":
    main()
