import sqlite3
from unicodedata import normalize

import pygame

from corneraim.drill import DEFAULT_DIFFICULTY, DIFFICULTIES, MODES
from corneraim.profile import HistoryRow, LocalStore, PersonalStats, Profile
from corneraim.view import (
    ACCENT, ACTIVE_EDGE, ACTIVE_FILL, BACKGROUND, BALL, CARD, CONTROL_EDGE,
    EDGE, MUTED, PANEL, SECONDARY, TEXT, Screen,
)

FIELDS = (
    ("game_dpi", "游戏鼠标 DPI"),
    ("game_sens", "游戏内灵敏度"),
    ("seconds", "每局秒数"),
)
TABS = ("参数", "模式", "统计", "历史")
FOCUS_LABELS = ("纯透", "浅底", "深底")
PAGE_SIZE = 5


def _area(size: tuple[int, int]) -> pygame.Rect:
    w, h = size
    left = max(14, (w - 552) // 2)
    return pygame.Rect(left, (h - 224) // 2, w - left * 2, 224)


def _choices(area: pygame.Rect, offset: int, height: int, count: int):
    available = area.w - 6 * (count - 1)
    for index in range(count):
        start = available * index // count
        end = available * (index + 1) // count
        yield pygame.Rect(area.x + start + index * 6, area.y + offset, end - start, height)


def _tabs(area: pygame.Rect):
    return _choices(area, 0, 30, len(TABS))


def _fields(area: pygame.Rect):
    width = (area.w - 12) // 2
    for index, (key, name) in enumerate(FIELDS):
        row, column = divmod(index, 2)
        yield key, name, pygame.Rect(area.x + column * (width + 12), area.y + 64 + row * 52, width, 28)


def _modes(area: pygame.Rect):
    width = (area.w - 10) // 2
    for index, key in enumerate(MODES):
        row, column = divmod(index, 2)
        yield key, pygame.Rect(area.x + column * (width + 10), area.y + 35 + row * 40, width, 36)


def _difficulty_choices(area: pygame.Rect):
    choices = pygame.Rect(area.x + 66, area.y, area.w - 66, area.h)
    return zip(DIFFICULTIES, _choices(choices, 153, 25, len(DIFFICULTIES)))


def _stealth_button(area: pygame.Rect) -> pygame.Rect:
    width = (area.w - 12) // 2
    return pygame.Rect(area.x + width + 12, area.y + 116, width, 28)


def _focus_choices(area: pygame.Rect):
    return _choices(_stealth_button(area), 35, 27, len(FOCUS_LABELS))


def _stats_modes(area: pygame.Rect):
    return zip(MODES, _choices(area, 42, 26, len(MODES)))


def _actions(area: pygame.Rect):
    y = area.bottom - 27
    return (
        pygame.Rect(area.right - 62, y, 62, 27),
        pygame.Rect(area.right - 132, y, 62, 27),
        pygame.Rect(area.left, y, 64, 27),
        pygame.Rect(area.left + 72, y, 64, 27),
    )


def _button(screen: Screen, rect: pygame.Rect, label: str, *, active: bool = False,
            disabled: bool = False) -> None:
    pygame.draw.rect(screen.surface, ACTIVE_FILL if active else CARD, rect, border_radius=6)
    pygame.draw.rect(screen.surface, ACTIVE_EDGE if active else CONTROL_EDGE, rect, 1, border_radius=6)
    color = MUTED if disabled else ACCENT if active else SECONDARY
    screen.label(label, rect.center, 14, color, "center")


def _milliseconds(value: float | None) -> str:
    return f"{value:.0f} ms" if value is not None else "—"


class SettingsPanel:
    def __init__(self, profile: Profile, store: LocalStore | None) -> None:
        self.store = store
        self.values = {key: str(getattr(profile, key)) for key, _ in FIELDS}
        self.mode = profile.mode
        self.difficulty = profile.difficulty
        self.stealth = profile.stealth
        self.focus_level = profile.focus_level
        self.tab = 0
        self.field: str | None = None
        self.selected = False
        self.notice = ""
        self.page = 0
        self.rows: list[HistoryRow] = []
        self.stats_mode = profile.mode
        self.stats = PersonalStats()

    def profile(self) -> Profile:
        try:
            game_dpi = float(self.values["game_dpi"])
            game_sens = float(self.values["game_sens"])
        except ValueError as error:
            raise ValueError("DPI 和灵敏度请填写有效数字") from error
        try:
            seconds = int(self.values["seconds"])
        except ValueError as error:
            raise ValueError("局长须为 5 到 300 的整数") from error
        return Profile(game_dpi, game_sens, seconds, self.mode,
                       stealth=self.stealth, focus_level=self.focus_level, difficulty=self.difficulty)

    def _focus(self, field: str | None) -> None:
        self.field = field
        self.selected = field is not None
        if field is None:
            pygame.key.stop_text_input()
        else:
            pygame.key.start_text_input()

    def _load_history(self, page: int) -> None:
        try:
            self.rows = self.store.history(offset=page * PAGE_SIZE, limit=PAGE_SIZE + 1) if self.store else []
            self.page = page
        except (OSError, sqlite3.Error, ValueError, KeyError, TypeError):
            self.notice = "本机历史读取失败"

    def _load_stats(self, mode: str) -> None:
        self.stats_mode = mode
        try:
            self.stats = self.store.statistics(mode, difficulty=self.difficulty) if self.store else PersonalStats()
        except (OSError, sqlite3.Error, ValueError, KeyError, TypeError):
            self.stats = PersonalStats()
            self.notice = "本机统计读取失败"

    def click(self, pos: tuple[int, int], size: tuple[int, int]) -> str | None:
        area = _area(size)
        back, save, prev, next_page = _actions(area)
        self.notice = ""
        self._focus(None)
        for index, rect in enumerate(_tabs(area)):
            if rect.collidepoint(pos):
                self.tab = index
                if index == 2:
                    self._load_stats(self.stats_mode)
                elif index == 3:
                    self._load_history(0)
                return None
        if back.collidepoint(pos):
            return "close"
        if self.tab == 3:
            if prev.collidepoint(pos) and self.page:
                self._load_history(self.page - 1)
            elif next_page.collidepoint(pos) and len(self.rows) > PAGE_SIZE:
                self._load_history(self.page + 1)
        elif self.tab == 2:
            for key, rect in _stats_modes(area):
                if rect.collidepoint(pos):
                    self._load_stats(key)
                    break
        elif save.collidepoint(pos):
            return "save"
        elif self.tab == 1:
            for key, rect in _modes(area):
                if rect.collidepoint(pos):
                    self.mode = key
                    return None
            for key, rect in _difficulty_choices(area):
                if rect.collidepoint(pos):
                    self.difficulty = key
                    break
        elif _stealth_button(area).collidepoint(pos):
            self.stealth = not self.stealth
        else:
            for key, _, rect in _fields(area):
                if rect.collidepoint(pos):
                    self._focus(key)
                    return None
            if self.stealth:
                for level, rect in enumerate(_focus_choices(area)):
                    if rect.collidepoint(pos):
                        self.focus_level = level
                        break
        return None

    def keyboard(self, event: pygame.event.Event) -> str | None:
        if self.field is None:
            return None
        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                return "save"
            if event.key == pygame.K_a and event.mod & pygame.KMOD_CTRL:
                self.selected = True
            elif event.key in (pygame.K_BACKSPACE, pygame.K_DELETE):
                self.values[self.field] = "" if self.selected else self.values[self.field][:-1]
                self.selected = False
                self.notice = ""
        elif event.type == pygame.TEXTINPUT:
            text = "".join(char for char in normalize("NFKC", event.text) if char in "0123456789.eE+-")
            if text:
                value = "" if self.selected else self.values[self.field]
                self.values[self.field] = (value + text)[:20]
                self.selected = False
                self.notice = ""
        return None

    def _draw_fields(self, screen: Screen, area: pygame.Rect) -> None:
        clip = screen.surface.get_clip()
        for key, name, rect in _fields(area):
            active = self.field == key
            screen.label(name, (rect.x, rect.y - 21), 14, SECONDARY)
            pygame.draw.rect(screen.surface, ACTIVE_FILL if active and self.selected else CARD,
                             rect, border_radius=6)
            pygame.draw.rect(screen.surface, ACCENT if active else CONTROL_EDGE, rect, 1, border_radius=6)
            value = self.values[key]
            screen.surface.set_clip(rect.inflate(-4, -4))
            screen.label(value or "填写数值", (rect.x + 9, rect.centery), 17 if value else 14,
                         TEXT if value else MUTED, "midleft", figures=bool(value))
            screen.surface.set_clip(clip)
        stealth = _stealth_button(area)
        screen.label("显示方式", (stealth.x, stealth.y - 21), 14, SECONDARY)
        _button(screen, stealth, "摸鱼模式  开" if self.stealth else "摸鱼模式  关", active=self.stealth)
        if self.stealth:
            for level, (label, rect) in enumerate(zip(FOCUS_LABELS, _focus_choices(area))):
                _button(screen, rect, label, active=level == self.focus_level)
        if self.notice:
            return
        try:
            sensitivity = self.profile().sensitivity
        except ValueError:
            return
        screen.label("eDPI", (area.x, area.y + 157), 14, MUTED, "midleft")
        screen.label(f"{sensitivity.edpi:.5g}", (area.x + 38, area.y + 157), 17, ACCENT, "midleft", figures=True)
        screen.label(f"{sensitivity.cm360:.4g} cm/360", (area.x, area.y + 167), 15, SECONDARY, figures=True)

    def _draw_modes(self, screen: Screen, area: pygame.Rect) -> None:
        for key, rect in _modes(area):
            mode = MODES[key]
            selected = key == self.mode
            pygame.draw.rect(screen.surface, ACTIVE_FILL if selected else CARD, rect, border_radius=7)
            pygame.draw.rect(screen.surface, ACTIVE_EDGE if selected else CONTROL_EDGE, rect, 1, border_radius=7)
            if selected:
                pygame.draw.line(screen.surface, ACCENT, (rect.x + 3, rect.y + 10), (rect.x + 3, rect.bottom - 11), 2)
            screen.label(mode.name, (rect.x + 11, rect.y + 1), 15, ACCENT if selected else TEXT)
            screen.label(mode.description, (rect.x + 11, rect.y + 19), 12, SECONDARY)
        screen.label("靶球难度", (area.x, area.y + 165), 13, MUTED, "midleft")
        for key, rect in _difficulty_choices(area):
            _button(screen, rect, DIFFICULTIES[key].name, active=key == self.difficulty)
        if not self.notice:
            hint = "保存后用于下一局 · 困难档会变速" if self.mode == "tracking" else "保存后用于下一局"
            screen.label(hint, (area.x, area.y + 180), 12, MUTED)

    def _draw_stats(self, screen: Screen, area: pygame.Rect) -> None:
        for mode, rect in _stats_modes(area):
            _button(screen, rect, MODES[mode].short, active=mode == self.stats_mode)
        stats = self.stats
        if self.stats_mode == "tracking":
            tracking = stats.tracking
            cards = (
                ("训练局数", str(stats.rounds)),
                ("累计贴靶", f"{tracking.on_target_seconds:.1f} s" if tracking else "—"),
                ("贴靶率", f"{tracking.ratio:.1%}" if tracking and tracking.seconds else "—"),
            )
            hint = "贴靶时间占实际练习时间的比例"
        elif self.stats_mode == "reaction":
            cards = (
                ("有效样本", str(stats.samples)),
                ("中位反应", _milliseconds(stats.median_ms)),
                ("反应 P90", _milliseconds(stats.p90_ms)),
                ("最快反应", _milliseconds(stats.best_ms)),
                ("抢跑", str(stats.false_starts)),
                ("超时", str(stats.timeouts)),
            )
            hint = "亮球到点击 · P90 为 90% 样本用时上限"
        else:
            accuracy = f"{stats.hits / stats.shots:.1%}" if stats.shots else "—"
            pace = f"{stats.hits_per_minute:.1f}" if stats.seconds else "—"
            timing = MODES[self.stats_mode].timing
            cards = (
                ("训练局数", str(stats.rounds)),
                ("命中率", accuracy),
                ("每分钟命中", pace),
                (f"中位{timing}", _milliseconds(stats.median_ms)),
                (f"{timing} P90", _milliseconds(stats.p90_ms)),
                ("最快耗时", _milliseconds(stats.best_ms)),
            )
            hint = f"{stats.samples} 个耗时样本 · P90 为 90% 样本用时上限"
        width = (area.w - 16) // 3
        for index, (label, value) in enumerate(cards):
            row, column = divmod(index, 3)
            rect = pygame.Rect(area.x + column * (width + 8), area.y + 77 + row * 49, width, 43)
            pygame.draw.rect(screen.surface, CARD, rect, border_radius=6)
            pygame.draw.rect(screen.surface, EDGE, rect, 1, border_radius=6)
            screen.label(label, (rect.x + 8, rect.y + 2), 13, SECONDARY)
            size = 22 if screen.figures[22].size(value)[0] <= rect.w - 16 else 17
            screen.label(value, (rect.x + 8, rect.y + 30), size, ACCENT if value != "—" else MUTED,
                         "midleft", figures=True)
        if not self.notice:
            level = DIFFICULTIES[self.difficulty].name
            screen.label(f"{level} · {hint}", (area.x, area.y + 175), 12, MUTED)

    def _draw_history(self, screen: Screen, area: pygame.Rect) -> None:
        if not self.rows:
            screen.label("完成一局后，成绩会出现在这里。", (area.centerx, area.y + 95), 13, MUTED, "center")
            return
        columns = [area.x + round(area.w * part) for part in (0, 0.30, 0.43, 0.55, 0.70, 0.84)]
        for x, label in zip(columns, ("日期", "模式", "难度", "成绩", "比率", "用时")):
            screen.label(label, (x, area.y + 42), 13, SECONDARY)
        pygame.draw.line(screen.surface, CONTROL_EDGE, (area.x, area.y + 61), (area.right - 1, area.y + 61))
        for index, row in enumerate(self.rows[:PAGE_SIZE]):
            y = area.y + 73 + 21 * index
            result = row.result
            mode = MODES.get(row.mode)
            difficulty = DIFFICULTIES.get(row.difficulty, DIFFICULTIES[DEFAULT_DIFFICULTY])
            if result.tracking is not None:
                tracking = result.tracking
                scores = (str(tracking.points), f"{tracking.ratio:.0%}", f"{tracking.on_target_seconds:.1f} s")
            else:
                accuracy = f"{result.accuracy:.0%}" if row.mode != "reaction" and result.shots else "—"
                scores = (str(result.hits), accuracy, _milliseconds(result.median_ms))
            cells = (
                row.played_at[2:16].replace("T", " "),
                mode.short if mode else "未知",
                difficulty.name,
                *scores,
            )
            for column, (x, value) in enumerate(zip(columns, cells)):
                numeric = column not in (1, 2)
                screen.label(value, (x, y), 15 if numeric else 13, TEXT, "midleft", figures=numeric)
            pygame.draw.line(screen.surface, EDGE, (area.x, y + 10), (area.right - 1, y + 10))

    def draw(self, screen: Screen) -> None:
        screen.surface.fill(PANEL)
        area = _area(screen.surface.get_size())
        rail = pygame.Rect(area.x, area.y, area.w, 30)
        pygame.draw.rect(screen.surface, BACKGROUND, rail, border_radius=7)
        pygame.draw.rect(screen.surface, EDGE, rail, 1, border_radius=7)
        for index, (rect, label) in enumerate(zip(_tabs(area), TABS)):
            selected = index == self.tab
            if selected:
                pill = rect.inflate(-4, -4)
                pygame.draw.rect(screen.surface, ACTIVE_FILL, pill, border_radius=5)
                pygame.draw.rect(screen.surface, ACTIVE_EDGE, pill, 1, border_radius=5)
            screen.label(label, rect.center, 15, ACCENT if selected else SECONDARY, "center")
        back, save, prev, next_page = _actions(area)
        _button(screen, back, "返回")
        if self.tab == 3:
            self._draw_history(screen, area)
            _button(screen, prev, "上一页", disabled=self.page == 0)
            _button(screen, next_page, "下一页", disabled=len(self.rows) <= PAGE_SIZE)
            screen.label(f"第 {self.page + 1} 页", (next_page.right + 10, next_page.centery), 12, MUTED, "midleft")
        elif self.tab == 2:
            self._draw_stats(screen, area)
        else:
            if self.tab == 0:
                self._draw_fields(screen, area)
            else:
                self._draw_modes(screen, area)
            _button(screen, save, "保存", active=True)
        if self.notice:
            notice_y = 180 if self.tab == 1 else 176
            screen.label(self.notice, (area.x, area.y + notice_y), 12, BALL)
