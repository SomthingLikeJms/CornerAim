import os
from functools import lru_cache
from math import atan, ceil, cos, degrees, hypot, radians, sin, tan
from pathlib import Path

import pygame

from corneraim.camera import View, direction
from corneraim.drill import DEFAULT_DIFFICULTY, DIFFICULTIES, HIT_FLASH, MODES, Drill, Result, Tracking
from corneraim.sens import Sensitivity

START_SIZE = (640, 420)
PROJECTION_SIZE = (360, 240)
MIN_SIZE = PROJECTION_SIZE
HFOV = 40.0
MIN_VFOV = 27.0
BACKGROUND = (13, 20, 32)
PANEL = (15, 23, 36)
CARD = (21, 31, 48)
EDGE = (38, 52, 74)
CONTROL_EDGE = (58, 77, 105)
ACTIVE_FILL = (26, 49, 74)
ACTIVE_EDGE = (76, 127, 171)
TEXT = (230, 237, 247)
SECONDARY = (201, 214, 232)
MUTED = (143, 163, 189)
ACCENT = (124, 200, 255)
CROSSHAIR = (117, 243, 198)
OUTLINE = (8, 13, 22)
BALL = (255, 138, 76)
BALL_CENTER = (255, 210, 184)
GRID_LINE = (24, 37, 58)
HORIZON = (44, 66, 98)
UNLOCK_HINT = "Alt 解锁鼠标"
# Zero-alpha pixels pass clicks through a layered window. Alpha 1 keeps the
# training surface available for click-to-capture and window resizing.
CLEAR_HIT_AREA = (0, 0, 0, 1)
FOCUS_ALPHA = (0, 86, 153)
FOCUS_WIDTH = 2 * tan(radians(11))
FOCUS_HEIGHT = 2 * tan(radians(7))

LATITUDES = tuple(
    (pitch, tuple(direction(yaw, pitch) for yaw in range(0, 361, 10)))
    for pitch in range(-80, 81, 10)
)
MERIDIANS = tuple(
    (radians(yaw), tuple(direction(yaw, pitch) for pitch in range(-90, 91, 10)))
    for yaw in range(0, 360, 10)
)


def finish_button(size: tuple[int, int]) -> pygame.Rect:
    w, h = size
    return pygame.Rect(w - 94, h - 28, 80, 23)


