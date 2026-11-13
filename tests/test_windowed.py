import ctypes
from math import asin, atan2, degrees
from random import Random
from unittest.mock import Mock, call

import pytest

from corneraim import app
from corneraim.app import pygame
from corneraim.camera import View
from corneraim.drill import Gridshot, ReactionTest, Result
from corneraim.profile import LocalStore, Profile
from corneraim.settings import (
    _actions, _area, _difficulty_choices, _fields, _focus_choices, _modes, _stats_modes, _stealth_button, _tabs,
)
from corneraim.title import TITLE_HEIGHT, _buttons, title_surface
from corneraim.view import (
    BALL_CENTER, CLEAR_HIT_AREA, CROSSHAIR, HFOV, MIN_SIZE, OUTLINE, START_SIZE, UNLOCK_HINT, Screen,
    finish_button, retry_button, training_marker,
)


@pytest.fixture
def session(monkeypatch):
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    pygame.display.init()
    try:
        pygame.display.set_mode((START_SIZE[0], START_SIZE[1] + TITLE_HEIGHT), pygame.RESIZABLE)
        clock = Mock(return_value=100.0)
        relative_mode = Mock()
        restore_cursor = Mock()
        monkeypatch.setattr(app, "perf_counter", clock)
        monkeypatch.setattr(pygame.key, "get_focused", lambda: True)
        monkeypatch.setattr(pygame.mouse, "set_relative_mode", relative_mode)
        monkeypatch.setattr(app.win32, "cursor_position", lambda: (120, 90))
        monkeypatch.setattr(app.win32, "restore_cursor", restore_cursor)
        yield app.Demo(Profile()), clock, relative_mode, restore_cursor
    finally:
        pygame.display.quit()


def click(demo, pos=(80, 80), *, allow_capture=True):
    event = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(pos[0], pos[1] + TITLE_HEIGHT))
    demo._event(event, allow_capture=allow_capture)


def test_click_locks_and_alt_freezes_time_until_the_next_click(session):
    demo, clock, relative_mode, restore_cursor = session
    demo._event(pygame.event.Event(pygame.MOUSEMOTION, pos=(80, 80), rel=(10, 10)), allow_capture=True)
    click(demo, pos=(-1, 15))
    assert demo.drill is None

    click(demo)
    drill = demo.drill
    assert demo.captured and drill.shots == 0
    clock.return_value = 103.0
    drill.update(demo._round_time())
    target = drill.target
    demo._event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_LALT))
    assert not demo.captured
    restore_cursor.assert_called_once_with((120, 90))

    clock.return_value = 145.0
    click(demo, allow_capture=False)
    assert not demo.captured
    assert demo._round_time() == 103.0

    click(demo)
    assert demo.captured and demo.drill is drill
    assert drill.target is target and drill.shots == 0
    clock.return_value = 145.5
    assert demo._round_time() == 103.5
    click(demo, allow_capture=False)
    assert drill.shots == 1
    assert relative_mode.call_args_list == [call(True), call(False), call(True)]


@pytest.mark.parametrize("event_type", [pygame.WINDOWFOCUSLOST, pygame.WINDOWMINIMIZED])
def test_leaving_the_window_releases_without_moving_the_pointer(session, event_type):
    demo, _, relative_mode, restore_cursor = session
    click(demo)
    demo._event(pygame.event.Event(event_type))
    assert demo.drill is not None and not demo.captured
    assert relative_mode.call_args_list == [call(True), call(False)]
    restore_cursor.assert_not_called()


def test_ending_a_paused_round_uses_the_current_window_size(session, monkeypatch):
    demo, _, relative_mode, _ = session
    click(demo)
    demo._event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RALT))
    resized = (920, 540)
    monkeypatch.setattr(pygame.display, "get_window_size", lambda: (resized[0], resized[1] + TITLE_HEIGHT))
    click(demo, pos=finish_button(resized).center)
    assert demo.drill is None and demo.last_result is not None
    assert relative_mode.call_args_list == [call(True), call(False)]


