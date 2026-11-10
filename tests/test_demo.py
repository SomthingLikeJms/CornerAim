from itertools import combinations
from math import acos, asin, atan2, degrees
from random import Random

import pytest

from corneraim.camera import Camera, View, direction, dot
from corneraim.drill import MODES, REACTION_LIMIT, TARGET_RADIUS, Gridshot, Microflick, ReactionTest, Target, start_drill
from corneraim.sens import CM360_EDPI, Sensitivity


def test_sensitivity_matches_the_same_physical_movement():
    dpi_800 = Sensitivity(320, 800)
    dpi_1600 = Sensitivity(320, 1600)
    assert dpi_800.degrees_per_count * 800 == pytest.approx(dpi_1600.degrees_per_count * 1600)
    assert dpi_800.cm360 == pytest.approx(40.82142857)
    assert CM360_EDPI / dpi_800.cm360 == pytest.approx(dpi_800.edpi)


def test_camera_turns_the_world_behind_the_fixed_crosshair():
    camera = Camera()
    camera.move(200, -100, 0.1)
    assert camera.yaw == pytest.approx(20)
    assert camera.pitch == pytest.approx(10)
    view = View(camera, (360, 240), 40)
    assert view.project(camera.forward) == pytest.approx((180, 120, 1))
    assert view.project(direction(200, -10)) is None
    view = View(Camera(yaw=20), (360, 240), 40)
    assert view.project(direction(0, 0))[:2] == pytest.approx((0, 120))


def test_wide_resize_keeps_targets_near_the_center():
    view = View(Camera(), (3001, 241), 40, min_vfov=27)
    assert view.project(direction(0, 0))[:2] == pytest.approx((1500, 120))
    x, y, _ = view.project(direction(4.5, 1.2))
    assert 1500 < x < 1550
    assert 100 < y < 120


@pytest.mark.parametrize("pitch", [0, 45, 60, 89, -89])
def test_spawn_is_nearby_visible_and_outside_the_crosshair(pitch):
    for seed in range(40):
        drill = Microflick(0, 30, 0.028, Random(seed))
        drill.camera = Camera(355, pitch)
        drill.update(drill.starts_at)
        target = drill.target
        assert target is not None
        angle = degrees(acos(dot(drill.camera.forward, target.direction)))
        assert TARGET_RADIUS < angle <= 4.66
        tx, ty, depth = View(drill.camera, (360, 240), 40).project(target.direction)
        assert 130 < tx < 230
        assert 100 < ty < 140
        assert depth > 0
        assert -89 <= degrees(asin(target.direction[1])) <= 89


def test_a_miss_keeps_the_ball_and_a_hit_spawns_the_next_one():
    drill = Microflick(0, 30, 0.028, Random(4))
    drill.fire(0.5)
    drill.move(100, 100, 0.5)
    assert drill.result().shots == 0
    assert drill.camera == Camera()

    started = drill.starts_at
    drill.update(started)
    original = drill.target
    assert original is not None
    drill.fire(started + 0.2)
    assert drill.target is original

    x, y, z = original.direction
    dx = round(degrees(atan2(x, z)) / drill.degrees_per_count)
    dy = round(-degrees(asin(y)) / drill.degrees_per_count)
    drill.move(dx, dy, started + 0.3)
    drill.fire(started + 0.45)
    assert drill.target is not original
    result = drill.result()
    assert result.hits == 1
    assert result.shots == 2
    assert result.accuracy == pytest.approx(0.5)
    assert result.median_ms == pytest.approx(450)

    drill.fire(drill.ends_at)
    assert drill.result() == result


def test_recovery_replaces_a_far_target_without_awarding_a_hit():
    drill = Microflick(0, 30, 0.1, Random(4))
    started = drill.starts_at
    drill.update(started)
    original = drill.target
    drill.move(450, 0, started + 0.1)
    drill.update(started + 0.1)
    drill.update(started + 0.3)
    assert drill.target is original
    drill.update(started + 0.6)
    assert drill.target is not original
    assert degrees(acos(dot(drill.camera.forward, drill.target.direction))) <= 4.66
    assert drill.result().shots == drill.result().hits == 0


@pytest.mark.parametrize("mode", MODES)
def test_round_factory_scales_ball_size_and_keeps_the_seeded_layout(mode):
    drills = [start_drill(mode, 0, 30, 0.028, difficulty=level) for level in ("easy", "medium", "hard")]
    base_radius = MODES[mode].radius
    assert [drill.rules.radius for drill in drills] == pytest.approx([base_radius * 1.2, base_radius, base_radius * 0.8])

    layouts = []
    for drill in drills:
        drill.rng.seed(4)
        drill.update(drill.cue_at if isinstance(drill, ReactionTest) else drill.starts_at)
        layouts.append(tuple(target.direction for target in drill.targets))
    assert layouts[0] == layouts[1] == layouts[2]