def retry_button(size: tuple[int, int]) -> pygame.Rect:
    w, h = size
    return pygame.Rect(w // 2 - 90, (h - 216) // 2 + 156, 180, 34)


def remaining_time(drill: Drill, now: float) -> float:
    return max(0.0, min(drill.duration, drill.ends_at - now))


def training_marker(drill: Drill, now: float, *, stealth: bool) -> tuple:
    flash = None
    if not stealth and drill.last_hit is not None:
        age = now - drill.last_hit[1]
        if 0 <= age < HIT_FLASH:
            flash = int(age * 60)
    return (
        drill, drill.camera.yaw, drill.camera.pitch, drill.targets,
        len(drill.hit_times), drill.shots, drill.false_starts, drill.timeouts,
        round(remaining_time(drill, now), 1), max(0, ceil(drill.starts_at - now)), flash,
    )


@lru_cache(maxsize=384)
def text_sprite(font: pygame.font.Font, text: str, color: tuple, outlined: bool) -> pygame.Surface:
    glyph = font.render(text, True, color)
    if not outlined:
        return glyph
    shade = font.render(text, True, OUTLINE).premul_alpha()
    image = pygame.Surface((glyph.get_width() + 2, glyph.get_height() + 2), pygame.SRCALPHA)
    for x, y in ((0, 1), (2, 1), (1, 0), (1, 2)):
        image.blit(shade, (x, y), special_flags=pygame.BLEND_RGBA_MAX)
    image.blit(glyph.premul_alpha(), (1, 1), special_flags=pygame.BLEND_PREMULTIPLIED)
    return image


@lru_cache(maxsize=64)
def _ball_sprite(radius: int, on_target: bool = False) -> pygame.Surface:
    size = 2 * radius + 3
    scale = 3
    large = pygame.Surface((size * scale, size * scale), pygame.SRCALPHA)
    center = large.get_rect().center
    pygame.draw.circle(large, ACTIVE_EDGE if on_target else BALL, center, radius * scale)
    pygame.draw.circle(large, ACCENT if on_target else BALL_CENTER, center, max(1, radius * scale // 3))
    return pygame.transform.smoothscale(large.premul_alpha(), (size, size))


@lru_cache(maxsize=2)
def _focus_mask(opacity: int) -> pygame.Surface:
    size = 128
    mask = pygame.Surface((size, size), pygame.SRCALPHA)
    center = (size - 1) / 2
    for y in range(size):
        for x in range(size):
            distance = hypot(x - center, y - center) / center
            if distance < 1:
                # Keep the central aiming zone even and feather the outside edge.
                fade = min(1.0, (1 - distance) / 0.4)
                alpha = round(opacity * fade * fade * (3 - 2 * fade))
                mask.set_at((x, y), (0, 0, 0, alpha))
    return mask


@lru_cache(maxsize=6)
def _focus_backdrop(size: tuple[int, int], opacity: int) -> pygame.Surface:
    return pygame.transform.smoothscale(_focus_mask(opacity), size)


class Screen:
    def __init__(self, surface: pygame.Surface) -> None:
        self.surface = surface
        # The Windows font registry can resolve the regular family to msyhl.ttc.
        regular = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "msyh.ttc"
        has_regular = regular.is_file()
        self.fonts = {
            size: pygame.font.Font(regular, size) if has_regular and size < 16 else pygame.font.SysFont(
                "Microsoft YaHei UI,Microsoft YaHei,Noto Sans CJK SC,SimHei", size, bold=size >= 16,
            )
            for size in (12, 13, 14, 15, 16, 18, 23)
        }
        self.figures = {
            size: pygame.font.SysFont("Saira Semi Condensed,Bahnschrift,Segoe UI,Arial", size, bold=size >= 26)
            for size in (15, 16, 17, 20, 22, 26, 28, 44, 64)
        }
        self.mono = pygame.font.SysFont("Consolas,Courier New", 25, bold=True)

    def label(self, text, pos, size=14, color=TEXT, anchor="topleft", *, outline=False, figures=False, mono=False):
        font = self.mono if mono else (self.figures if figures else self.fonts)[size]
        image = text_sprite(font, text, color, outline)
        rect = image.get_rect(**{anchor: pos})
        self.surface.blit(image, rect, special_flags=pygame.BLEND_PREMULTIPLIED if outline else 0)

    def _brand(self, x: int, y: int) -> None:
        pygame.draw.circle(self.surface, ACCENT, (x, y), 8, 1)
        pygame.draw.circle(self.surface, ACCENT, (x, y), 2)
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            pygame.draw.line(self.surface, ACCENT, (x + dx * 6, y + dy * 6), (x + dx * 11, y + dy * 11))
        self.label("CornerAim", (x + 19, y), 28, TEXT, "midleft", figures=True)

    def _scoreboard(self, stats, left: int, right: int, top: int, *, stealth: bool) -> None:
        split = left + (right - left) * 2 // 5
        if not stealth:
            box = pygame.Rect(left, top + 53, right - left, 74)
            pygame.draw.rect(self.surface, CARD, box, border_radius=8)
            pygame.draw.rect(self.surface, EDGE, box, 1, border_radius=8)
            pygame.draw.line(self.surface, EDGE, (split, top + 64), (split, top + 116))

        primary, *secondary = stats
        self.label(primary[0], (left + 13, top + 59), 14, SECONDARY, outline=stealth)
        size = 44 if self.figures[44].size(primary[1])[0] <= split - left - 24 else 28
        self.label(primary[1], (left + 12, top + 103), size, TEXT, "midleft", outline=stealth, figures=True)
        for index, (label, value) in enumerate(secondary):
            y = top + 73 + index * 32
            self.label(label, (split + 12, y), 14, SECONDARY, "midleft", outline=stealth)
            self.label(value, (right - 13, y), 22, TEXT, "midright", outline=stealth, figures=True)

    def idle(
        self, result: Result | None, sensitivity: Sensitivity, duration: float, notice: str,
        mode: str = "microflick", *, stealth: bool = False, difficulty: str = DEFAULT_DIFFICULTY,
    ) -> None:
        w, h = self.surface.get_size()
        left = max(18, (w - 520) // 2)
        right = w - left
        top = (h - 216) // 2
        mode_name = MODES[mode].name
        level = DIFFICULTIES[difficulty].name
        self.surface.fill(CLEAR_HIT_AREA if stealth else PANEL)
        if stealth and result is None:
            self.label(f"{mode_name} · {level}", (w // 2, h // 2 - 26), 18, TEXT, "center", outline=True)
            self.label("点击开始训练", (w // 2, h // 2 + 6), 16, ACCENT, "center", outline=True)
            self.label(notice or UNLOCK_HINT, (w // 2, h // 2 + 34), 14, BALL if notice else TEXT,
                       "midtop", outline=True)
            return
        status = "本局成绩" if result is not None else "待机"
        if stealth:
            self.label(status, (w // 2, top + 2), 23, TEXT, "midtop", outline=True)
            self.label(f"{mode_name} · {level}", (w // 2, top + 34), 14, MUTED, "midtop", outline=True)
        else:
            pygame.draw.rect(self.surface, EDGE, (0, 0, w, h), 1)
            self._brand(left + 12, top + 16)
            description = f"{mode_name} · {level}"
            if result is None:
                description += f" · {duration:g} 秒"
            self.label(description, (left + 1, top + 33), 14, MUTED)
            pill_width = self.fonts[14].size(status)[0] + 26
            pill = pygame.Rect(right - pill_width, top + 3, pill_width, 26)
            pygame.draw.rect(self.surface, ACTIVE_FILL, pill, border_radius=6)
            pygame.draw.circle(self.surface, ACCENT, (pill.left + 9, pill.centery), 3)
            self.label(status, (right - 7, pill.centery), 14, ACCENT, "midright")

        hits = str(result.hits) if result else "—"
        accuracy = f"{result.accuracy:.0%}" if result and result.shots else "—"
        timing = f"{result.median_ms:.0f} ms" if result and result.median_ms is not None else "—"
        if mode == "tracking":
            tracking = result.tracking if result else None
            stats = (
                ("得分", str(tracking.points) if tracking else "—"),
                ("贴靶率", f"{tracking.ratio:.0%}" if tracking and tracking.seconds else "—"),
                ("贴靶时长", f"{tracking.on_target_seconds:.1f} s" if tracking else "—"),
            )
        elif mode == "reaction":
            early = str(result.false_starts) if result else "—"
            stats = (("有效反应", hits), ("抢跑", early), ("中位反应", timing))
        else:
            stats = (("命中", hits), ("命中率", accuracy), (f"中位{MODES[mode].timing}", timing))
        self._scoreboard(stats, left, right, top, stealth=stealth)

        button = retry_button((w, h))
        if result is not None:
            self.label("鼠标已解锁", (w // 2, top + 128), 14, ACCENT, "midtop", outline=stealth)
        elif not stealth:
            self.label(
                f"DPI {sensitivity.dpi:.5g}   ·   eDPI {sensitivity.edpi:.4g}   ·   {sensitivity.cm360:.4g} cm/360",
                (left, top + 128), 13, MUTED,
            )
        if not stealth:
            pygame.draw.rect(self.surface, ACTIVE_FILL, button, border_radius=7)
            pygame.draw.rect(self.surface, ACTIVE_EDGE, button, 1, border_radius=7)
        self.label("再练一局" if result is not None else "点击开始训练", button.center, 16, ACCENT, "center",
                   outline=stealth)
        if notice:
            self.label(notice, (w // 2, top + 195), 13, BALL, "midtop", outline=stealth)
        elif result is None:
            self.label(UNLOCK_HINT, (w // 2, top + 196), 13, MUTED, "midtop")

    def _grid_line(self, view: View, line, color) -> None:
        points = []
        for vector in line:
            projected = view.project(vector, near=0.15)
            if projected is not None:
                points.append(projected[:2])
                continue
            if len(points) > 1:
                pygame.draw.aalines(self.surface, color, False, points)
            points = []
        if len(points) > 1:
            pygame.draw.aalines(self.surface, color, False, points)

    def _grid(self, view: View, yaw: float, pitch: float) -> None:
        # Include the corners of the viewport and a margin for the sampled arcs.
        cone = degrees(atan(hypot(view.cx, view.cy) / view.focal_length)) + 5
        for latitude, line in LATITUDES:
            if abs(latitude - pitch) <= cone:
                self._grid_line(view, line, HORIZON if latitude == 0 else GRID_LINE)
        cutoff = cos(radians(cone))
        sin_pitch, cos_pitch = sin(radians(pitch)), cos(radians(pitch))
        yaw = radians(yaw)
        for longitude, line in MERIDIANS:
            # Max forward dot product on this pole-to-pole half meridian.
            horizontal = cos_pitch * max(0.0, cos(longitude - yaw))
            if hypot(sin_pitch, horizontal) >= cutoff:
                self._grid_line(view, line, GRID_LINE)

    def _crosshair(self, *, outline: bool) -> None:
        x, y = self.surface.get_rect().center
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            if outline:
                pygame.draw.line(self.surface, OUTLINE, (x + 3 * dx, y + 3 * dy), (x + 8 * dx, y + 8 * dy), 3)
            pygame.draw.line(self.surface, CROSSHAIR, (x + 4 * dx, y + 4 * dy), (x + 7 * dx, y + 7 * dy))
        if outline:
            pygame.draw.circle(self.surface, OUTLINE, (x, y), 2)
        pygame.draw.circle(self.surface, CROSSHAIR, (x, y), 1)

    def _training_hud(self, drill: Drill, remaining: float, *, paused: bool, stealth: bool) -> None:
        w, h = self.surface.get_size()
        hits = len(drill.hit_times)
        accuracy = f"{hits / drill.shots:.0%}" if drill.shots else "—"
        reaction = drill.mode == "reaction"
        tracking = drill.score if isinstance(drill, Tracking) else None
        if tracking is not None:
            action = "贴住小球"
            ratio = f"{tracking.ratio:.0%}" if tracking.seconds else "—"
            status = f"得分 {tracking.points}  ·  贴靶率 {ratio}"
        elif reaction:
            action = "见球即点"
            status = f"有效 {hits}  抢跑 {drill.false_starts}  超时 {drill.timeouts}"
        else:
            action = "左键点射"
            status = f"命中 {hits}  ·  {accuracy}"
        timer = f"{remaining:04.1f} s"
        if stealth:
            self.label(status, (14, 8), 16, outline=True)
            self.label(timer, (w - 14, 8), anchor="topright", outline=True, mono=True)
            if not paused:
                self.label(action, (14, h - 17), 15, TEXT, "midleft", outline=True)
                self.label(UNLOCK_HINT, (w - 14, h - 17), 16, ACCENT, "midright", outline=True)
            return

        pygame.draw.rect(self.surface, PANEL, (0, 0, w, 42))
        pygame.draw.line(self.surface, EDGE, (0, 41), (w - 1, 41))
        mode = pygame.Rect(14, 8, 124, 26)
        pygame.draw.rect(self.surface, CARD, mode, border_radius=6)
        pygame.draw.rect(self.surface, CONTROL_EDGE, mode, 1, border_radius=6)
        self.label(drill.rules.name, mode.center, 15, SECONDARY, "center")
        self.label("已暂停" if paused else action, (mode.right + 14, 21), 14, MUTED, "midleft")
        self.label(timer, (w - 14, 21), anchor="midright", mono=True)

        pygame.draw.rect(self.surface, PANEL, (0, h - 44, w, 44))
        pygame.draw.line(self.surface, EDGE, (0, h - 44), (w - 1, h - 44))
        track = pygame.Rect(14, h - 5, w - 28, 2)
        pygame.draw.rect(self.surface, EDGE, track)
        filled = round(track.w * remaining / drill.duration)
        pygame.draw.rect(self.surface, ACCENT, (track.x, track.y, filled, track.h))
        for step in range(1, 10):
            x = track.x + track.w * step // 10
            pygame.draw.line(self.surface, PANEL, (x, track.top), (x, track.bottom - 1))
        if paused:
            return

        y = h - 23
        if reaction or tracking is not None:
            self.label(status, (14, y), 15, TEXT, "midleft")
        else:
            score = str(hits)
            x = 21 + self.figures[26].size(score)[0]
            self.label(score, (14, y), 26, TEXT, "midleft", figures=True)
            self.label("命中", (x, y), 14, MUTED, "midleft")
            x = max(96, x + 42)
            self.label(accuracy, (x, y), 20, SECONDARY, "midleft", figures=True)
            self.label("命中率", (x + self.figures[20].size(accuracy)[0] + 6, y), 13, MUTED, "midleft")
        keycap = pygame.Rect(w - 116, y - 12, 32, 24)
        pygame.draw.rect(self.surface, ACTIVE_FILL, keycap, border_radius=5)
        pygame.draw.rect(self.surface, ACTIVE_EDGE, keycap, 1, border_radius=5)
        self.label("Alt", keycap.center, 16, ACCENT, "center", figures=True)
        self.label("解锁鼠标", (w - 14, y), 16, ACCENT, "midright")

    def training(
        self, drill: Drill, now: float, *, paused: bool, notice: str, stealth: bool = False, focus_level: int = 0,
    ) -> None:
        w, h = self.surface.get_size()
        self.surface.fill(CLEAR_HIT_AREA if stealth else BACKGROUND)
        # The window crops or extends the reference view without zooming it.
        view = View(drill.camera, (w, h), HFOV, min_vfov=MIN_VFOV, reference_size=PROJECTION_SIZE)
        if stealth and focus_level and not paused:
            size = round(view.focal_length * FOCUS_WIDTH), round(view.focal_length * FOCUS_HEIGHT)
            backdrop = _focus_backdrop(size, FOCUS_ALPHA[focus_level])
            self.surface.blit(backdrop, backdrop.get_rect(center=(view.cx, view.cy)),
                              special_flags=pygame.BLEND_PREMULTIPLIED)
        elif not stealth and drill.mode != "reaction":
            self._grid(view, drill.camera.yaw, drill.camera.pitch)
        if not stealth and drill.last_hit is not None:
            vector, hit_at = drill.last_hit
            age = (now - hit_at) / HIT_FLASH
            if 0 <= age < 1 and (flash := view.project(vector, near=0.15)) is not None:
                x, y, depth = flash
                color = tuple(round(a * (1 - age) + b * age) for a, b in zip(BALL, BACKGROUND))
                radius = view.radius(drill.rules.radius, depth)
                pygame.draw.circle(self.surface, color, (round(x), round(y)), radius + 2 + round(age * 4), 1)
        targets = () if stealth and paused else drill.targets
        on_target = isinstance(drill, Tracking) and drill.on_target and not paused
        for target in targets:
            ball = view.project(target.direction, near=0.15)
            if ball is None:
                continue
            x, y, depth = ball
            radius = view.radius(drill.rules.radius, depth)
            if -radius <= x <= w + radius and -radius <= y <= h + radius:
                sprite = _ball_sprite(radius, on_target)
                self.surface.blit(sprite, sprite.get_rect(center=(round(x), round(y))),
                                  special_flags=pygame.BLEND_PREMULTIPLIED)
        self._training_hud(drill, remaining_time(drill, now), paused=paused, stealth=stealth)

        if not paused and now < drill.starts_at:
            self.label(str(ceil(drill.starts_at - now)), (w // 2, h // 2 - 12), 64, TEXT, "center",
                       outline=stealth, figures=True)
            self.label(drill.rules.name, (w // 2, h // 2 + 28), 16, SECONDARY, "midtop", outline=stealth)
        elif not paused and drill.mode != "reaction":
            self._crosshair(outline=stealth)
        if paused:
            if not stealth:
                card = pygame.Rect(w // 2 - 116, h // 2 - 46, 232, 92)
                pygame.draw.rect(self.surface, CARD, card, border_radius=8)
                pygame.draw.rect(self.surface, CONTROL_EDGE, card, 1, border_radius=8)
            self.label("已暂停", (w // 2, h // 2 - 28), 23, TEXT, "midtop", outline=stealth)
            self.label(
                notice or "点击训练区继续", (w // 2, h // 2 + 10),
                15, BALL if notice else ACCENT, "midtop", outline=stealth,
            )
            finish = finish_button((w, h))
            if not stealth:
                pygame.draw.rect(self.surface, CARD, finish, border_radius=5)
                pygame.draw.rect(self.surface, CONTROL_EDGE, finish, 1, border_radius=5)
            self.label("结束本局", finish.center, 14, SECONDARY, "center", outline=stealth)
