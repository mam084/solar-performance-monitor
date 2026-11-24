"""Detector, ticket agent, review log and pipeline, all offline."""

import json
from types import SimpleNamespace

import pandas as pd
import pytest

from solarmon import config, review
from solarmon.config import get_site
from solarmon.demo import make_demo
from solarmon.detect import backtest, detect_events, false_alarms
from solarmon.expected import expected_ac_kw
from solarmon.metrics import daily_performance
from solarmon.tickets import TICKET_SCHEMA, claude_ticket, draft_ticket, template_ticket


@pytest.fixture(scope="module")
def demo_run():
    site = get_site(2107)
    df, faults = make_demo(site)
    out = expected_ac_kw(df, site)
    events, daily = detect_events(out, daily_performance(out), site.system_id)
    truth = pd.DataFrame([f.__dict__ for f in faults])
    return site, events, daily, truth


def test_detector_finds_and_labels_every_injected_fault(demo_run):
    _, events, _, truth = demo_run
    bt = backtest(events, truth)
    assert bt["detected"].all(), bt
    assert bt["correct_kind"].all(), bt
    assert false_alarms(events, truth) == []


def test_abrupt_faults_flagged_same_day(demo_run):
    _, events, _, truth = demo_run
    bt = backtest(events, truth)
    abrupt = bt[bt["true_kind"].isin(["outage", "partial_outage", "sensor_fault", "data_gap"])]
    assert (abrupt["delay_days"] == 0).all(), abrupt


def test_ongoing_fault_is_active_and_sized(demo_run):
    _, events, _, _ = demo_run
    active = [e for e in events if e.active]
    assert len(active) == 1 and active[0].kind == "partial_outage"
    assert active[0].evidence["capacity_offline_pct"] == pytest.approx(12, abs=4)


def test_soiling_traces_back_to_when_decline_began(demo_run):
    _, events, _, truth = demo_run
    soil = next(e for e in events if e.kind == "soiling")
    began = pd.Timestamp(soil.evidence["decline_began"])
    true_start = pd.Timestamp(truth.loc[truth["kind"] == "soiling", "start"].iloc[0])
    assert abs((began - true_start).days) <= 14


def test_sensor_and_gap_events_claim_no_lost_energy(demo_run):
    _, events, _, _ = demo_run
    for e in events:
        if e.kind in ("sensor_fault", "data_gap"):
            assert e.energy_lost_kwh == 0 and e.loss_pct is None


def test_healthy_site_raises_no_events():
    site = get_site(2107)
    df, _ = make_demo(site, start="2023-01-01", end="2024-01-01", faults=[], seed=3)
    out = expected_ac_kw(df, site)
    events, _ = detect_events(out, daily_performance(out), site.system_id)
    assert events == []


# ----------------------------------------------------------------------------- tickets

def _event(demo_run, kind):
    site, events, _, _ = demo_run
    from solarmon.pipeline import site_dict
    return next(e for e in events if e.kind == kind).to_dict(), site_dict(site)


def test_template_ticket_has_full_schema(demo_run):
    ev, site = _event(demo_run, "partial_outage")
    t = template_ticket(ev, site)
    for k in TICKET_SCHEMA["required"]:
        assert t[k], k
    assert t["status"] == "pending_review" and t["drafted_by"] == "template"
    assert t["priority"] == "P2"


class FakeClient:
    """Stands in for anthropic.Anthropic; records the request, returns a tool call."""

    def __init__(self, body):
        self.body, self.sent = body, None
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kw):
        self.sent = kw
        return SimpleNamespace(content=[SimpleNamespace(type="tool_use", input=self.body)])


def test_claude_ticket_forces_tool_and_sends_evidence(demo_run):
    ev, site = _event(demo_run, "outage")
    body = {"title": "Inverter trip", "priority": "P1", "summary": "s", "evidence": ["e"],
            "likely_causes": ["c"], "recommended_actions": ["a"], "parts_and_tools": [], "safety_notes": "n"}
    client = FakeClient(body)
    t = claude_ticket(ev, site, model="test-model", client=client)
    assert client.sent["tool_choice"] == {"type": "tool", "name": "draft_ticket"}
    packet = json.loads(client.sent["messages"][0]["content"].split("<evidence>\n")[1].split("\n</evidence>")[0])
    assert packet["event"]["energy_lost_kwh"] == ev["energy_lost_kwh"]
    assert t["title"] == "Inverter trip" and t["drafted_by"] == "claude:test-model"


def test_failed_claude_draft_falls_back_to_template(demo_run):
    ev, site = _event(demo_run, "soiling")
    t = draft_ticket(ev, site, use_claude=True, client=FakeClient({"title": "only a title"}))
    assert t["drafted_by"] == "template" and "missing" in t["draft_note"]


# ----------------------------------------------------------------------------- review + pipeline

@pytest.fixture
def built(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    from solarmon import pipeline
    meta = pipeline.build(2107, demo=True, verbose=False)
    return tmp_path / "processed" / "2107", meta


def test_pipeline_writes_app_outputs(built):
    d, meta = built
    for f in ("intraday.parquet", "daily.parquet", "events.json", "tickets.json", "meta.json"):
        assert (d / f).exists(), f
    assert meta["nrmse_healthy_pct"] < 5
    assert meta["backtest"]["detected"] == meta["backtest"]["faults_injected"]
    assert len(json.loads((d / "tickets.json").read_text())) == meta["n_events"]


def test_review_log_keeps_edits_and_history(built):
    d, _ = built
    tid = review.load_tickets(d)[0]["ticket_id"]
    with pytest.raises(ValueError):
        review.record(d, tid, "rejected", "matt")  # rejection needs a reason
    review.record(d, tid, "approved", "matt", edits={"priority": "P1", "status": "hacked"})
    t = next(t for t in review.load_tickets(d) if t["ticket_id"] == tid)
    assert t["status"] == "approved" and t["priority"] == "P1" and t["reviewer"] == "matt"
    review.record(d, tid, "pending_review", "matt", "Reopened")
    t = next(t for t in review.load_tickets(d) if t["ticket_id"] == tid)
    assert t["status"] == "pending_review" and t["priority"] == "P1"  # edit survives reopen
    assert [h["status"] for h in t["history"]] == ["approved", "pending_review"]
    # Drafts on disk are never modified
    assert json.loads((d / "tickets.json").read_text())[0]["status"] == "pending_review"


@pytest.mark.parametrize("system_id", [4902, 4903, 1430, 1367])
def test_every_fleet_site_demo_is_detected_and_labelled(system_id):
    """Each site has its own climate and faults; 1430 is a single-axis tracker."""
    site = get_site(system_id)
    df, faults = make_demo(site)
    out = expected_ac_kw(df, site)
    events, _ = detect_events(out, daily_performance(out), site.system_id)
    truth = pd.DataFrame([f.__dict__ for f in faults])
    bt = backtest(events, truth)
    assert bt["correct_kind"].all(), bt
    assert false_alarms(events, truth) == []


def test_tracker_stall_ticket_uses_tracker_playbook():
    site = get_site(1430)
    df, _ = make_demo(site)
    out = expected_ac_kw(df, site)
    events, _ = detect_events(out, daily_performance(out), site.system_id)
    stall = next(e for e in events if e.kind == "tracker_stall").to_dict()
    from solarmon.pipeline import site_dict
    t = template_ticket(stall, site_dict(site))
    assert any("tracker controller" in a.lower() for a in t["recommended_actions"])
    assert stall["evidence"]["shape_gap"] < -0.12
