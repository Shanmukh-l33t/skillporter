#!/usr/bin/env python3
"""Derive website presentation assets from the approved Skillporter logo.

The approved artwork is ``website/public/brand/skillporter-logo.png`` (the
owner's original file, copied byte for byte). This script never redraws the
logo. It only:

  * removes the flat dark background so the lockup can sit on the site colour,
  * crops the lockup and the bridge mark out of the original pixels,
  * scales those crops into favicon, touch icon and social preview sizes.

Run after replacing the master artwork:

    python3 website/scripts/make_brand_assets.py

Requires Pillow. Fonts for the social card come from the installed
``@fontsource-variable`` packages, so run ``npm ci`` in ``website/`` first.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

WEBSITE = Path(__file__).resolve().parent.parent
PUBLIC = WEBSITE / "public"
BRAND = PUBLIC / "brand"
MASTER = BRAND / "skillporter-logo.png"

MIDNIGHT = (7, 13, 25)
DEEP_NAVY = (11, 20, 37)
IVORY = (243, 240, 233)
SECONDARY = (166, 176, 192)
BORDER = (38, 50, 73)
AMBER = (241, 138, 80)

# Pixel regions measured on the 2172x724 master.
MARK_BOX = (185, 223, 750, 477)
LOCKUP_BOX = (185, 223, 2026, 477)
NOISE_FLOOR = 7


def background_colour(im: Image.Image) -> tuple[int, int, int]:
    px = im.load()
    w, h = im.size
    counts: Counter[tuple[int, int, int]] = Counter()
    for x in range(0, w, 9):
        for y in list(range(0, 60, 3)) + list(range(h - 60, h, 3)):
            counts[px[x, y]] += 1
    return counts.most_common(1)[0][0]


def key_out_background(im: Image.Image) -> Image.Image:
    """Return an RGBA copy whose flat background is transparent.

    For each pixel the smallest alpha that explains it as ``fg over bg`` is
    chosen, then the foreground colour is solved for. Compositing the result
    back over the original background reproduces the source pixels, so edges
    keep their original antialiasing.
    """
    bg = background_colour(im)
    src = im.convert("RGB")
    out = Image.new("RGBA", src.size, (0, 0, 0, 0))
    sp = src.load()
    op = out.load()
    w, h = src.size
    for y in range(h):
        for x in range(w):
            r, g, b = sp[x, y]
            dr, dg, db = r - bg[0], g - bg[1], b - bg[2]
            if max(abs(dr), abs(dg), abs(db)) <= NOISE_FLOOR:
                continue
            alpha = max(dr / (255 - bg[0]), dg / (255 - bg[1]), db / (255 - bg[2]), 0.0)
            if alpha <= 0.02:
                continue
            alpha = min(alpha, 1.0)
            fr = min(255, max(0, round(bg[0] + dr / alpha)))
            fg = min(255, max(0, round(bg[1] + dg / alpha)))
            fb = min(255, max(0, round(bg[2] + db / alpha)))
            op[x, y] = (fr, fg, fb, round(alpha * 255))
    return out


def for_light_surface(im: Image.Image) -> Image.Image:
    """Adapt an RGBA lockup for white surfaces without altering geometry or hue.

    Saturated pixels (the electric-blue bridge and warm-amber arc/dot) keep
    their exact RGB values; neutral ivory pixels (wordmark and endpoints) map
    to Midnight (#070D19) with the original alpha preserved.
    """
    out = im.copy()
    px = out.load()
    w, h = out.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a == 0:
                continue
            chroma = max(r, g, b) - min(r, g, b)
            if chroma >= 80:
                # Keep warm amber details (arc, divider, 'i' dot) crisp against white at 28px.
                if r > g > b and (r - b) >= 60:
                    px[x, y] = (min(255, round(r * 0.96)), round(g * 0.84), round(b * 0.72), a)
                continue
            t = max(0.0, (chroma - 28.0) / 52.0)
            nr = round((1.0 - t) * MIDNIGHT[0] + t * r)
            ng = round((1.0 - t) * MIDNIGHT[1] + t * g)
            nb = round((1.0 - t) * MIDNIGHT[2] + t * b)
            px[x, y] = (nr, ng, nb, a)
    return out


def crop_padded(im: Image.Image, box: tuple[int, int, int, int], pad: int) -> Image.Image:
    x0, y0, x1, y1 = box
    return im.crop((x0 - pad, y0 - pad, x1 + pad, y1 + pad))


def scale_to_height(im: Image.Image, height: int) -> Image.Image:
    width = round(im.width * height / im.height)
    return im.resize((width, height), Image.Resampling.LANCZOS)


def scale_to_width(im: Image.Image, width: int) -> Image.Image:
    height = round(im.height * width / im.width)
    return im.resize((width, height), Image.Resampling.LANCZOS)


def icon(mark: Image.Image, size: int, *, radius_ratio: float = 0.22, fill: float = 0.8) -> Image.Image:
    """Bridge mark centred on a midnight rounded square."""
    scale = 4
    big = size * scale
    canvas = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, big - 1, big - 1), radius=round(big * radius_ratio), fill=255)
    canvas.paste(Image.new("RGBA", (big, big), (*MIDNIGHT, 255)), (0, 0), mask)
    m = scale_to_width(mark, round(big * fill))
    canvas.alpha_composite(m, ((big - m.width) // 2, (big - m.height) // 2))
    return canvas.resize((size, size), Image.Resampling.LANCZOS)


def font(name: str, size: int, weight: int) -> ImageFont.FreeTypeFont:
    path = WEBSITE / "node_modules" / "@fontsource-variable" / name / "files" / f"{name}-latin-wght-normal.woff2"
    f = ImageFont.truetype(str(path), size)
    f.set_variation_by_axes([weight])
    return f


def social_card(lockup: Image.Image) -> Image.Image:
    w, h = 1200, 630
    card = Image.new("RGBA", (w, h), (*MIDNIGHT, 255))
    d = ImageDraw.Draw(card)
    margin = 80

    logo = scale_to_width(lockup, 400)
    card.alpha_composite(logo, (margin, 72))

    headline = font("geist", 104, 500)
    d.text((margin - 4, 232), "One skill.", font=headline, fill=IVORY)
    d.text((margin - 4, 346), "Every agent.", font=headline, fill=IVORY)

    sub = font("geist", 30, 400)
    d.text((margin, 492), "The package manager for AI agent skills.", font=sub, fill=SECONDARY)

    d.line((margin, 566, w - margin, 566), fill=BORDER, width=1)
    mono = font("geist-mono", 22, 400)
    d.text((margin, 580), "skillporter.dev", font=mono, fill=SECONDARY)
    label = "uvx skillporter demo"
    tw = d.textlength(label, font=mono)
    d.text((w - margin - tw, 580), label, font=mono, fill=AMBER)
    return card.convert("RGB")


def main() -> None:
    if not MASTER.exists():
        raise SystemExit(f"error: approved logo not found at {MASTER}")
    master = Image.open(MASTER)
    keyed = key_out_background(master)

    lockup = crop_padded(keyed, LOCKUP_BOX, 12)
    mark = crop_padded(keyed, MARK_BOX, 6)

    scale_to_height(lockup, 144).save(BRAND / "skillporter-lockup.webp", lossless=True, method=6)
    scale_to_height(lockup, 144).save(BRAND / "skillporter-lockup.png", optimize=True)
    lockup_light = for_light_surface(lockup)
    scale_to_height(lockup_light, 144).save(BRAND / "skillporter-lockup-light.webp", lossless=True, method=6)
    scale_to_height(lockup_light, 144).save(BRAND / "skillporter-lockup-light.png", optimize=True)
    scale_to_width(mark, 512).save(BRAND / "skillporter-mark.webp", lossless=True, method=6)
    scale_to_width(mark, 512).save(BRAND / "skillporter-mark.png", optimize=True)

    icon(mark, 512, fill=0.76).save(PUBLIC / "icon-512.png", optimize=True)
    icon(mark, 192, fill=0.76).save(PUBLIC / "icon-192.png", optimize=True)
    icon(mark, 180, radius_ratio=0.0, fill=0.74).convert("RGB").save(PUBLIC / "apple-touch-icon.png", optimize=True)
    icon(mark, 32, fill=0.88).save(PUBLIC / "favicon-32.png", optimize=True)
    icon(mark, 48, fill=0.88).save(
        PUBLIC / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)]
    )

    social_card(lockup).save(BRAND / "skillporter-social.png", optimize=True)

    for path in sorted([*BRAND.iterdir(), *PUBLIC.glob("*.png"), PUBLIC / "favicon.ico"]):
        if path.is_file():
            print(f"{path.relative_to(WEBSITE)}  {path.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    main()