def test_end_of_round_unlocks_and_blocks_a_click_burst(session, tmp_path, monkeypatch):
    demo, clock, relative_mode, restore_cursor = session
    demo.store = LocalStore(tmp_path)
    grab, cursor_visible = Mock(), Mock()
    monkeypatch.setattr(pygame.event, "set_grab", grab)
    monkeypatch.setattr(pygame.mouse, "set_visible", cursor_visible)
    retry = retry_button(START_SIZE).center
    click(demo, retry)
    clock.return_value = demo.drill.ends_at
    pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(0, 0)))
    demo._finish()
    assert not pygame.event.peek(pygame.MOUSEBUTTONDOWN, pump=False)
    grab.assert_called_once_with(False)
    cursor_visible.assert_called_once_with(True)
    restore_cursor.assert_called_once_with((120, 90))

    clock.return_value += 1.0
    click(demo, retry)
    assert demo.drill is None
    demo._body_presented()
    first_frame = clock.return_value
    for tick in range(1, 21):
        clock.return_value = first_frame + tick / 10
        click(demo, retry)
        assert demo.drill is None and demo.last_result is not None

    clock.return_value += 1.0
    click(demo, (START_SIZE[0] // 2, START_SIZE[1] // 2))
    assert demo.drill is None
    assert len(demo.store.history(offset=0, limit=5)) == 1
    assert relative_mode.call_args_list == [call(True), call(False)]

    clock.return_value += app.RESTART_CLICK_GAP + 0.01
    click(demo, retry)
    assert demo.captured and demo.drill.shots == 0


def test_stealth_result_shows_the_finished_round_after_setting_changes(session):
    demo, clock, _, _ = session
    demo.profile = Profile(mode="gridshot", difficulty="hard", stealth=True)
    click(demo)
    demo.drill.hit_times.extend((320, 480))
    demo.drill.shots = 4
    clock.return_value = demo.drill.ends_at
    demo._finish()
    demo.profile = Profile(mode="reaction", difficulty="easy", stealth=True)
    pygame.font.init()
    try:
        screen = Screen(pygame.Surface(MIN_SIZE, pygame.SRCALPHA))
        screen.label = Mock(wraps=screen.label)
        demo._draw_body(screen, clock.return_value, stealth=True)
        labels = {call.args[0]: call.args[1] for call in screen.label.call_args_list}
        assert {"本局成绩", "三球微调 · 困难", "50%", "400 ms", "鼠标已解锁"} <= labels.keys()
        assert labels["再练一局"] == retry_button(MIN_SIZE).center
        assert screen.surface.get_at((1, 1)) == CLEAR_HIT_AREA
    finally:
        pygame.font.quit()


def test_settings_editing_and_mode_selection_do_not_capture_the_mouse(session):
    demo, _, relative_mode, _ = session
    settings_rect = dict(_buttons(START_SIZE[0]))["settings"]
    click(demo, (settings_rect.centerx, settings_rect.centery - TITLE_HEIGHT))
    assert demo.settings is not None
    area = _area(START_SIZE)
    dpi_rect = next(_fields(area))[2]
    click(demo, dpi_rect.center)
    demo._event(pygame.event.Event(pygame.TEXTINPUT, text="１６００"))
    assert demo.settings.profile().sensitivity.edpi == 640

    click(demo, list(_tabs(area))[1].center)
    click(demo, dict(_modes(area))["headline"].center)
    click(demo, dict(_difficulty_choices(area))["hard"].center)
    demo._settings_action("save")
    assert demo.settings is None and demo.profile.mode == "headline"
    assert demo.profile.game_dpi == 1600
    relative_mode.assert_not_called()
    click(demo)
    assert demo.drill.difficulty == "hard"
    assert demo.drill.rules.radius == pytest.approx(0.44)


def test_stats_and_stealth_backdrop_are_accessible_from_settings(session, tmp_path):
    demo, _, relative_mode, _ = session
    demo.store = LocalStore(tmp_path)
    demo.store.record("reaction", 30, Result(2, 3, 220, (200, 240), false_starts=1))
    demo._title_click("settings")
    area = _area(START_SIZE)
    tabs = list(_tabs(area))
    click(demo, tabs[2].center)
    click(demo, dict(_stats_modes(area))["reaction"].center)
    assert demo.settings.stats.median_ms == 220
    assert demo.settings.mode == "microflick"
    click(demo, tabs[3].center)
    assert demo.settings.rows[0].mode == "reaction"
    click(demo, tabs[0].center)
    click(demo, _stealth_button(area).center)
    click(demo, list(_focus_choices(area))[2].center)
    demo._settings_action("save")
    assert demo.store.load_profile().stealth
    assert demo.store.load_profile().focus_level == 2
    relative_mode.assert_not_called()


def test_tracking_scores_without_clicks_and_persists_the_round(session, tmp_path, monkeypatch):
    demo, clock, relative_mode, _ = session
    demo.store = LocalStore(tmp_path)
    demo.profile = Profile(seconds=5, stealth=True)
    monkeypatch.setattr(pygame.display, "get_window_size", lambda: (MIN_SIZE[0], MIN_SIZE[1] + TITLE_HEIGHT))
    click(demo, (dict(_buttons(MIN_SIZE[0]))["settings"].centerx, -10))
    area = _area(MIN_SIZE)
    click(demo, list(_tabs(area))[1].center)
    click(demo, dict(_modes(area))["tracking"].center)
    click(demo, dict(_difficulty_choices(area))["easy"].center)
    click(demo, _actions(area)[1].center)
    assert demo.profile.mode == "tracking" and demo.profile.difficulty == "easy"
    relative_mode.assert_not_called()

    click(demo)
    drill = demo.drill
    drill.update(demo._round_time())
    assert not drill.targets and drill.score.points == 0
    clock.return_value = drill.starts_at
    drill.update(demo._round_time())
    x, y, z = drill.targets[0].direction
    dx = round(degrees(atan2(x, z)) / drill.degrees_per_count)
    dy = round(-degrees(asin(y)) / drill.degrees_per_count)
    demo._event(pygame.event.Event(pygame.MOUSEMOTION, rel=(dx, dy)))
    drill.update(demo._round_time())
    assert drill.on_target
    clock.return_value += 0.1
    drill.update(demo._round_time())
    assert drill.score.points == 10
    click(demo, allow_capture=False)
    assert drill.score.points == 10 and drill.result().shots == 0

    clock.return_value += 0.05
    demo._event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_LALT))
    assert not demo.captured and drill.score.points == 15
    clock.return_value += 40
    click(demo)
    clock.return_value += 0.05
    demo._event(pygame.event.Event(pygame.MOUSEMOTION, rel=(900, 0)))
    drill.update(demo._round_time())
    assert not drill.on_target and drill.score.points == 20

    clock.return_value += 6
    demo._finish()
    assert not demo.captured and demo.last_result.tracking.seconds == pytest.approx(5)
    assert demo.last_result.tracking.ratio == pytest.approx(0.04)
    assert relative_mode.call_args_list == [call(True), call(False), call(True), call(False)]
    reopened = LocalStore(tmp_path)
    [row] = reopened.history(offset=0, limit=5)
    assert row.mode == "tracking" and row.difficulty == "easy" and row.result == demo.last_result
    assert reopened.statistics("tracking", difficulty="easy").tracking == row.result.tracking
    assert reopened.statistics("tracking", difficulty="hard").rounds == 0


