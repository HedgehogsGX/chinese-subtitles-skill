# -*- coding: utf-8 -*-
"""Render one caption line as a transparent 1920x1080 RGBA overlay.

White text, hard dark stroke, soft blurred shadow underneath, no background box.

The shadow is not decoration. A stroke alone survives dark footage but disappears
into bright, busy frames (white sand, snow, muzzle flash) where the outline has
nothing to contrast against. The blurred dark halo gives the glyphs a local
darkening to sit on, which is what keeps them readable at the worst moments.
"""
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H = 1920, 1080
DIALOGUE_BOTTOM = 975      # bottom of the text block; clears a typical FPS HUD.
                           # Other footage puts other things here - check a frame.


def load_font(fontpath, size, index=0, variation=None):
    f = ImageFont.truetype(fontpath, size, index=index)
    if variation:
        # variable fonts (e.g. the Google Fonts Noto Sans SC) need an instance
        f.set_variation_by_name(variation)
    return f


def render_sub(lines, fontpath, size=54, index=0, box_bottom=DIALOGUE_BOTTOM,
               W=W, H=H, variation=None, stroke=5, shadow=True,
               fill=(255, 255, 255, 255), stroke_fill=(0, 0, 0, 255)):
    """Return an RGBA overlay with `lines` centred, block bottom at box_bottom."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    f = load_font(fontpath, size, index, variation)
    asc, desc = f.getmetrics()
    line_h = asc + desc

    probe = ImageDraw.Draw(img)
    rows = [(ln, probe.textlength(ln, font=f)) for ln in lines]
    y0 = box_bottom - len(rows) * line_h

    if shadow:
        sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ds = ImageDraw.Draw(sh)
        y = y0
        for ln, tw in rows:
            ds.text(((W - tw) / 2, y + 4), ln, font=f, fill=(0, 0, 0, 190),
                    stroke_width=stroke + 3, stroke_fill=(0, 0, 0, 190))
            y += line_h
        img = Image.alpha_composite(img, sh.filter(ImageFilter.GaussianBlur(6)))

    d = ImageDraw.Draw(img)
    y = y0
    for ln, tw in rows:
        d.text(((W - tw) / 2, y), ln, font=f, fill=fill,
               stroke_width=stroke, stroke_fill=stroke_fill)
        y += line_h
    return img


def text_width(text, fontpath, size=54, index=0, variation=None):
    """Rendered pixel width - the real constraint on line length, not char count."""
    f = load_font(fontpath, size, index, variation)
    return ImageDraw.Draw(Image.new("RGB", (4, 4))).textlength(text, font=f)
