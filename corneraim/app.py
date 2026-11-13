import os
import sqlite3
from pathlib import Path
from time import perf_counter

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame

from corneraim import win32
from corneraim.drill import Drill, Result, start_drill
from corneraim.profile import LocalStore, Profile
from corneraim.settings import SettingsPanel
from corneraim.title import CONTROL_STRIP, TITLE_HEIGHT, title_action, title_surface
from corneraim.view import MIN_SIZE, PANEL, START_SIZE, Screen, finish_button, retry_button, training_marker

TRAIN_FPS = 240
ICON_PATH = Path(__file__).with_name("assets") / "corneraim.ico"
RESULT_REVIEW_TIME = 0.75
RESTART_CLICK_GAP = 0.25


class Demo:
    def __init__(self, profile: Profile, store: LocalStore | None = None) -> None:
        self.profile = profile
        self.store = store
        self.settings: SettingsPanel | None = None
        self.window: pygame.Window | None = None
        self.maximized = False
        self.title_hover: str | None = None
        self.drill: Drill | None = None
        self.last_result: Result | None = None
        self.last_scenario: tuple[str, str] | None = None
        self.restart_ready_at: float | None = None
        self.paused_at: float | None = None
        self.pause_duration = 0.0
        self.saved_cursor: tuple[int, int] | None = None
        self.notice = ""
        self.running = True
        self.redraw = True

    @property
    def captured(self) -> bool:
        return self.drill is not None and self.paused_at is None

    def _round_time(self) -> float:
        # The drill uses the same clock for the countdown, targets and hit times.
        now = perf_counter() if self.paused_at is None else self.paused_at
        return now - self.pause_duration

    def _capture(self) -> None:
        if not pygame.key.get_focused():
            return
        saved_cursor = win32.cursor_position()
        try:
            pygame.mouse.set_relative_mode(True)
        except pygame.error:
            self.notice = "无法锁定鼠标，点击重试"
            self.redraw = True
            return

        now = perf_counter()
        if self.drill is None:
            self.drill = start_drill(self.profile.mode, now, self.profile.seconds,
                                     self.profile.sensitivity.degrees_per_count, difficulty=self.profile.difficulty)
            self.pause_duration = 0.0
        elif self.paused_at is not None:
            self.pause_duration += now - self.paused_at
            self.drill.resume(now - self.pause_duration)
        self.paused_at = None
        self.saved_cursor = saved_cursor
        self.notice = ""
        self.title_hover = None
        self.redraw = True
        # The activation click and any already-queued clicks were made unlocked.
        pygame.event.clear(pygame.MOUSEBUTTONDOWN, pump=False)

    def _release(self, *, restore_cursor: bool) -> None:
        saved_cursor = self.saved_cursor
        self.saved_cursor = None
        try:
            pygame.mouse.set_relative_mode(False)
        finally:
            pygame.event.set_grab(False)
            pygame.mouse.set_visible(True)
            if restore_cursor and pygame.key.get_focused():
                win32.restore_cursor(saved_cursor)

    def _pause(self, *, restore_cursor: bool) -> None:
        if not self.captured:
            return
        now = perf_counter()
        round_now = now - self.pause_duration
        if round_now >= self.drill.ends_at:
            self._finish(restore_cursor=restore_cursor)
            return
        self.drill.settle_score(round_now)
        self.paused_at = now
        self._release(restore_cursor=restore_cursor)
        self.redraw = True

    def _finish(self, *, restore_cursor: bool = True) -> None:
        drill = self.drill
        was_captured = self.captured
        now = self._round_time()
        elapsed = min(drill.duration, now - drill.starts_at)
        drill.settle_score(now)
        self.last_result = drill.result()
        self.last_scenario = drill.mode, drill.difficulty
        self.restart_ready_at = None
        self.drill = None
        self.paused_at = None
        self.notice = ""
        self.redraw = True
        if was_captured:
            self._release(restore_cursor=restore_cursor)
        pygame.event.clear(pygame.MOUSEBUTTONDOWN, pump=False)
        if elapsed > 0 and self.store is not None:
            try:
                self.store.record(drill.mode, elapsed, self.last_result, difficulty=drill.difficulty)
            except (OSError, sqlite3.Error):
                self.notice = "本局成绩保存失败"

    def _settings_action(self, action: str | None) -> None:
        if action == "save":
            try:
                updated = self.settings.profile()
                if self.store is not None:
                    self.store.save_profile(updated)
            except ValueError as error:
                self.settings.notice = str(error).rstrip("。")
                return
            except (OSError, sqlite3.Error):
                self.settings.notice = "本机设置保存失败，请重试"
                return
            self.profile = updated
            self.notice = ""
        if action in ("save", "close"):
            pygame.key.stop_text_input()
            self.settings = None

    def _title_click(self, action: str | None) -> None:
        if action == "settings":
            if self.settings is None:
                self.settings = SettingsPanel(self.profile, self.store)
            else:
                self._settings_action("close")
        elif action == "minimize":
            self.window.minimize()
        elif action == "maximize":
            if self.maximized:
                self.window.restore()
            else:
                self.window.maximize()
        elif action == "close":
            self.running = False
        self.redraw = True

    def _unlocked_click(self, pos: tuple[int, int]) -> None:
        w, h = pygame.display.get_window_size()
        if pos[1] < TITLE_HEIGHT:
            self._title_click(title_action(w, pos))
            return
        size = w, h - TITLE_HEIGHT
        body_pos = pos[0], pos[1] - TITLE_HEIGHT
        if not pygame.Rect((0, 0), size).collidepoint(body_pos):
            return
        if self.settings is not None:
            self._settings_action(self.settings.click(body_pos, size))
            self.redraw = True
            return
        if self.drill is not None and finish_button(size).collidepoint(body_pos):
            self._finish()
            return
        if self.drill is None and self.last_result is not None:
            if self.restart_ready_at is None:
                return
            now = perf_counter()
            if now < self.restart_ready_at or not retry_button(size).collidepoint(body_pos):
                # A burst must stop before any new click can restart the drill.
                self.restart_ready_at = max(self.restart_ready_at, now + RESTART_CLICK_GAP)
                return
        self._capture()

    def _event(self, event: pygame.event.Event, *, allow_capture: bool = False) -> None:
        if event.type in (pygame.QUIT, pygame.WINDOWCLOSE):
            self.running = False
        elif event.type in (pygame.WINDOWFOCUSLOST, pygame.WINDOWMINIMIZED, pygame.WINDOWHIDDEN):
            self._pause(restore_cursor=False)
        elif event.type == pygame.WINDOWMAXIMIZED:
            self.maximized = True
            self.redraw = True
        elif event.type == pygame.WINDOWRESTORED:
            self.maximized = False
            self.redraw = True
        elif event.type in (pygame.WINDOWEXPOSED, pygame.WINDOWSHOWN,
                            pygame.WINDOWSIZECHANGED, pygame.WINDOWRESIZED):
            self.redraw = True
        elif event.type == pygame.KEYDOWN and event.key in (pygame.K_LALT, pygame.K_RALT):
            self._pause(restore_cursor=True)
        elif event.type in (pygame.KEYDOWN, pygame.TEXTINPUT) and self.settings is not None:
            self._settings_action(self.settings.keyboard(event))
            self.redraw = True
        elif event.type == pygame.MOUSEMOTION and self.captured:
            self.drill.move(*event.rel, self._round_time())
        elif event.type in (pygame.MOUSEMOTION, pygame.WINDOWLEAVE):
            hover = title_action(pygame.display.get_window_size()[0], event.pos) if (
                event.type == pygame.MOUSEMOTION
            ) else None
            if hover != self.title_hover:
                self.title_hover = hover
                self.redraw = True
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.captured:
                self.drill.fire(self._round_time())
            elif allow_capture:
                self._unlocked_click(event.pos)

    def _draw_body(self, screen: Screen, now: float, *, stealth: bool) -> None:
        if self.settings is not None:
            self.settings.draw(screen)
        elif self.drill is None:
            mode, difficulty = self.last_scenario or (self.profile.mode, self.profile.difficulty)
            screen.idle(self.last_result, self.profile.sensitivity, self.profile.seconds,
                        self.notice, mode, stealth=stealth, difficulty=difficulty)
        else:
            screen.training(self.drill, now, paused=not self.captured, notice=self.notice,
                            stealth=stealth, focus_level=self.profile.focus_level)

    def _body_presented(self) -> None:
        if self.captured:
            self.drill.presented(self._round_time())
        elif (self.drill is None and self.settings is None and self.last_result is not None
              and self.restart_ready_at is None):
            self.restart_ready_at = perf_counter() + RESULT_REVIEW_TIME

    def _run_window(self, layered: bool) -> None:
        pygame.display.set_caption("CornerAim · 微调训练")
        if ICON_PATH.is_file():
            pygame.display.set_icon(pygame.image.load(ICON_PATH))
        size = START_SIZE[0], START_SIZE[1] + TITLE_HEIGHT
        flags = pygame.RESIZABLE | (pygame.NOFRAME | pygame.HIDDEN if layered else 0)
        pygame.display.set_mode(size, flags)
        self.window = pygame.Window.from_display_module()
        self.window.minimum_size = MIN_SIZE[0], MIN_SIZE[1] + TITLE_HEIGHT
        frame = None
        try:
            if layered:
                handle = pygame.display.get_wm_info()["window"]
                frame = win32.LayeredFrame(handle, TITLE_HEIGHT, CONTROL_STRIP, lambda: self.captured)
            canvas = None
            screen = Screen(pygame.Surface(START_SIZE))
            caption_key = caption = None

            def paint(now: float, *, stealth: bool) -> bool:
                nonlocal canvas, caption, caption_key
                size = frame.client_size() if frame is not None else pygame.display.get_window_size()
                w, h = size
                if w <= 0 or h <= TITLE_HEIGHT:
                    return False
                if canvas is None or canvas.get_size() != size:
                    if frame is not None:
                        canvas = pygame.image.frombuffer(frame.new_buffer(size), size, "BGRA")
                    else:
                        canvas = pygame.Surface(size, pygame.SRCALPHA)
                    screen.surface = canvas.subsurface((0, TITLE_HEIGHT, w, h - TITLE_HEIGHT))
                hide_caption = stealth and self.captured
                key = w, self.settings is not None, self.maximized, self.title_hover, stealth, hide_caption
                if caption_key != key:
                    caption = title_surface(w, screen.fonts[14], settings=self.settings is not None,
                                            maximized=self.maximized, hover=self.title_hover,
                                            text_only=stealth, hidden=hide_caption)
                    caption_key = key
                canvas.fill((0, 0, 0, 0) if frame else PANEL, (0, 0, w, TITLE_HEIGHT))
                canvas.blit(caption, (0, 0), special_flags=pygame.BLEND_PREMULTIPLIED)
                self._draw_body(screen, now, stealth=stealth)
                if frame is not None:
                    return frame.present(size)
                pygame.display.get_surface().blit(canvas, (0, 0))
                pygame.display.flip()
                return True

            if frame is not None:
                if not paint(self._round_time(), stealth=self.profile.stealth):
                    raise OSError("无法绘制透明窗口首帧")
                self.window.show()
                self.redraw = False

            clock = pygame.time.Clock()
            drawn_marker = None
            while self.running:
                if self.captured:
                    events = pygame.event.get()
                    if not pygame.key.get_focused():
                        self._pause(restore_cursor=False)
                    # An Alt or focus event may release capture partway through
                    # this batch. Its other clicks cannot start another capture.
                    for event in events:
                        self._event(event)
                        if not self.running:
                            break
                elif not self.redraw:
                    self._event(pygame.event.wait(250), allow_capture=True)
                if not self.running:
                    break

                now = self._round_time()
                if self.captured and now >= self.drill.ends_at:
                    self._finish()
                stealth = frame is not None and self.profile.stealth and self.settings is None
                marker = None
                if self.captured:
                    self.drill.update(now)
                    marker = training_marker(self.drill, now, stealth=stealth)
                if self.redraw or (marker is not None and marker != drawn_marker):
                    if pygame.display.get_active():
                        self.redraw = not paint(now, stealth=stealth)
                        if not self.redraw:
                            drawn_marker = marker
                            self._body_presented()
                    else:
                        self.redraw = False
                if self.captured:
                    clock.tick(TRAIN_FPS)
        finally:
            if frame is not None:
                frame.close()

    def run(self) -> None:
        win32.set_dpi_awareness()
        os.environ["SDL_MOUSE_RELATIVE_MODE_WARP"] = "0"
        os.environ["SDL_MOUSE_RELATIVE_SYSTEM_SCALE"] = "0"
        os.environ["SDL_MOUSE_RELATIVE_SPEED_SCALE"] = "1"
        os.environ["SDL_MOUSE_FOCUS_CLICKTHROUGH"] = "1"
        os.environ["SDL_BORDERLESS_WINDOWED_STYLE"] = "1"
        os.environ["SDL_BORDERLESS_RESIZABLE_STYLE"] = "1"
        pygame.display.init()
        pygame.font.init()
        try:
            layered = pygame.display.get_driver() == "windows"
            try:
                self._run_window(layered)
            except (OSError, pygame.error):
                if not layered:
                    raise
                self._pause(restore_cursor=False)
                self.window = None
                pygame.display.quit()
                pygame.display.init()
                self.notice = "已切换到普通窗口显示"
                self.redraw = True
                self.maximized = False
                self._run_window(False)
        finally:
            try:
                if self.captured:
                    self._release(restore_cursor=False)
            finally:
                pygame.quit()
