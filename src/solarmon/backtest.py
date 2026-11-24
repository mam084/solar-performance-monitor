"""Backtest the detector on many simulated site-histories with known injected faults.

Each seed draws different weather (clouds, temperature) and model error; the faults
are the same seven every time. Reports detection rate, labelling accuracy, detection
delay and false alarms per fault type.

Usage:
    python -m solarmon.backtest --seeds 30            # site 2107
    python -m solarmon.backtest --seeds 30 --site all # every site in sites.yaml
"""

from __future__ import annotations

import argparse
import warnings

import pandas as pd

from .config import get_site
from .demo import make_demo
from .detect import backtest, detect_events, false_alarms
from .expected import expected_ac_kw
from .metrics import daily_performance


def run(system_id: int = 2107, seeds: int = 30) -> tuple[pd.DataFrame, list]:
    site = get_site(system_id)
    rows, alarms = [], []
    for seed in range(1, seeds + 1):
        df, faults = make_demo(site, seed=seed)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            out = expected_ac_kw(df, site)
        events, _ = detect_events(out, daily_performance(out), site.system_id)
        truth = pd.DataFrame([f.__dict__ for f in faults])
        bt = backtest(events, truth)
        bt["seed"] = seed
        bt["site"] = system_id
        rows.append(bt)
        alarms += [(system_id, seed, e.kind, e.start, e.days) for e in false_alarms(events, truth)]
    return pd.concat(rows, ignore_index=True), alarms


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--seeds", type=int, default=30)
    p.add_argument("--site", default="2107", help="a system id, or 'all'")
    args = p.parse_args(argv)
    from .config import load_sites
    ids = sorted(load_sites()) if args.site == "all" else [int(args.site)]
    parts = [run(i, args.seeds) for i in ids]
    bt = pd.concat([b for b, _ in parts], ignore_index=True)
    alarms = [a for _, al in parts for a in al]
    summary = bt.groupby("true_kind").agg(
        detected=("detected", "mean"), labelled_right=("correct_kind", "mean"),
        median_delay_days=("delay_days", "median"))
    print(summary.round(3).to_string())
    print(f"\n{bt['detected'].sum()}/{len(bt)} faults found, {bt['correct_kind'].sum()} labelled correctly, "
          f"{len(alarms)} false alarm(s) over {args.seeds * 2 * len(ids)} simulated site-years")
    for a in alarms:
        print(f"  false alarm: site {a[0]} seed {a[1]}, {a[2]} starting {a[3]} ({a[4]} days)")
    misses = bt[~bt["correct_kind"]]
    for r in misses.itertuples():
        print(f"  {'mislabelled' if r.detected else 'missed'}: site {r.site} seed {r.seed}, "
              f"{r.true_kind}" + (f" called {r.detected_kind}" if r.detected else ""))


if __name__ == "__main__":
    main()
