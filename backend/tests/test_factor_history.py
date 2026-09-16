"""Workstream 09: tests for the versioned emission-factor history
(app/services/factor_history.py), the two scripts built on it
(generate_emission_factors_snapshot.py, update_emission_factor.py), and
the read-only /factors API. Isolated from the REAL factor_history.json /
emission_factors.json via monkeypatched module-level path constants (the
same pattern already used for company-scoped storage tests) so nothing
here can corrupt the live, committed data files.
"""

from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.services import factor_history

BACKEND_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def isolated_history(tmp_path, monkeypatch):
    """A tiny, fully isolated history file with two categories: one with
    a single (current) entry, one with a superseded entry followed by a
    current one -- enough to exercise every code path without touching
    the real 27-category file."""
    history_path = tmp_path / "factor_history.json"
    data = {
        "_meta": {"scope": "test fixture"},
        "categories": {
            "widget": [
                {
                    "valid_from": "2026-01-01",
                    "valid_to": None,
                    "changelog_note": "initial widget factor",
                    "value": {"ef_kgco2e_per_kg": 1.0, "ef_source": "test"},
                }
            ],
            "gadget": [
                {
                    "valid_from": "2025-01-01",
                    "valid_to": "2026-06-01",
                    "changelog_note": "original gadget factor",
                    "value": {"ef_kgco2e_per_kg": 5.0, "ef_source": "old test source"},
                },
                {
                    "valid_from": "2026-06-01",
                    "valid_to": None,
                    "changelog_note": "gadget re-sourced from a better EPD",
                    "value": {"ef_kgco2e_per_kg": 3.0, "ef_source": "new test source"},
                },
            ],
        },
    }
    history_path.write_text(json.dumps(data, indent=2))
    monkeypatch.setattr(factor_history, "HISTORY_PATH", history_path)
    return history_path


# --- factor_history.py ---


def test_list_categories(isolated_history):
    assert factor_history.list_categories() == ["gadget", "widget"]


def test_get_history_returns_entries_oldest_first(isolated_history):
    entries = factor_history.get_history("gadget")
    assert len(entries) == 2
    assert entries[0].valid_from == "2025-01-01"
    assert entries[1].valid_from == "2026-06-01"
    assert entries[1].valid_to is None


def test_get_history_unknown_category_returns_empty_list_not_an_error(isolated_history):
    assert factor_history.get_history("not_a_real_category") == []


def test_get_factor_as_of_none_returns_currently_valid_entry(isolated_history):
    entry = factor_history.get_factor_as_of("gadget")
    assert entry.value["ef_kgco2e_per_kg"] == 3.0


def test_get_factor_as_of_past_date_returns_the_entry_valid_then(isolated_history):
    entry = factor_history.get_factor_as_of("gadget", as_of="2025-06-01")
    assert entry.value["ef_kgco2e_per_kg"] == 5.0
    # Exactly on the boundary date the new entry starts -- new entry wins (half-open interval).
    entry_on_boundary = factor_history.get_factor_as_of("gadget", as_of="2026-06-01")
    assert entry_on_boundary.value["ef_kgco2e_per_kg"] == 3.0
    # The day before the boundary -- old entry still applies.
    entry_before = factor_history.get_factor_as_of("gadget", as_of="2026-05-31")
    assert entry_before.value["ef_kgco2e_per_kg"] == 5.0


def test_get_factor_as_of_before_any_recorded_entry_returns_none(isolated_history):
    assert factor_history.get_factor_as_of("gadget", as_of="2020-01-01") is None


def test_get_factor_as_of_unknown_category_returns_none(isolated_history):
    assert factor_history.get_factor_as_of("not_a_real_category") is None


def test_generate_snapshot_uses_current_entries_and_flags_status(isolated_history):
    snap = factor_history.generate_snapshot()
    assert snap["widget"]["ef_kgco2e_per_kg"] == 1.0
    assert snap["gadget"]["ef_kgco2e_per_kg"] == 3.0  # the current one, not the superseded one
    assert "GENERATED" in snap["_status"]
    assert snap["_snapshot_as_of"] == "current"


def test_generate_snapshot_as_of_past_date_and_flags_missing_categories(isolated_history):
    # As of 2025-06-01, "widget" (valid_from 2026-01-01) doesn't exist yet.
    snap = factor_history.generate_snapshot(as_of="2025-06-01")
    assert snap["gadget"]["ef_kgco2e_per_kg"] == 5.0
    assert "widget" not in snap
    assert snap["_missing_as_of_this_date"] == ["widget"]
    assert snap["_snapshot_as_of"] == "2025-06-01"


# --- Real (non-isolated) data: the actual migration is sane and lossless ---


def test_real_history_covers_every_real_emission_factors_category():
    """Guards against the migration silently dropping a category -- every
    key app/services/emission_factors.py's real load_emission_factors()
    can return (minus the underscore-prefixed metadata keys) must have at
    least one history entry."""
    from app.services.emission_factors import load_emission_factors

    load_emission_factors.cache_clear()
    real_categories = {k for k in load_emission_factors().keys() if not k.startswith("_")}
    history_categories = set(factor_history.list_categories())
    assert real_categories <= history_categories


