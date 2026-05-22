"""Tray icon images, drawn with Pillow and cached per state.

States use distinct shape AND color (not color alone) so they read on any
theme and for color-blind users:

    read_only    closed gray padlock
    writable     open green padlock
    unreachable  red disc with "?"   (Syncthing not reachable / bad key)
    incomplete   dim-red disc with "?" (no API key / not configured)

A small blue corner dot overlays any state while a folder is actively syncing.
"""
from __future__ import annotations

from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

# State identifiers.
READ_ONLY = "read_only"
WRITABLE = "writable"
UNREACHABLE = "unreachable"
INCOMPLETE = "incomplete"

_SIZE = 64

_COLOR = {
    READ_ONLY: (150, 157, 165, 255),    # gray
    WRITABLE: (52, 168, 83, 255),       # green
    UNREACHABLE: (234, 67, 53, 255),    # red
    INCOMPLETE: (176, 96, 88, 255),     # dim red
}
_KEYHOLE = (255, 255, 255, 235)
_SYNC_DOT = (66, 133, 244, 255)         # blue
_WHITE = (255, 255, 255, 255)


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in ("arialbd.ttf", "arial.ttf", "segoeui.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _draw_padlock(draw: ImageDraw.ImageDraw, color, *, locked: bool) -> None:
    # Body: a rounded rectangle low on the canvas.
    body = (16, 30, 48, 57)
    if locked:
        # Symmetric shackle, both legs entering the body.
        draw.arc((20, 12, 44, 36), start=180, end=360, fill=color, width=6)
        draw.line((23, 24, 23, 32), fill=color, width=6)
        draw.line((41, 24, 41, 32), fill=color, width=6)
    else:
        # Shackle swung up to the left; left leg lifted clear of the body.
        draw.arc((13, 7, 37, 31), start=180, end=360, fill=color, width=6)
        draw.line((34, 19, 34, 31), fill=color, width=6)   # right leg into body
        draw.line((16, 19, 16, 26), fill=color, width=6)   # left leg open
    draw.rounded_rectangle(body, radius=6, fill=color)
    # Keyhole: circle + tapered slot.
    draw.ellipse((29, 38, 35, 44), fill=_KEYHOLE)
    draw.polygon([(31, 42), (33, 42), (35, 52), (29, 52)], fill=_KEYHOLE)


def _draw_status_disc(draw: ImageDraw.ImageDraw, color) -> None:
    draw.ellipse((8, 8, 56, 56), fill=color)
    font = _font(40)
    text = "?"
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    x = (_SIZE - (right - left)) / 2 - left
    y = (_SIZE - (bottom - top)) / 2 - top
    draw.text((x, y), text, font=font, fill=_WHITE)


def _draw_sync_dot(draw: ImageDraw.ImageDraw) -> None:
    draw.ellipse((42, 42, 60, 60), fill=_SYNC_DOT)
    draw.ellipse((42, 42, 60, 60), outline=_WHITE, width=2)


@lru_cache(maxsize=None)
def make_icon(state: str, syncing: bool = False) -> Image.Image:
    img = Image.new("RGBA", (_SIZE, _SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    color = _COLOR.get(state, _COLOR[UNREACHABLE])
    if state in (READ_ONLY, WRITABLE):
        _draw_padlock(draw, color, locked=(state == READ_ONLY))
    else:
        _draw_status_disc(draw, color)
    if syncing:
        _draw_sync_dot(draw)
    return img
