"""Every term the app explains must exist in the glossary, with a real definition."""

import re
from pathlib import Path

from solarmon.detect import KIND_LABELS
from solarmon.glossary import GLOSSARY, define

APP = (Path(__file__).resolve().parents[1] / "streamlit_app.py").read_text()


def test_every_define_call_in_the_app_resolves():
    terms = set(re.findall(r'define\("([^"]+)"\)', APP))
    assert terms, "expected the app to use the glossary"
    for t in terms:
        assert len(define(t)) > 40, t


def test_every_problem_type_is_defined():
    for label in KIND_LABELS.values():
        assert len(define(label)) > 20, label


def test_no_unexplained_jargon_in_definitions():
    """Definitions are for non-specialists: an acronym must be spelled out where it appears."""
    for group in GLOSSARY.values():
        for term, text in group.items():
            for acronym in re.findall(r"\b(POA|PI|nRMSE|RMSE|PVWatts|NREL)\b", text):
                spelled = {"POA": "plane-of-array", "PI": "performance index", "nRMSE": "normalised RMSE",
                           "RMSE": "normalised RMSE", "PVWatts": "physics model", "NREL": "NREL"}[acronym]
                assert spelled.lower() in text.lower(), (term, acronym)
