# FILE: packaging/wizard_art.py
"""
Draw the installers' artwork from assets/intval.png:

    python packaging/wizard_art.py <out dir>

    wizard-large(.bmp, @2x)   Inno Setup's side panel on the welcome/finish pages
    wizard-small(.bmp, @2x)   Inno Setup's top-right corner on the other pages
    banner.png                the Linux installer's header
"""

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
ICON = Image.open(ROOT / "assets" / "intval.png").convert("RGBA")
TOP, BOTTOM = (25, 26, 27), (31, 42, 52)  # the app's dark chrome, fading to its blue


def _font(size, bold=False):
    for name in (("segoeuib.ttf", "DejaVuSans-Bold.ttf") if bold else ("segoeui.ttf", "DejaVuSans.ttf")):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _gradient(w, h):
    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / max(1, h - 1)
        d.line([(0, y), (w, y)], fill=tuple(round(a + (b - a) * t) for a, b in zip(TOP, BOTTOM)))
    return img


def large(scale):
    w, h = 164 * scale, 314 * scale
    img = _gradient(w, h)
    s = 84 * scale
    img.paste(ICON.resize((s, s), Image.LANCZOS), ((w - s) // 2, 70 * scale), ICON.resize((s, s), Image.LANCZOS))
    d = ImageDraw.Draw(img)
    for text, y, size, bold, fill in (("INTVAL", 172, 22, True, (235, 235, 235)),
                                      ("Intrinsic Value", 202, 11, False, (170, 175, 180)),
                                      ("Calculator", 218, 11, False, (170, 175, 180))):
        f = _font(size * scale, bold)
        tw = d.textlength(text, font=f)
        d.text(((w - tw) / 2, y * scale), text, font=f, fill=fill)
    return img


def small(scale):
    s = 55 * scale
    img = Image.new("RGB", (s, s), (255, 255, 255))
    i = ICON.resize((s - 6 * scale, s - 6 * scale), Image.LANCZOS)
    img.paste(i, (3 * scale, 3 * scale), i)
    return img


def banner():
    w, h = 640, 84
    img = _gradient(w, h).rotate(0)
    i = ICON.resize((52, 52), Image.LANCZOS)
    img.paste(i, (20, 16), i)
    d = ImageDraw.Draw(img)
    d.text((88, 18), "INTVAL", font=_font(24, True), fill=(235, 235, 235))
    d.text((88, 50), "Intrinsic Value Calculator - Setup", font=_font(13), fill=(170, 175, 180))
    return img


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    out.mkdir(parents=True, exist_ok=True)
    for scale, tag in ((1, ""), (2, "@2x")):
        large(scale).save(out / f"wizard-large{tag}.bmp")
        small(scale).save(out / f"wizard-small{tag}.bmp")
    banner().save(out / "banner.png")
    print(f"artwork in {out}")
