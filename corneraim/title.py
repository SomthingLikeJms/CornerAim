import pygame

from corneraim.view import ACCENT, CLEAR_HIT_AREA, OUTLINE, TEXT, text_sprite

TITLE_HEIGHT = 34
CONTROL_WIDTHS = (54, 38, 38, 38)
CONTROLS = ("settings", "minimize", "maximize", "close")
RIGHT_MARGIN = 6
CONTROL_STRIP = sum(CONTROL_WIDTHS) + RIGHT_MARGIN


def _buttons(width: int):
    x = width - CONTROL_STRIP
    for name, button_width in zip(CONTROLS, CONTROL_WIDTHS):
        yield name, pygame.Rect(x, 5, button_width, TITLE_HEIGHT - 10)
        x += button_width


def title_action(width: int, pos: tuple[int, int]) -> str | None:
    return next((name for name, rect in _buttons(width) if rect.collidepoint(pos)), None)


def _text(surface: pygame.Surface, font: pygame.font.Font, text: str,
          center: tuple[int, int], color) -> None:
    label = text_sprite(font, text, color, True)
    surface.blit(label, label.get_rect(center=center), special_flags=pygame.BLEND_PREMULTIPLIED)


def _icon(surface: pygame.Surface, lines, color) -> None:
    for points in lines:
        pygame.draw.lines(surface, OUTLINE, False, points, 3)
    for points in lines:
        pygame.draw.lines(surface, color, False, points)


def title_surface(
    width: int, font: pygame.font.Font, *, settings: bool, maximized: bool, hover: str | None,
    text_only: bool = False, hidden: bool = False,
) -> pygame.Surface:
    surface = pygame.Surface((width, TITLE_HEIGHT), pygame.SRCALPHA)
    surface.fill(CLEAR_HIT_AREA)
    if hidden:
        return surface

    labels = {"settings": "设置", "minimize": "−", "maximize": "▣" if maximized else "□", "close": "×"}
    for name, rect in _buttons(width):
        x, y = rect.center
        color = ACCENT if name == hover or (name == "settings" and settings) else TEXT
        if name == "close" and name == hover:
            color = (255, 156, 156)
        if text_only or name == "settings":
            _text(surface, font, labels[name], rect.center, color)
        elif name == "minimize":
            _icon(surface, (((x - 5, y + 2), (x + 5, y + 2)),), color)
        elif name == "maximize":
            if maximized:
                lines = (
                    ((x - 2, y - 3), (x - 2, y - 6), (x + 6, y - 6), (x + 6, y + 2), (x + 3, y + 2)),
                    ((x - 5, y - 3), (x + 3, y - 3), (x + 3, y + 5), (x - 5, y + 5), (x - 5, y - 3)),
                )
            else:
                lines = (((x - 5, y - 5), (x + 5, y - 5), (x + 5, y + 5), (x - 5, y + 5), (x - 5, y - 5)),)
            _icon(surface, lines, color)
        else:
            _icon(surface, (((x - 4, y - 4), (x + 4, y + 4)),
                            ((x + 4, y - 4), (x - 4, y + 4))), color)
    return surface
