"""The warehouse frames must match the Snowflake DDL column for column."""

import re
from pathlib import Path

import pytest

from solarmon import config
from solarmon.warehouse import mart_frames, site_frames

SQL_DIR = Path(__file__).resolve().parents[1] / "warehouse"


def ddl_columns() -> dict[str, list[str]]:
    """{'MARTS.EVENTS': ['EVENT_ID', ...]} parsed from every CREATE TABLE in warehouse/*.sql."""
    out = {}
    for f in sorted(SQL_DIR.glob("*.sql")):
        sql = f.read_text()
        for m in re.finditer(r"CREATE TABLE IF NOT EXISTS SOLARMON\.(\w+\.\w+) \((.*?)\n\)", sql, re.S):
            cols = []
            for line in m.group(2).splitlines():
                line = re.sub(r"--.*", "", line).strip()
                word = line.split(" ", 1)[0] if line else ""
                if word and word.isupper() and word not in ("PRIMARY",):
                    cols.append(word)
            out[m.group(1)] = cols
    return out


@pytest.fixture(scope="module")
def processed(tmp_path_factory):
    root = tmp_path_factory.mktemp("data")
    old = config.DATA_DIR
    config.DATA_DIR = root
    try:
        from solarmon.pipeline import build
        build(2107, demo=True, verbose=False)
    finally:
        config.DATA_DIR = old
    return root / "processed" / "2107"


def test_every_frame_matches_its_table(processed):
    ddl = ddl_columns()
    defaults = {"LOADED_AT", "UPDATED_AT"}  # filled by Snowflake
    frames = {**site_frames(), **mart_frames(processed)}
    for table, df in frames.items():
        assert table in ddl, f"{table} has no CREATE TABLE"
        assert list(df.columns) == [c for c in ddl[table] if c not in defaults], table


def test_decisions_table_is_never_loaded(processed):
    assert "MARTS.TICKET_DECISIONS" not in mart_frames(processed)


def test_marts_content(processed):
    f = mart_frames(processed)
    assert f["MARTS.DAILY_PERFORMANCE"]["DAY"].is_unique
    assert f["MARTS.EVENTS"]["EVENT_ID"].is_unique and len(f["MARTS.EVENTS"]) == 7
    assert set(f["MARTS.TICKETS"]["EVENT_ID"]) == set(f["MARTS.EVENTS"]["EVENT_ID"])
    assert f["MARTS.PIPELINE_RUNS"]["RUN_ID"].iloc[0] == f["MARTS.EVENTS"]["RUN_ID"].iloc[0]


def test_site_config_tables():
    f = site_frames()
    assert len(f["RAW.SITES"]) == 5
    m = f["RAW.SIGNAL_MAP"]
    assert m.loc[(m.SYSTEM_ID == 2107) & (m.SIGNAL == "ambient_temp"), "UNIT"].iloc[0] == "F"
    c = f["RAW.FILE_CLOCKS"]
    assert c.loc[c.SYSTEM_ID == 2107, "IS_UTC"].all()