def test_stealth_frames_show_an_outlined_aim_crosshair_over_the_clear_body():
    pygame.font.init()
    try:
        screen = Screen(pygame.Surface(MIN_SIZE, pygame.SRCALPHA))
        screen.label = Mock(wraps=screen.label)
        drill = Gridshot(0, 30, 0.028, Random(4))
        now = drill.starts_at + 0.02
        drill.update(now)
        marker = training_marker(drill, now, stealth=True)
        assert marker == training_marker(drill, now + 0.01, stealth=True)
        assert marker != training_marker(drill, now + 0.10, stealth=True)
        drill.move(2, 0, now)
        assert marker != training_marker(drill, now, stealth=True)

        screen.training(drill, now, paused=False, notice="", stealth=True)
        assert any(call.args[0] == UNLOCK_HINT for call in screen.label.call_args_list)
        assert screen.surface.get_at((10, 10)) == CLEAR_HIT_AREA
        x, y = screen.surface.get_rect().center
        assert screen.surface.get_at((x, y)) == (*CROSSHAIR, 255)
        assert screen.surface.get_at((x + 6, y)) == (*CROSSHAIR, 255)
        assert screen.surface.get_at((x + 6, y - 1)) == (*OUTLINE, 255)
        assert screen.surface.get_at((x + 8, y)) == (*OUTLINE, 255)
        view = View(drill.camera, MIN_SIZE, HFOV)
        for target in drill.targets:
            x, y, _ = view.project(target.direction)
            assert tuple(screen.surface.get_at((round(x), round(y)))) == pytest.approx((*BALL_CENTER, 255), abs=3)
        assert screen.surface.subsurface((0, 0, MIN_SIZE[0], 33)).get_bounding_rect(min_alpha=2).width > 0
        title = title_surface(MIN_SIZE[0], screen.fonts[14], settings=False, maximized=False, hover=None, hidden=True)
        assert not title.get_bounding_rect(min_alpha=2).width

        screen.training(drill, now, paused=False, notice="")
        assert screen.surface.get_at((10, 10)).a == 255
        assert screen.surface.get_at(screen.surface.get_rect().center) == (*CROSSHAIR, 255)

        reaction = ReactionTest(0, 30, 0.028, Random(4))
        reaction.update(now)
        screen.training(reaction, now, paused=False, notice="", stealth=True)
        assert screen.surface.get_at(screen.surface.get_rect().center) == CLEAR_HIT_AREA
    finally:
        pygame.font.quit()


