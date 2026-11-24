"""Load the pipeline's outputs into Snowflake (schemas in warehouse/*.sql).

`site_frames` and `mart_frames` shape everything into DataFrames whose columns match
the tables exactly (a test parses the SQL to keep the two in sync), so the shaping is
checked offline and the Snowflake part is just a write.

Each load replaces one site's rows in a single transaction, so a rerun never
duplicates data and the app never reads a half-written site. TICKET_DECISIONS is
never touched: reviewer decisions survive every rebuild.

Usage:
    python -m solarmon.warehouse push all          # needs SNOWFLAKE_* env vars (below)
    python -m solarmon.warehouse export all out/   # same frames as parquet, no Snowflake needed

Connection settings come from the environment: SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER,
SNOWFLAKE_PASSWORD (or SNOWFLAKE_PRIVATE_KEY_FILE), SNOWFLAKE_ROLE (default
SOLARMON_PIPELINE), SNOWFLAKE_WAREHOUSE (default SOLARMON_WH).
Install the connector with: pip install "snowflake-connector-python[pandas]"
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import pandas as pd

from . import config
from .config import load_sites

DATABASE = "SOLARMON"


def run_id(meta: dict) -> str:
    return f"{meta['site']['system_id']}-{meta['built_at']}"


def site_frames() -> dict[str, pd.DataFrame]:
    """RAW.SITES, RAW.SIGNAL_MAP and RAW.FILE_CLOCKS from config/sites.yaml."""
    sites, signals, clocks = [], [], []
    for sid, s in load_sites().items():
        sites.append({"SYSTEM_ID": sid, "NAME": s.name, "LOCATION": s.location, "LATITUDE": s.latitude,
                      "LONGITUDE": s.longitude, "TIMEZONE": s.timezone, "DC_CAPACITY_KW": s.dc_capacity_kw,
                      "AC_CAPACITY_KW": s.ac_capacity_kw, "MOUNT": s.mount, "TILT": s.tilt,
                      "AZIMUTH": s.azimuth})
        for signal, raw in s.mapped_columns.items():
            for col in ([raw] if isinstance(raw, str) else raw):
                signals.append({"SYSTEM_ID": sid, "SIGNAL": signal, "RAW_COLUMN": col,
                                "UNIT": s.units.get(signal)})
        patterns = set(s.utc_files) | set(s.file_offsets_h)
        for pat in sorted(patterns):
            clocks.append({"SYSTEM_ID": sid, "FILE_PATTERN": pat, "IS_UTC": pat in s.utc_files,
                           "OFFSET_HOURS": float(s.file_offsets_h.get(pat, 0.0))})
    return {
        "RAW.SITES": pd.DataFrame(sites),
        "RAW.SIGNAL_MAP": pd.DataFrame(signals, columns=["SYSTEM_ID", "SIGNAL", "RAW_COLUMN", "UNIT"]),
        "RAW.FILE_CLOCKS": pd.DataFrame(clocks, columns=["SYSTEM_ID", "FILE_PATTERN", "IS_UTC", "OFFSET_HOURS"]),
    }


def mart_frames(site_dir: Path) -> dict[str, pd.DataFrame]:
    """The MARTS tables for one site, from data/processed/<id>/."""
    meta = json.loads((site_dir / "meta.json").read_text())
    events = json.loads((site_dir / "events.json").read_text())
    tickets = json.loads((site_dir / "tickets.json").read_text())
    sid, rid = int(meta["site"]["system_id"]), run_id(meta)

    intr = pd.read_parquet(site_dir / "intraday.parquet")
    intr = pd.DataFrame({
        "SYSTEM_ID": sid, "INTERVAL_START": intr.index,
        "AC_POWER_KW": intr["ac_power_kw"].to_numpy(), "EXPECTED_AC_KW": intr["expected_ac_kw"].to_numpy(),
        "POA_IRRADIANCE": intr["poa_irradiance"].to_numpy(), "AMBIENT_TEMP": intr["ambient_temp"].to_numpy(),
        "RUN_ID": rid,
    })

    daily = pd.read_parquet(site_dir / "daily.parquet")
    daily = daily.rename(columns=str.upper).rename_axis("DAY").reset_index()
    daily["DAY"] = pd.to_datetime(daily["DAY"]).dt.date
    daily.insert(0, "SYSTEM_ID", sid)
    daily["DATA_GAP"] = daily["DATA_GAP"].astype("boolean")
    daily["RUN_ID"] = rid
    daily = daily[_DAILY_COLS]

    ev = pd.DataFrame([{
        "EVENT_ID": e["id"], "SYSTEM_ID": sid, "KIND": e["kind"], "LABEL": e["label"],
        "START_DAY": pd.Timestamp(e["start"]).date(), "END_DAY": pd.Timestamp(e["end"]).date(),
        "DAYS": e["days"], "ACTIVE": e["active"], "SEVERITY": e["severity"], "PI_BEFORE": e["pi_before"],
        "PI_DURING": e["pi_during"], "ENERGY_LOST_KWH": e["energy_lost_kwh"], "EST_COST_USD": e["est_cost_usd"],
        "LOSS_PCT": e["loss_pct"], "EVIDENCE": json.dumps(e["evidence"]), "RUN_ID": rid,
    } for e in events], columns=_EVENT_COLS)

    body_keys = ("summary", "evidence", "likely_causes", "recommended_actions", "parts_and_tools",
                 "safety_notes", "draft_note")
    tk = pd.DataFrame([{
        "TICKET_ID": t["ticket_id"], "EVENT_ID": t["event_id"], "SYSTEM_ID": sid, "KIND": t["kind"],
        "TITLE": t["title"], "PRIORITY": t["priority"],
        "BODY": json.dumps({k: t[k] for k in body_keys if k in t}),
        "DRAFTED_BY": t["drafted_by"], "DRAFTED_AT": pd.Timestamp(t["drafted_at"]).tz_localize(None),
        "RUN_ID": rid,
    } for t in tickets], columns=_TICKET_COLS)

    runs = pd.DataFrame([{
        "RUN_ID": rid, "SYSTEM_ID": sid, "SOURCE": meta["source"],
        "STARTED_AT": pd.Timestamp(meta["built_at"]).tz_localize(None),
        "DATA_START": pd.Timestamp(meta["data_start"]).date(), "DATA_END": pd.Timestamp(meta["data_end"]).date(),
        "CALIBRATION_SCALE": meta["calibration_scale"], "AC_CAPACITY_KW": meta["ac_capacity_kw"],
        "NRMSE_HEALTHY_PCT": meta["nrmse_healthy_pct"], "N_EVENTS": meta["n_events"],
    }])
    return {"MARTS.INTERVAL_PERFORMANCE": intr, "MARTS.DAILY_PERFORMANCE": daily, "MARTS.EVENTS": ev,
            "MARTS.TICKETS": tk, "MARTS.PIPELINE_RUNS": runs}


_DAILY_COLS = ["SYSTEM_ID", "DAY", "ACTUAL_KWH", "EXPECTED_KWH", "PI", "BASELINE_PI", "DEV", "POA_KWH_M2",
               "ACTUAL_KWH_DAY", "EXPECTED_KWH_DAY", "DATA_GAP", "FLAG", "EVENT_KIND", "RUN_ID"]
_EVENT_COLS = ["EVENT_ID", "SYSTEM_ID", "KIND", "LABEL", "START_DAY", "END_DAY", "DAYS", "ACTIVE", "SEVERITY",
               "PI_BEFORE", "PI_DURING", "ENERGY_LOST_KWH", "EST_COST_USD", "LOSS_PCT", "EVIDENCE", "RUN_ID"]
_TICKET_COLS = ["TICKET_ID", "EVENT_ID", "SYSTEM_ID", "KIND", "TITLE", "PRIORITY", "BODY", "DRAFTED_BY",
                "DRAFTED_AT", "RUN_ID"]
VARIANT_COLS = {"MARTS.EVENTS": ["EVIDENCE"], "MARTS.TICKETS": ["BODY"]}


# --------------------------------------------------------------------------- Snowflake

def connect():
    import snowflake.connector
    kw = dict(account=os.environ["SNOWFLAKE_ACCOUNT"], user=os.environ["SNOWFLAKE_USER"],
              role=os.environ.get("SNOWFLAKE_ROLE", "SOLARMON_PIPELINE"),
              warehouse=os.environ.get("SNOWFLAKE_WAREHOUSE", "SOLARMON_WH"), database=DATABASE)
    if os.environ.get("SNOWFLAKE_PRIVATE_KEY_FILE"):
        kw["private_key_file"] = os.environ["SNOWFLAKE_PRIVATE_KEY_FILE"]
    else:
        kw["password"] = os.environ["SNOWFLAKE_PASSWORD"]
    return snowflake.connector.connect(**kw)


def replace_rows(conn, table: str, df: pd.DataFrame, where: str = "", params: tuple = ()) -> None:
    """Delete the rows this load owns, then append df. Caller wraps it in a transaction."""
    from snowflake.connector.pandas_tools import write_pandas
    schema, name = table.split(".")
    cur = conn.cursor()
    cur.execute(f"DELETE FROM {DATABASE}.{schema}.{name}" + (f" WHERE {where}" if where else ""), params)
    if df.empty:
        return
    variant = VARIANT_COLS.get(table, [])
    if not variant:
        write_pandas(conn, df, name, database=DATABASE, schema=schema, quote_identifiers=False,
                     use_logical_type=True)
        return
    # VARIANT columns: land as text in a temp table, then PARSE_JSON on insert
    tmp = f"{name}_LOAD"
    cur.execute(f"CREATE TEMPORARY TABLE {DATABASE}.{schema}.{tmp} LIKE {DATABASE}.{schema}.{name}")
    for c in variant:
        cur.execute(f"ALTER TABLE {DATABASE}.{schema}.{tmp} ALTER COLUMN {c} SET DATA TYPE VARCHAR")
    write_pandas(conn, df, tmp, database=DATABASE, schema=schema, quote_identifiers=False, use_logical_type=True)
    cols = ", ".join(f"PARSE_JSON({c})" if c in variant else c for c in df.columns)
    cur.execute(f"INSERT INTO {DATABASE}.{schema}.{name} ({', '.join(df.columns)}) "
                f"SELECT {cols} FROM {DATABASE}.{schema}.{tmp}")
    cur.execute(f"DROP TABLE {DATABASE}.{schema}.{tmp}")


def push(system_ids: list[int]) -> None:
    conn = connect()
    try:
        conn.cursor().execute("BEGIN")
        for table, df in site_frames().items():
            replace_rows(conn, table, df)
        for sid in system_ids:
            for table, df in mart_frames(config.DATA_DIR / "processed" / str(sid)).items():
                replace_rows(conn, table, df, "SYSTEM_ID = %s", (sid,))
            print(f"  loaded site {sid}")
        conn.cursor().execute("COMMIT")
    except Exception:
        conn.cursor().execute("ROLLBACK")
        raise
    finally:
        conn.close()


def export(system_ids: list[int], dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    frames = dict(site_frames())
    for sid in system_ids:
        for table, df in mart_frames(config.DATA_DIR / "processed" / str(sid)).items():
            frames[table] = pd.concat([frames.get(table, pd.DataFrame()), df], ignore_index=True)
    for table, df in frames.items():
        df.to_parquet(dest / f"{table.lower()}.parquet")
        print(f"  {table:<30} {len(df):>8,} rows")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("push", "export"):
        s = sub.add_parser(name)
        s.add_argument("system_id", help="a system id, or 'all' (every site with processed data)")
        if name == "export":
            s.add_argument("dest", type=Path)
    args = p.parse_args(argv)
    proc = config.DATA_DIR / "processed"
    ids = (sorted(int(d.name) for d in proc.iterdir() if (d / "meta.json").exists())
           if args.system_id == "all" else [int(args.system_id)])
    push(ids) if args.cmd == "push" else export(ids, args.dest)


if __name__ == "__main__":
    main()
