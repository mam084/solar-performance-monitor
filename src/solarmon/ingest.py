"""Download PVDAQ data from NREL's public OEDI data lake (no AWS account needed).

Two layouts exist on the data lake:

* basic sites:  pvdaq/<fmt>/pvdata/system_id=<id>/year=<y>/month=<m>/day=<d>/<file>
                (one file per day; fmt is "parquet" or "csv")
* prize sites:  pvdaq/2023-solar-data-prize/<id>_OEDI/data/<file>.csv
                (a handful of large CSVs per site, plus a metadata/ folder)

Usage:
    python -m solarmon.ingest ls pvdaq/parquet/                # browse the bucket
    python -m solarmon.ingest download 4902 --start 2016-01-01 --end 2016-12-31
    python -m solarmon.ingest download 2107 --dry-run          # see what would download
"""

from __future__ import annotations

import argparse
import re
from datetime import date
from pathlib import Path

import boto3
from botocore import UNSIGNED
from botocore.config import Config

from .config import Site, get_site

BUCKET = "oedi-data-lake"
_PARTITION_RE = re.compile(r"year=(\d{4})/month=(\d{1,2})/day=(\d{1,2})/")


def s3_client():
    """Anonymous S3 client — the OEDI bucket is public."""
    return boto3.client("s3", config=Config(signature_version=UNSIGNED))


def list_keys(prefix: str, client=None) -> list[dict]:
    """All objects under a prefix: [{'Key': ..., 'Size': ...}, ...]."""
    client = client or s3_client()
    out = []
    for page in client.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=prefix):
        out.extend(page.get("Contents", []))
    return out


def list_prefixes(prefix: str, client=None) -> list[str]:
    """One level of 'folders' under a prefix, like `aws s3 ls`."""
    client = client or s3_client()
    out = []
    for page in client.get_paginator("list_objects_v2").paginate(
        Bucket=BUCKET, Prefix=prefix, Delimiter="/"
    ):
        out.extend(p["Prefix"] for p in page.get("CommonPrefixes", []))
        out.extend(o["Key"] for o in page.get("Contents", []))
    return out


def partition_date(key: str) -> date | None:
    m = _PARTITION_RE.search(key)
    return date(*map(int, m.groups())) if m else None


def site_objects(site: Site, fmt: str = "parquet", start: date | None = None,
                 end: date | None = None, client=None) -> list[dict]:
    """Objects to download for a site, filtered to [start, end] for basic sites."""
    client = client or s3_client()
    if site.source == "prize":
        root = f"pvdaq/2023-solar-data-prize/{site.system_id}_OEDI/"
        objs = list_keys(root + "data/", client) + list_keys(root + "metadata/", client)
        return [o for o in objs if not o["Key"].endswith("/")]

    base = f"pvdaq/{fmt}/pvdata/system_id={site.system_id}/"
    # Narrow the listing to the requested years so we don't page through decades of keys.
    years = range(start.year, end.year + 1) if start and end else [None]
    objs = []
    for y in years:
        objs.extend(list_keys(base + (f"year={y}/" if y else ""), client))
    if start or end:
        def keep(o):
            d = partition_date(o["Key"])
            return d is not None and (not start or d >= start) and (not end or d <= end)
        objs = [o for o in objs if keep(o)]
    return objs


def local_path(site: Site, key: str) -> Path:
    """Mirror the bucket layout under data/raw/<id>/ so daily files never collide."""
    if site.source == "prize":
        rel = key.split(f"{site.system_id}_OEDI/", 1)[1]
    else:
        rel = key.split(f"system_id={site.system_id}/", 1)[1]
    return site.raw_dir / rel


def download_site(system_id: int, fmt: str = "parquet", start: date | None = None,
                  end: date | None = None, dry_run: bool = False) -> list[Path]:
    site = get_site(system_id)
    client = s3_client()
    objs = site_objects(site, fmt, start, end, client)
    total_mb = sum(o["Size"] for o in objs) / 1e6
    print(f"[{site.system_id}] {site.name}: {len(objs)} files, {total_mb:,.1f} MB")
    if site.source == "prize" and (start or end):
        print("  note: prize sites are stored as whole-period CSVs; --start/--end don't apply")
    if not objs:
        print("  nothing found; check the system id and dates with `python -m solarmon.ingest ls`")
    if dry_run:
        for o in objs[:20]:
            print(f"  {o['Key']}  ({o['Size'] / 1e6:.2f} MB)")
        if len(objs) > 20:
            print(f"  ... and {len(objs) - 20} more")
        return []

    paths = []
    for i, o in enumerate(objs, 1):
        dest = local_path(site, o["Key"])
        if dest.exists() and dest.stat().st_size == o["Size"]:
            paths.append(dest)
            continue  # already have it; downloads are resumable
        dest.parent.mkdir(parents=True, exist_ok=True)
        client.download_file(BUCKET, o["Key"], str(dest))
        paths.append(dest)
        if i % 50 == 0 or i == len(objs):
            print(f"  {i}/{len(objs)} downloaded")
    return paths


def _date(s: str) -> date:
    return date.fromisoformat(s)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    ls = sub.add_parser("ls", help="list one level of the bucket under a prefix")
    ls.add_argument("prefix", nargs="?", default="pvdaq/")

    dl = sub.add_parser("download", help="download one site's data into data/raw/<id>/")
    dl.add_argument("system_id", type=int)
    dl.add_argument("--format", default="parquet", choices=["parquet", "csv"])
    dl.add_argument("--start", type=_date, help="YYYY-MM-DD (basic sites only)")
    dl.add_argument("--end", type=_date, help="YYYY-MM-DD (basic sites only)")
    dl.add_argument("--dry-run", action="store_true")

    args = p.parse_args(argv)
    if args.cmd == "ls":
        for x in list_prefixes(args.prefix):
            print(x)
    else:
        download_site(args.system_id, args.format, args.start, args.end, args.dry_run)


if __name__ == "__main__":
    main()