def test_regenerating_real_snapshot_matches_the_committed_emission_factors_json():
    """The core correctness guarantee of this workstream: the committed
    app/data/ice_db/emission_factors.json must be byte-for-byte
    reproducible from the committed factor_history.json (modulo the two
    metadata keys, which are allowed to differ -- see module docstring).
    A mismatch here means someone hand-edited emission_factors.json
    directly instead of going through update_emission_factor.py, and the
    two files have silently drifted apart.
    """
    from app.services.emission_factors import FACTORS_PATH

    committed = json.loads(FACTORS_PATH.read_text())
    regenerated = factor_history.generate_snapshot()

    committed_categories = {k: v for k, v in committed.items() if not k.startswith("_")}
    regenerated_categories = {k: v for k, v in regenerated.items() if not k.startswith("_")}
    assert committed_categories == regenerated_categories


# --- scripts/update_emission_factor.py (subprocess, fully isolated tmp copy) ---


@pytest.fixture()
def isolated_backend_copy(tmp_path):
    """update_emission_factor.py resolves its own paths from
    __file__ (same convention as every other script in this project), so
    testing it in true isolation means running it against a real copy of
    the scripts/ and app/services/ + app/data/ice_db/ tree, not just a
    monkeypatched import -- a subprocess call can't see this test
    process's monkeypatches anyway."""
    import shutil

    dest = tmp_path / "backend_copy"
    for rel in ["scripts", "app", "pytest.ini"]:
        src = BACKEND_ROOT / rel
        dst = dest / rel
        if src.is_dir():
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__"))
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(src, dst)
    return dest


def _run(args, cwd):
    return subprocess.run(
        [sys.executable, "scripts/update_emission_factor.py", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def test_update_script_records_new_value_and_closes_out_the_old_one(isolated_backend_copy):
    history_file = isolated_backend_copy / "app" / "data" / "ice_db" / "factor_history.json"
    before = json.loads(history_file.read_text())
    assert before["categories"]["aluminium"][-1]["valid_to"] is None

    result = _run(
        [
            "--category", "aluminium",
            "--value", '{"ef_kgco2e_per_kg": 20.0, "ef_source": "test update", "evidence_tier": "ifc_primary_source"}',
            "--effective-from", "2099-01-01",
            "--note", "test: re-sourced for this workstream's own test",
        ],
        cwd=isolated_backend_copy,
    )
    assert result.returncode == 0, result.stderr

    after = json.loads(history_file.read_text())
    entries = after["categories"]["aluminium"]
    assert entries[-2]["valid_to"] == "2099-01-01"  # the previously-current entry is now closed out
    assert entries[-1]["valid_from"] == "2099-01-01"
    assert entries[-1]["valid_to"] is None
    assert entries[-1]["value"]["ef_kgco2e_per_kg"] == 20.0

    # The live snapshot must have been regenerated to reflect the new value immediately.
    snapshot_file = isolated_backend_copy / "app" / "data" / "ice_db" / "emission_factors.json"
    snapshot = json.loads(snapshot_file.read_text())
    assert snapshot["aluminium"]["ef_kgco2e_per_kg"] == 20.0


def test_update_script_refuses_to_backdate_before_the_current_entry(isolated_backend_copy):
    history_file = isolated_backend_copy / "app" / "data" / "ice_db" / "factor_history.json"
    before = history_file.read_text()

    result = _run(
        ["--category", "aluminium", "--value", "{}", "--effective-from", "2000-01-01", "--note", "should be rejected"],
        cwd=isolated_backend_copy,
    )
    assert result.returncode != 0
    assert "must be strictly after" in result.stderr

    # Nothing written.
    assert history_file.read_text() == before


def test_update_script_dry_run_writes_nothing(isolated_backend_copy):
    history_file = isolated_backend_copy / "app" / "data" / "ice_db" / "factor_history.json"
    snapshot_file = isolated_backend_copy / "app" / "data" / "ice_db" / "emission_factors.json"
    before_history = history_file.read_text()
    before_snapshot = snapshot_file.read_text()

    result = _run(
        [
            "--category", "aluminium",
            "--value", '{"ef_kgco2e_per_kg": 999.0}',
            "--effective-from", "2099-01-01",
            "--note", "dry run only",
            "--dry-run",
        ],
        cwd=isolated_backend_copy,
    )
    assert result.returncode == 0, result.stderr
    assert history_file.read_text() == before_history
    assert snapshot_file.read_text() == before_snapshot


# --- /factors API ---


def test_factors_current_endpoint():
    from app.main import app

    client = TestClient(app)
    r = client.get("/factors/current")
    assert r.status_code == 200
    body = r.json()
    assert "aluminium" in body
    assert body["_snapshot_as_of"] == "current"


def test_factors_history_endpoint_known_category():
    from app.main import app

    client = TestClient(app)
    r = client.get("/factors/aluminium/history")
    assert r.status_code == 200
    body = r.json()
    assert len(body) >= 1
    assert body[0]["category"] == "aluminium"


def test_factors_history_endpoint_unknown_category_is_404():
    from app.main import app

    client = TestClient(app)
    r = client.get("/factors/not_a_real_category/history")
    assert r.status_code == 404