def test_stealth_backdrop_dims_the_aiming_zone_and_fades_outside_it():
    pygame.font.init()
    try:
        screen = Screen(pygame.Surface(MIN_SIZE, pygame.SRCALPHA))
        drill = ReactionTest(0, 30, 0.028, Random(4))
        now = drill.starts_at + 0.02
        drill.update(now)
        x, y = screen.surface.get_rect().center

        screen.training(drill, now, paused=False, notice="", stealth=True, focus_level=1)
        light = screen.surface.get_at((x, y)).a
        assert CLEAR_HIT_AREA[3] < screen.surface.get_at((x + 78, y)).a < light
        assert screen.surface.get_at((x + 105, y)) == CLEAR_HIT_AREA

        screen.training(drill, now, paused=False, notice="", stealth=True, focus_level=2)
        assert light < screen.surface.get_at((x, y)).a < 255
        screen.training(drill, now, paused=True, notice="", stealth=True, focus_level=2)
        assert screen.surface.get_at((x + 78, y)) == CLEAR_HIT_AREA
    finally:
        pygame.font.quit()


def test_rendered_ball_sizes_differ_even_at_the_minimum_window_size():
    pygame.font.init()
    try:
        screen = Screen(pygame.Surface(MIN_SIZE, pygame.SRCALPHA))
        x, y = screen.surface.get_rect().center
        diameters = []
        for difficulty in ("easy", "medium", "hard"):
            drill = ReactionTest(0, 30, 0.028, Random(4), difficulty=difficulty)
            drill.update(drill.cue_at)
            screen.training(drill, drill.cue_at, paused=False, notice="", stealth=True)
            diameters.append(sum(screen.surface.get_at((px, y)).a > 128 for px in range(x - 20, x + 21)))
        assert diameters[0] > diameters[1] > diameters[2]
    finally:
        pygame.font.quit()


