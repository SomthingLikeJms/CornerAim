import json
from math import asin, degrees
from random import Random

import pytest

from corneraim.camera import Camera
from corneraim.drill import Microflick, Result
from corneraim.profile import LocalStore, Profile


def test_profile_and_history_survive_reopen_and_page_in_reverse_order(tmp_path):
    store = LocalStore(tmp_path)
    assert store.load_profile() == Profile()
    assert not store.path.exists()
    saved = Profile(1600, 0.2, 20, "headline", stealth=True, focus_level=2, difficulty="easy")
    store.save_profile(saved)
    for hits in range(1, 8):
        store.record(saved.mode, 19.5, Result(hits, 8, 450), difficulty=saved.difficulty)

    reopened = LocalStore(tmp_path)
    assert reopened.load_profile() == saved
    assert reopened.load_profile().sensitivity.edpi == 320
    with reopened._connection() as db:
        legacy = json.loads(db.execute("SELECT value FROM profile WHERE id=1").fetchone()[0])
        assert "focus_level" not in legacy and "difficulty" not in legacy
    assert [row.result.hits for row in reopened.history(offset=0, limit=5)] == [7, 6, 5, 4, 3]
    older = reopened.history(offset=5, limit=5)
    assert [row.result.hits for row in older] == [2, 1]
    assert older[0].mode == "headline" and older[0].seconds == 19.5
    assert older[0].difficulty == "easy"


def test_headline_stays_on_a_narrow_height_band():
    for seed in range(10):
        drill = Microflick(0, 30, 0.028, Random(seed), mode="headline")
        drill.camera = Camera(10, 0.8)
        drill.update(drill.starts_at)
        pitch = degrees(asin(drill.target.direction[1]))
        assert -0.2 <= pitch <= 0.2
        assert drill.rules.radius == pytest.approx(0.55)


def test_old_profile_and_history_keep_their_settings_and_totals(tmp_path):
    store = LocalStore(tmp_path)
    old = dict(game_dpi=1600, game_sens=0.22, office_cpi=800, seconds=30, mode="microflick", stealth=True)
    with store._connection() as db:
        db.execute("INSERT INTO profile VALUES (1, ?)", (json.dumps(old),))
        db.execute("INSERT INTO history VALUES (1, '2026-11-01T10:00:00', 'microflick', 30, 5, 10, 420)")

    profile = store.load_profile()
    assert profile == Profile(game_dpi=1600, game_sens=0.22, stealth=True, focus_level=1)
    assert profile.sensitivity.degrees_per_count == pytest.approx(0.07 * 0.22)
    store.save_profile(profile)
    with store._connection() as db:
        assert "office_cpi" not in json.loads(db.execute("SELECT value FROM profile WHERE id=1").fetchone()[0])
    old_row = store.history(offset=0, limit=1)[0]
    assert old_row.result == Result(5, 10, 420)
    assert old_row.difficulty == "medium"

    store.record("microflick", 30, Result(4, 5, 200, (100, 180, 220, 400)))
    store.record("microflick", 30, Result(1, 4, 760, (760,)), difficulty="hard")
    store.record("reaction", 15, Result(1, 3, 170, (170,), false_starts=2, timeouts=1))
    aim = store.statistics("microflick", difficulty="medium")
    assert (aim.rounds, aim.samples, aim.hits, aim.shots, aim.hits_per_minute) == (2, 4, 9, 15, 9)
    assert (aim.median_ms, aim.p90_ms, aim.best_ms) == (200, 400, 100)
    hard = store.statistics("microflick", difficulty="hard")
    assert (hard.rounds, hard.samples, hard.median_ms) == (1, 1, 760)
    reaction = store.statistics("reaction")
    assert (reaction.samples, reaction.median_ms, reaction.false_starts, reaction.timeouts) == (1, 170, 2, 1)
