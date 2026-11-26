"""Scheduled update: rebuild a site only when something that feeds it has changed.

For each site, a fingerprint covers three things:
    - the NREL file listing (names, sizes, ETags), so new or revised data triggers a run
    - the site's entry in config/sites.yaml, so fixing a mapping or clock offset does too
    - the pipeline code, so a detector change re-processes history

If the fingerprint matches the one saved with the last build, the site is skipped
after a cheap S3 listing. Otherwise: download (only missing files) -> preflight ->
build. A preflight FAIL keeps the previous outputs and reports why; warnings are
saved into meta.json and shown in the app.

Usage (what the GitHub Actions job runs):
    python -m solarmon.update                 # every site with a real column mapping
    python -m solarmon.update --sites 2107 --force
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
from pathlib import Path

from . import config
from .config import Site, get_site, load_sites

INCLUDE = ["meter", "irradiance", "environment"]  # prize-site files the pipeline reads
CODE_DIR = Path(__file__).resolve().parent


def is_mapped(site: Site) -> bool:
    return {"ac_power", "poa_irradiance"} <= set(site.mapped_columns)


def source_listing(site: Site, client=None) -> list[dict]:
    """What NREL currently has for this site (only the files we'd download)."""
    from .ingest import site_objects
    objs = site_objects(site, client=client)
    if site.source == "prize":
        objs = [o for o in objs if "/metadata/" in o["Key"]
                or any(s in o["Key"].rsplit("/", 1)[-1] for s in INCLUDE)]
    return sorted(({"key": o["Key"], "size": int(o["Size"]), "etag": str(o.get("ETag", "")).strip('"')}
                   for o in objs), key=lambda o: o["key"])


def code_hash() -> str:
    h = hashlib.sha256()
    for p in sorted(CODE_DIR.glob("*.py")):
        if p.name not in ("update.py", "warehouse.py", "demo.py", "backtest.py"):
            h.update(p.name.encode() + p.read_bytes())
    return h.hexdigest()[:16]


def fingerprint(site: Site, listing: list[dict]) -> str:
    cfg = {k: v for k, v in dataclasses.asdict(site).items() if k != "raw_dir"}
    blob = json.dumps({"listing": listing, "config": cfg, "code": code_hash()}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def manifest_path(site: Site) -> Path:
    return config.DATA_DIR / "processed" / str(site.system_id) / "source_manifest.json"


def saved_fingerprint(site: Site) -> str | None:
    try:
        return json.loads(manifest_path(site).read_text())["fingerprint"]
    except (FileNotFoundError, KeyError, json.JSONDecodeError):
        return None


def inspect_path(site: Site) -> Path:
    return config.DATA_DIR / "processed" / str(site.system_id) / "inspect.md"


def inspect_unmapped(site: Site, client=None, sample_days: int = 14) -> bool:
    """For a site with no mapping yet: download two weeks of data and commit a column report.

    The report (data/processed/<id>/inspect.md) lists which years exist, every column with
    its value range, and a suggested mapping, which is all it takes to write the site's
    `columns:` entry without downloading anything locally. Runs once per site.
    """
    from datetime import date, timedelta

    from .ingest import download_site, list_prefixes
    from .inspect import report

    dest = inspect_path(site)
    if dest.exists():
        return False
    lines = [f"# Column report: {site.system_id} {site.name}", ""]
    if site.source == "basic":
        base = f"pvdaq/parquet/pvdata/system_id={site.system_id}/"
        years = sorted(int(p.rstrip("/").split("=")[-1]) for p in list_prefixes(base, client) if "year=" in p)
        lines.append(f"Years in the bucket: {', '.join(map(str, years)) or 'none found'}")
        if not years:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text("\n".join(lines) + "\n")
            return True
        # Mid-summer in a middle year: long days, so every signal shows its range
        year = years[len(years) // 2]
        start = date(year, 6, 1)
        download_site(site.system_id, start=start, end=start + timedelta(days=sample_days - 1))
        lines.append(f"Sample: {start} to {start + timedelta(days=sample_days - 1)}")
    else:
        download_site(site.system_id, include=INCLUDE)
    lines += ["", "```", report(site).strip(), "```", ""]
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(lines))
    return True


def update_site(system_id: int, force: bool = False, client=None) -> dict:
    """Returns {'site', 'status', 'detail'}; status is skipped | unchanged | blocked | built."""
    site = get_site(system_id)
    if not is_mapped(site):
        made = inspect_unmapped(site, client)
        return {"site": system_id, "status": "skipped",
                "detail": "no column mapping yet (stays on demo data)"
                          + ("; wrote a column report to map it from" if made else "")}

    listing = source_listing(site, client)
    if not listing:
        return {"site": system_id, "status": "blocked", "detail": "NREL returned no files for this site"}
    fp = fingerprint(site, listing)
    if fp == saved_fingerprint(site) and not force:
        return {"site": system_id, "status": "unchanged", "detail": f"{len(listing)} files, nothing new"}

    from .ingest import download_site
    from .pipeline import build
    from .preflight import FAIL, report, run

    download_site(system_id, include=INCLUDE if site.source == "prize" else None)
    checks, _ = run(site)
    print(report(site, checks))
    if any(c.status == FAIL for c in checks):
        bad = "; ".join(f"{c.name}: {c.detail}" for c in checks if c.status == FAIL)
        return {"site": system_id, "status": "blocked", "detail": f"preflight failed ({bad}); previous outputs kept"}

    meta = build(system_id, preflight=[dataclasses.asdict(c) for c in checks])
    manifest_path(site).write_text(json.dumps({
        "fingerprint": fp, "code": code_hash(), "built_at": meta["built_at"],
        "files": len(listing), "total_mb": round(sum(o["size"] for o in listing) / 1e6, 1),
        "listing": listing,
    }, indent=2) + "\n")
    warns = [c.name for c in checks if c.status == "WARN"]
    return {"site": system_id, "status": "built",
            "detail": f"{meta['data_start']} to {meta['data_end']}, {meta['n_events']} events, "
                      f"nRMSE {meta['nrmse_healthy_pct']:.1f}%"
                      + (f"; preflight warnings: {', '.join(warns)}" if warns else "")}


def summary_markdown(results: list[dict]) -> str:
    icon = {"built": "✅", "unchanged": "⏸️", "skipped": "➖", "blocked": "⚠️"}
    rows = [f"| {icon[r['status']]} {r['site']} | {r['status']} | {r['detail']} |" for r in results]
    return "### Data update\n\n| Site | Result | Detail |\n|---|---|---|\n" + "\n".join(rows) + "\n"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sites", default="auto", help="'auto' (every site in sites.yaml) or space-separated ids")
    p.add_argument("--force", action="store_true", help="rebuild even if nothing changed")
    args = p.parse_args(argv)
    ids = sorted(load_sites()) if args.sites in ("auto", "") else [int(x) for x in args.sites.split()]

    results = []
    for sid in ids:
        try:
            results.append(update_site(sid, force=args.force))
        except Exception as e:  # noqa: BLE001 - one bad site mustn't stop the rest
            results.append({"site": sid, "status": "blocked", "detail": f"{type(e).__name__}: {e}"})
    md = summary_markdown(results)
    print(md)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write(md)
    # Fail the job only if every attempted site broke, so a partial success still commits
    tried = [r for r in results if r["status"] != "skipped"]
    return 1 if tried and all(r["status"] == "blocked" for r in tried) else 0


if __name__ == "__main__":
    raise SystemExit(main())
