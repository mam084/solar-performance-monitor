"""Plain-language definitions for every term the app shows.

One source for the app's tooltips and its Help & glossary tab, so the wording can't
drift apart. Keys are the term as it appears on screen.
"""

from __future__ import annotations

GLOSSARY: dict[str, dict[str, str]] = {
    "Measurements": {
        "Sunlight on the panels": (
            "How much sunlight reaches the panels, measured by a sensor tilted the same way they are, in "
            "watts per square metre (W/m²). About 1,000 W/m² is full midday sun. Engineers call this "
            "plane-of-array (POA) irradiance."),
        "kW and kWh": (
            "kW (kilowatts) is power at a moment, like a car's speed. kWh (kilowatt-hours) is energy over "
            "time, like distance driven. 1 MWh = 1,000 kWh. A typical US home uses about 10,000 kWh a year."),
        "Size (kW DC)": (
            "The panels' combined rating under standard test conditions. Real output is lower: heat, wiring "
            "and conversion losses take their share."),
        "Inverter limit (kW AC)": (
            "The most power the inverters (which turn the panels' DC into grid AC) can deliver. On very sunny "
            "days output flattens at this limit. That's by design ('clipping'), not a fault."),
    },
    "The model": {
        "Expected output": (
            "What the site should have produced given the sunlight and temperature its own sensors measured. "
            "It comes from NREL's PVWatts physics model, calibrated to this site on a known-good year, plus a "
            "correction for the site's normal daily pattern and, where it proved better, a machine-learning layer."),
        "Performance (actual ÷ expected)": (
            "Energy the site produced divided by expected output, per day. 1.00 means right on target; 0.90 "
            "means 10% short; above 1.00 usually means the sunlight sensor is reading low. Because expected "
            "output uses the day's measured sunlight, clouds don't lower it. In the code this is the "
            "performance index (PI)."),
        "Normal level": (
            "What performance usually looks like for this site lately: the median of the previous 90 days, "
            "leaving out days already flagged as problems. Days are judged against this, so slow ageing of "
            "the panels doesn't set off alarms. Called the baseline in the code."),
        "Alert line": (
            "How far below its normal level a day must fall to count as a problem. It's set from how much "
            "this site normally varies day to day, so a naturally noisy site doesn't raise constant false alarms."),
        "Prediction accuracy": (
            "How closely expected output matches actual output, on clear days when the site was at its best: "
            "the typical 15-minute gap as a share of average output. Under 5% is the target. Engineers call "
            "this normalised RMSE (nRMSE)."),
        "Full-health day": (
            "A clear day on which the site performed at its own best recent level. Used to measure the model "
            "without counting the plant's own problems as model error."),
        "Everyday shortfall": (
            "On days with no detected problem, how far output still fell below the site's best clear-day "
            "level, added up over the year. It captures losses too small or scattered to alert on, such as a "
            "string or inverter dropping out now and then. Measurement noise alone gives a healthy site about "
            "2–3%, so only the excess is real loss."),
        "Machine-learning layer": (
            "A gradient-boosted model that learns patterns the physics misses, from sunlight, temperature and "
            "the sun's position. It's switched on for a site only if it predicted the most recent quarter of "
            "the data (which it never saw while learning) better than physics alone."),
    },
    "Problems": {
        "Problem (event)": (
            "A run of days on which the site produced less than its alert line allows, or its data looked "
            "wrong. Each gets a type, a severity and a draft maintenance ticket."),
        "Full outage": "The site produced nothing (or almost nothing) despite sunlight.",
        "Partial outage": (
            "Output stepped down suddenly and stayed down: part of the array (an inverter, a string or a "
            "fuse) went offline."),
        "Soiling / gradual loss": (
            "A slow slide over weeks, typically dust or pollen on the panels, often reset by rain or cleaning."),
        "Curtailment / output cap": (
            "Normal in the morning and evening but capped at midday: an export limit or a power setting, not "
            "lost capacity."),
        "Tracker stall": (
            "On sun-tracking sites: fine at midday but short in the morning and evening, because rows "
            "stopped turning to follow the sun."),
        "Snow cover": (
            "Output collapsed but didn't switch off, right after freezing weather: snow on the panels. "
            "Usually clears on its own."),
        "Irradiance sensor fault": (
            "The sunlight sensor stopped reporting, or reads low (output above what it says is possible). "
            "Performance numbers aren't reliable until it's fixed."),
        "Monitoring data gap": "No power readings during daylight, so output is unknown for that stretch.",
        "Ongoing": (
            "The problem was still happening on the last day of data. For sites whose public data ended "
            "years ago, that means 'ongoing when the data ends', not today."),
        "Severity": (
            "How urgent the problem is: critical, high, medium or low, from its type, how much output it "
            "costs and whether it's ongoing."),
        "Energy lost and cost": (
            "The gap between expected and actual energy over the problem's days. Cost assumes $0.12 per kWh. "
            "Sensor faults and data gaps show no loss, because the true output is unknown."),
    },
    "Tickets": {
        "Ticket": (
            "A draft work order written from a problem's evidence: what happened, likely causes, and steps "
            "for a technician. A person must approve it before anyone is sent."),
        "Priority": "P1 (act today) to P4 (when convenient). Follows severity: critical = P1, high = P2, and so on.",
        "Awaiting review": "A recent or ongoing problem's ticket, waiting for someone to approve, edit or reject it.",
        "History": (
            "Problems that ended more than 45 days before the site's latest data. Kept for the record and "
            "reopenable, but not queued for action."),
        "Approved / rejected": (
            "A reviewer's decision, saved with their name, the time, any edits and (for rejections) the reason."),
    },
    "Data": {
        "Where the data comes from": (
            "Measured data from NREL's public PVDAQ archive (CC BY 4.0), checked for new files every morning "
            "by a scheduled job. Some sites' public records ended years ago; their numbers describe that period."),
    },
}


def define(term: str) -> str:
    """The definition of a term, for tooltips. Raises KeyError for unknown terms, so a
    typo in the app fails a test rather than showing an empty tooltip."""
    for group in GLOSSARY.values():
        if term in group:
            return group[term]
    raise KeyError(term)
