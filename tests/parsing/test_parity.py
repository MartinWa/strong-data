import importlib.util
import os
from decimal import Decimal
from pathlib import Path

import pytest

from parsing import classify_muscle, parse_workouts

REPO_ROOT = Path(__file__).resolve().parents[2]


def load_reference_loader():
    path = REPO_ROOT / "reference" / "load_workouts.py"
    if not path.is_file():
        pytest.skip("reference/load_workouts.py is not present")
    spec = importlib.util.spec_from_file_location("reference_loader", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_opt_in_parity_with_reference_loader():
    csv_path = os.environ.get("STRONG_LOCAL_CSV")
    if not csv_path:
        pytest.skip("STRONG_LOCAL_CSV is not set")
    path = Path(csv_path)
    if not path.is_file():
        pytest.skip("STRONG_LOCAL_CSV does not point to a file")

    reference = load_reference_loader()
    old_sessions, old_exercises, old_sets = reference.load_rows(path)
    parsed = parse_workouts(path.read_text(encoding="utf-8-sig"))

    assert len(parsed.sessions) == len(old_sessions)
    assert list(parsed.exercises) == list(old_exercises)
    assert sum(session.set_count for session in parsed.sessions) == len(old_sets)

    old_by_key = dict(old_sessions)
    new_by_key = {
        (session.session_date.isoformat(), session.workout_name): session
        for session in parsed.sessions
    }
    assert set(new_by_key) == set(old_by_key)

    for key, new_session in new_by_key.items():
        old_session = old_by_key[key]
        assert new_session.set_count == old_session["set_count"]
        assert new_session.total_volume_kg == old_session["total_volume_kg"]
        assert new_session.duration_min == old_session["duration_min"]

    assert sum((session.total_volume_kg for session in parsed.sessions), Decimal(0)) == sum(
        (row[8] for row in old_sets), Decimal(0)
    )
    assert [classify_muscle(name) for name in parsed.exercises] == [
        reference.classify_muscle(name) for name in old_exercises
    ]