def test_resizing_preserves_target_pixels_and_mouse_travel():
    pygame.font.init()
    try:
        sensitivity = Profile(game_dpi=1600, game_sens=0.22).sensitivity
        drill = Gridshot(0, 30, sensitivity.degrees_per_count, Random(6))
        now = drill.starts_at + 0.1
        drill.update(now)
        screen = Screen(pygame.Surface(MIN_SIZE, pygame.SRCALPHA))
        sizes = (MIN_SIZE, START_SIZE, (1001, 241), (361, 701))

        def center_pixels(size):
            screen.surface = pygame.Surface(size, pygame.SRCALPHA)
            screen.training(drill, now, paused=False, notice="", stealth=True)
            center = pygame.Rect(0, 0, 160, 120)
            center.center = screen.surface.get_rect().center
            return pygame.image.tobytes(screen.surface.subsurface(center), "RGBA")

        before = [center_pixels(size) for size in sizes]
        drill.move(200, -60, now)
        after = [center_pixels(size) for size in sizes]
        assert drill.camera.yaw == pytest.approx(3.08)
        assert before[0] != after[0]
        assert all(pixels == before[0] for pixels in before)
        assert all(pixels == after[0] for pixels in after)
    finally:
        pygame.font.quit()


def test_layered_paint_supplies_extent_without_changing_window_size(monkeypatch):
    win32 = app.win32
    frame = win32.LayeredFrame.__new__(win32.LayeredFrame)
    frame.handle, frame.dc = 1, 2
    frame.client_size = lambda: (640, 454)

    def update(handle, pointer):
        info = ctypes.cast(pointer, ctypes.POINTER(win32._LayerUpdate)).contents
        assert handle == 1
        assert (info.extent.contents.cx, info.extent.contents.cy) == (640, 454)
        assert info.flags == win32.ULW_ALPHA | win32.ULW_EX_NORESIZE
        return True

    monkeypatch.setattr(win32, "_update_layer", update, raising=False)
    assert frame.present((640, 454))


@pytest.mark.parametrize("composition_works", [True, False])
def test_startup_paints_before_show_or_opens_standard_window(monkeypatch, composition_works):
    calls = []
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    monkeypatch.setattr(app.win32, "set_dpi_awareness", lambda: None)
    monkeypatch.setattr(pygame.display, "get_driver", lambda: "windows")
    monkeypatch.setattr(pygame.display, "get_wm_info", lambda: {"window": 1})
    set_mode = pygame.display.set_mode

    def open_window(size, flags):
        calls.append(("open", bool(flags & pygame.HIDDEN)))
        return set_mode(size, flags)

    class Window:
        @classmethod
        def from_display_module(cls):
            return cls()

        def show(self):
            calls.append("show")
            pygame.event.post(pygame.event.Event(pygame.QUIT))

    class Frame:
        def __init__(self, *_):
            self.pixels = None

        def client_size(self):
            return pygame.display.get_window_size()

        def new_buffer(self, size):
            self.pixels = bytearray(size[0] * size[1] * 4)
            return self.pixels

        def present(self, size):
            calls.append("paint layer")
            assert self.pixels[((TITLE_HEIGHT + 30) * size[0] + 5) * 4 + 3] == 255
            if not composition_works:
                raise OSError("layer unavailable")
            return True

        def close(self):
            calls.append("close layer")

    def flip():
        calls.append("paint standard")
        pygame.event.post(pygame.event.Event(pygame.QUIT))

    monkeypatch.setattr(pygame, "Window", Window)
    monkeypatch.setattr(pygame.display, "set_mode", open_window)
    monkeypatch.setattr(pygame.display, "flip", flip)
    monkeypatch.setattr(app.win32, "LayeredFrame", Frame)
    app.Demo(Profile()).run()

    assert calls[:2] == [("open", True), "paint layer"]
    if composition_works:
        assert calls[2:] == ["show", "close layer"]
    else:
        assert calls[2:4] == ["close layer", ("open", False)]
        assert "paint standard" in calls[4:]