def test_smaller_balls_also_shrink_the_hit_zone():
    for offset, expected in ((0.70, [1, 0, 0]), (0.60, [1, 1, 0])):
        hits = []
        for difficulty in ("easy", "medium", "hard"):
            drill = start_drill("microflick", 0, 30, 0.028, difficulty=difficulty)
            drill.targets = (Target(direction(offset, 0), drill.starts_at),)
            drill.fire(drill.starts_at + 0.2)
            hits.append(drill.result().hits)
        assert hits == expected


@pytest.mark.parametrize("pitch", [0, 89, -89])
def test_gridshot_replaces_only_the_hit_target_in_a_compact_field(pitch):
    drill = Gridshot(0, 30, 0.028, Random(4), difficulty="easy")
    drill.camera = Camera(355, pitch)
    start = drill.starts_at
    drill.update(start)
    original = drill.targets
    assert len(original) == 3
    for a, b in combinations(original, 2):
        gap = degrees(acos(dot(a.direction, b.direction)))
        assert 2 * drill.rules.radius < gap < 13
    drill.fire(start + 0.1)
    assert drill.targets is original
    x, y, z = original[1].direction
    drill.camera = Camera(degrees(atan2(x, z)), degrees(asin(y)))
    drill.fire(start + 0.3)
    assert drill.targets[0] is original[0] and drill.targets[2] is original[2]
    assert drill.targets[1] is not original[1]
    refill_gap = degrees(acos(dot(original[1].direction, drill.targets[1].direction)))
    assert refill_gap <= 4.5
    assert len({target.slot for target in drill.targets}) == 3
    assert drill.result().samples_ms == pytest.approx((300,))
    assert drill.result().accuracy == pytest.approx(0.5)


def test_gridshot_refills_at_the_nearest_open_slot_when_nearby_slots_are_taken():
    drill = Gridshot(0, 30, 0.028, Random(0))
    drill.field = tuple(direction(yaw, pitch) for yaw, pitch in
                        ((0, 0), (2.7, 0), (0, 2.7), (5.4, 0), (8.1, 0)))
    start = drill.starts_at
    drill.targets = tuple(Target(vector, start, slot) for slot, vector in enumerate(drill.field[:3]))

    drill.fire(start + 0.3)

    assert tuple(target.slot for target in drill.targets) == (3, 1, 2)


def test_gridshot_refill_uses_ball_centers_even_when_easy_ball_is_hit_at_the_edge():
    field = tuple(direction(yaw, pitch) for yaw, pitch in
                  ((0, 0), (2.32, 0), (-2.7, 0), (0, 2.7), (0, -2.7)))
    for difficulty, aim_yaw in (("easy", 0.93), ("medium", 0.5), ("hard", 0)):
        drill = Gridshot(0, 30, 0.028, Random(1), difficulty=difficulty)
        drill.field = field
        start = drill.starts_at
        drill.targets = tuple(Target(field[slot], start, slot) for slot in (0, 3, 4))
        drill.camera = Camera(aim_yaw, 0)

        drill.fire(start + 0.1)

        assert drill.result().hits == 1
        assert tuple(target.slot for target in drill.targets) == (1, 3, 4)


def test_reaction_starts_at_presentation_and_separates_early_and_late_clicks():
    drill = ReactionTest(0, 30, 0.028, Random(4))
    cue = drill.cue_at
    drill.update(cue - 0.01)
    assert not drill.targets
    drill.update(cue)
    drill.fire(cue + 0.01)
    assert drill.result().false_starts == 1

    cue = drill.cue_at
    drill.update(cue)
    drill.presented(cue + 0.02)
    drill.presented(cue + 0.10)
    drill.fire(cue + 0.25)
    assert drill.result().samples_ms == pytest.approx((230,))

    cue = drill.cue_at
    drill.update(cue)
    drill.presented(cue)
    drill.update(cue + REACTION_LIMIT + 0.01)
    assert drill.result().timeouts == 1 and not drill.targets

    cue = drill.cue_at
    drill.update(cue)
    drill.presented(cue)
    drill.resume(cue + 0.2)
    assert not drill.targets and drill.cue_at > cue + 0.2
    assert drill.result().samples_ms == pytest.approx((230,))
