"""Scheduled update against a fake NREL bucket: builds once, then skips until something changes."""

import dataclasses
import json
import shutil

import pytest

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent))

from solarmon import config, ingest, update
from solarmon.config import get_site

from test_preflight import write_raw

PREFIX = "pvdaq/2023-solar-data-prize/2107_OEDI/"


@pytest.fixture
def bucket(tmp_path, monkeypatch):
    """Site 2107's files laid out as in the real bucket, served by a fake S3 client."""
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "bucket_src")
    staging = get_site(2107)
    write_raw(staging)  # meter, UTC irradiance, environment CSVs
    src_dir = staging.raw_dir / "data"
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    root = tmp_path / "bucket"
    (root / PREFIX / "data").mkdir(parents=True)
    for f in src_dir.iterdir():
        shutil.copy(f, root / PREFIX / "data" / f.name)

    def listing(site, fmt="parquet", start=None, end=None, client=None):
        return [{"Key": str(p.relative_to(root)), "Size": p.stat().st_size, "ETag": f'"{p.stat().st_mtime_ns}"'}
                for p in sorted(root.rglob("*")) if p.is_file()]

    class FakeS3:
        downloads = []

        def download_file(self, bucket_name, key, dest):
            self.downloads.append(key)
            shutil.copy(root / key, dest)

    fake = FakeS3()
    monkeypatch.setattr(ingest, "site_objects", listing)
    monkeypatch.setattr(ingest, "s3_client", lambda: fake)
    return root, fake


def test_builds_then_skips_then_rebuilds_on_new_data(bucket):
    root, s3 = bucket
    r = update.update_site(2107)
    assert r["status"] == "built", r
    out = config.DATA_DIR / "processed" / "2107"
    meta = json.loads((out / "meta.json").read_text())
    assert meta["source"] == "pvdaq" and "preflight" in meta
    assert json.loads((out / "source_manifest.json").read_text())["files"] == 3
    n = len(s3.downloads)

    assert update.update_site(2107)["status"] == "unchanged"
    assert len(s3.downloads) == n  # nothing re-downloaded

    extra = root / PREFIX / "data" / "2107_environment_data_2.csv"
    shutil.copy(root / PREFIX / "data" / "2107_environment_data.csv", extra)
    assert update.update_site(2107)["status"] == "built"
    assert s3.downloads[n:] == [str(extra.relative_to(root))]  # only the new file


def test_config_change_triggers_rebuild(bucket, monkeypatch):
    assert update.update_site(2107)["status"] == "built"
    site = get_site(2107)
    monkeypatch.setattr(update, "get_site", lambda i: dataclasses.replace(site, file_offsets_h={"meter": 0.25}))
    assert update.fingerprint(update.get_site(2107), []) != update.fingerprint(site, [])


def test_failed_preflight_keeps_previous_outputs(bucket, monkeypatch):
    root, _ = bucket
    assert update.update_site(2107)["status"] == "built"
    before = (config.DATA_DIR / "processed" / "2107" / "meta.json").read_text()
    site = get_site(2107)
    broken = dataclasses.replace(site, columns={**site.columns, "ac_power": "no_such_column"})
    monkeypatch.setattr(update, "get_site", lambda i: broken)
    import solarmon.ingest as ing
    monkeypatch.setattr(ing, "get_site", lambda i: broken)
    r = update.update_site(2107)
    assert r["status"] == "blocked" and "previous outputs kept" in r["detail"]
    assert (config.DATA_DIR / "processed" / "2107" / "meta.json").read_text() == before


def test_unmapped_sites_are_skipped():
    assert update.update_site(4902)["status"] == "skipped"
