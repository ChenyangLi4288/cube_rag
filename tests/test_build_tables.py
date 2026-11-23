"""Tests for the v1 data rules in scripts/build_tables.py (M2 sampling, M5 code stripping). No data files needed."""
import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_spec = importlib.util.spec_from_file_location(
    "build_tables", Path(__file__).resolve().parents[1] / "scripts" / "build_tables.py")
bt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bt)

TERMS = ["Failure to Read Input Signal", "Device Alarm System", "Alarm, Audible", "Type of Investigation not yet "
         "determined", "Results Pending Completion of Investigation", "Conclusion Not Yet Available",
         "No Findings Available", "Corroded", "Insufficient Information"]
FDA = ["1581", "1012", "1131", "3190", "3191", "2978", "2199", "4014"]


@pytest.fixture(scope="module")
def strip():
    return bt.CodeStripper(TERMS, fda_codes=FDA)


@pytest.mark.parametrize("text, gone", [
    ("OMIT: A1301 - FAILURE TO READ INPUT SIGNAL (1581), G0204002 - KEYBOARD/KEYPAD, B21 - TYPE OF INVESTIGATION "
     "NOT YET DETERMINED. A REVIEW WAS DONE.", ["A1301", "1581", "FAILURE TO READ", "B21", "G0204002"]),
    ("ADDITIONAL INFORMATION: ANNEX A: A1801, A0601. ANNEX G: G02005.", ["A1801", "A0601", "G02005"]),
    ("(B)(4). H6 MEDICAL DEVICE PROBLEM CODE - 3191 - PATIENT WAS UNABLE TO IDENTIFY THE ISSUE.", ["3191"]),
    ("PROVIDED IN SECTION H6 UNDER HEALTH EFFECT - CLINICAL CODE: 2199 WITH THIS REPORT.", ["2199"]),
    ("PT CODES: 1831, 4411. DEVICE CODES: 2460, 2917.", ["1831", "4411", "2460", "2917"]),
    ("CODE 3191 IS USED TO INDICATE SURGERY.", ["3191"]),
    ("REMOVED MEDICAL DEVICE PROBLEM CODE ¿ 3283 (RELATED)", ["3283"]),
    ("THE INITIAL REPORT (2978) IN SECTION H6 WAS INCORRECT. DEVICE CODE: [4014] - DEVICE FELL", ["2978", "4014"]),
    ("TYPE OF REPORTABLE EVENT: MALFUNCTION. THE PUMP STOPPED.", ["MALFUNCTION"]),
    ("THE ELECTRODE WAS CORRODED (1131) ON INSPECTION.", ["1131", "CORRODED"]),
])
def test_codes_removed(strip, text, gone):
    out = strip(text)
    for g in gone:
        assert g not in out.upper(), (g, out)


@pytest.mark.parametrize("text", [
    "THE PUMP DISPLAYED ERROR CODE 1260 AND ALARMED.",       # device message: signal, not a leak
    "PATIENT RECEIVED VITAMIN B12 AND D5W IN 2021.",          # short tokens outside code context
    "IMDRF ANNEX A, C, D AND G CODES ARE LISTED IN SECTION H6.",
    "THE EVENT OCCURRED IN (2021) DURING USE.",               # year in parentheses
])
def test_signal_kept(strip, text):
    assert strip(text) == text


def test_strip_codes_flags_changed_rows(strip):
    s = pd.Series(["NO CODES HERE.", None, "ANNEX A: A0601.", "ERROR CODE 1260."])
    out, changed = bt.strip_codes(s, strip)
    assert changed.tolist() == [False, False, True, False]
    assert out.iat[0] == s.iat[0] and out.iat[3] == s.iat[3]


def test_unit_hash_deterministic_uniform():
    keys = np.arange(1, 200_001, dtype=np.int64)
    u1, u2 = bt.unit_hash(keys, 7), bt.unit_hash(keys, 7)
    assert np.array_equal(u1, u2)
    assert ((u1 >= 0) & (u1 < 1)).all()
    assert abs(u1.mean() - 0.5) < 0.01
    assert abs((u1 < 0.1).mean() - 0.1) < 0.005
    assert not np.array_equal(u1, bt.unit_hash(keys, 8))


def test_sampling_rates_hit_target_and_keep_small_codes_whole():
    counts = pd.Series({"QBJ": 1_800_000, "FRN": 1_500_000, "LWS": 170_000, "NIK": 80_000, "MDS": 44_000})
    rates, _ = bt.sampling_rates(counts)
    assert rates["LWS"] == rates["NIK"] == rates["MDS"] == 1.0
    assert rates["QBJ"] == rates["FRN"] < 1
    expected = sum(counts[c] * r for c, r in rates.items())
    assert abs(expected - bt.SAMPLE_TARGET) < 10
