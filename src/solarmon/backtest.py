"""Backtest the detector on many simulated site-histories with known injected faults.

Each seed draws different weather (clouds, temperature) and model error; the faults
are the same seven every time. Reports detection rate, labelling accuracy, detection
delay and false alarms per fault type.

Usage:
    python -m solarmon.backtest --seeds 30
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
        rows.append(bt)
        alarms += [(seed, e.kind, e.start, e.days) for e in false_alarms(events, truth)]
    return pd.concat(rows, ignore_index=True), alarms


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--seeds", type=int, default=30)
    p.add_argument("--site", type=int, default=2107)
    args = p.parse_args(argv)
    bt, alarms = run(args.site, args.seeds)
    summary = bt.groupby("true_kind").agg(
        detected=("detected", "mean"), labelled_right=("correct_kind", "mean"),
        median_delay_days=("delay_days", "median"))
    print(summary.round(3).to_string())
    print(f"\n{bt['detected'].sum()}/{len(bt)} faults found, {bt['correct_kind'].sum()} labelled correctly, "
          f"{len(alarms)} false alarm(s) over {args.seeds * 2} simulated site-years")
    for a in alarms:
        print(f"  false alarm: seed {a[0]}, {a[1]} starting {a[2]} ({a[3]} days)")


if __name__ == "__main__":
    main()
