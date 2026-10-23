"""Show which sensors a downloaded site has, and suggest a column mapping for sites.yaml.

Usage:
    python -m solarmon.inspect 2107
"""

from __future__ import annotations

import argparse
import re

import pandas as pd

from .config import get_site
from .load import peek

# Keyword patterns for guessing which raw column is which canonical signal.
# These are suggestions only. Always sanity-check the values before trusting them.
PATTERNS = {
    "ac_power": [r"ac_power", r"inv.*power", r"real_power", r"meter.*power", r"(?<!dc_)power"],
    "poa_irradiance": [r"poa", r"plane.?of.?array", r"pyranometer.*tilt"],
    "module_temp": [r"module.*temp", r"back.?of.?module", r"bom_temp", r"panel.*temp"],
    "ambient_temp": [r"ambient", r"air.?temp"],
    "wind_speed": [r"wind.?speed", r"wind"],
}
EXCLUDE = re.compile(r"dc_|_dc|reactive|apparent|energy|kwh|wh_|status|fault|freq", re.I)


def guess(columns: list[str]) -> dict[str, list[str]]:
    out = {}
    for name, pats in PATTERNS.items():
        hits = []
        for pat in pats:
            for c in columns:
                if re.search(pat, c, re.I) and c not in hits:
                    if name == "ac_power" and EXCLUDE.search(c):
                        continue
                    hits.append(c)
            if hits:
                break  # earlier patterns are more specific; stop at the first that matches
        out[name] = hits
    return out


def describe(df: pd.DataFrame) -> pd.DataFrame:
    num = df.select_dtypes("number")
    return pd.DataFrame({
        "non_null_%": (num.notna().mean() * 100).round(1),
        "min": num.min().round(2),
        "median": num.median().round(2),
        "max": num.max().round(2),
    })


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("system_id", type=int)
    p.add_argument("--nrows", type=int, default=2000)
    args = p.parse_args(argv)

    site = get_site(args.system_id)
    samples = peek(site, args.nrows)
    if not samples:
        raise SystemExit(f"No files in {site.raw_dir}. Run `python -m solarmon.ingest download {site.system_id}` first.")

    all_cols = []
    pd.set_option("display.max_rows", 500, "display.width", 140)
    for path, df in samples.items():
        print(f"\n=== {path.relative_to(site.raw_dir)}  ({len(df.columns)} columns, "
              f"{df.index.min()} -> {df.index.max()})")
        print(describe(df).to_string())
        all_cols.extend(df.columns)

    print("\n--- suggested mapping for config/sites.yaml (check before using) ---")
    print("    columns:")
    for name, hits in guess(all_cols).items():
        if not hits:
            print(f"      {name}: null")
        elif len(hits) == 1:
            print(f"      {name}: {hits[0]}")
        else:
            print(f"      {name}:  # {len(hits)} candidates; ac_power lists are summed, others averaged")
            for h in hits:
                print(f"        - {h}")


if __name__ == "__main__":
    main()
