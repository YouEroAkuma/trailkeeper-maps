#!/usr/bin/env python3
"""Merges the per-region entries into catalog.json, the list the app reads.

Usage: make_catalog.py <dir-with-region-json> <release-download-base-url> <out-file>
Regions without a built file are left out.
"""
import datetime as dt
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src_dir, base, out = sys.argv[1], sys.argv[2].rstrip("/"), sys.argv[3]

with open(os.path.join(ROOT, "regions.json")) as f:
    order = [r["id"] for r in json.load(f)["regions"]]

regions = []
for rid in order:
    p = os.path.join(src_dir, f"{rid}.json")
    if not os.path.exists(p):
        continue
    with open(p) as f:
        e = json.load(f)
    e["url"] = f"{base}/{e['file']}"
    regions.append(e)

with open(out, "w") as f:
    json.dump({"format": 1, "updated": dt.date.today().isoformat(), "regions": regions}, f, indent=1, ensure_ascii=False)
print(f"{len(regions)} regions in catalog")
