# -*- coding: utf-8 -*-
"""Generate every PashuAarogya app icon from one source logo.

    python make_icons.py [path-to-logo]

With no argument it looks for frontend/icons/logo-source.(png|jpg|jpeg|webp).

The source artwork is a white Kalamkari mark on a charcoal ground with the
wordmark underneath. Small icons must NOT carry that wordmark — at 32px it is
an illegible smudge — so the script splits the art from the text by finding the
blank band between them, and uses the art alone for every square icon.

Writes into frontend/icons/:
    logo.png          full logo incl. wordmark, 1024px  (landing hero)
    logo-mark.png     artwork only, square              (headers, 44-52px)
    icon-192.png      PWA icon (rounded)
    icon-512.png      PWA icon
    maskable-512.png  Android adaptive (art inside the 80% safe zone)
    apple-180.png     iOS home screen
    favicon-32.png    browser tab
"""
import os
import sys

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.abspath(__file__))
ICONS = os.path.join(ROOT, "frontend", "icons")
CANDIDATES = ["logo-source.png", "logo-source.jpg", "logo-source.jpeg",
              "logo-source.webp"]


def find_source(argv):
    if len(argv) > 1:
        return argv[1]
    for c in CANDIDATES:
        p = os.path.join(ICONS, c)
        if os.path.exists(p):
            return p
    return None


def ink_rows(rgb, bg, tol=60):
    """Count non-background pixels per row — used to find art / text bands."""
    w, h = rgb.size
    px = rgb.load()
    step = max(1, w // 220)
    out = []
    for y in range(h):
        n = 0
        for x in range(0, w, step):
            p = px[x, y]
            if abs(p[0] - bg[0]) + abs(p[1] - bg[1]) + abs(p[2] - bg[2]) > tol:
                n += 1
        out.append(n)
    return out


def bands(counts, min_ink=1, min_gap=6):
    """Contiguous runs of inked rows, separated by gaps of >= min_gap rows."""
    runs, start, gap = [], None, 0
    for i, c in enumerate(counts):
        if c >= min_ink:
            if start is None:
                start = i - gap if gap and start is not None else i
            gap = 0
        else:
            if start is not None:
                gap += 1
                if gap >= min_gap:
                    runs.append((start, i - gap))
                    start, gap = None, 0
    if start is not None:
        runs.append((start, len(counts) - 1))
    return [(a, b) for a, b in runs if b > a]


def trim_box(rgb, bg, tol=60):
    """Bounding box of everything that is not background."""
    w, h = rgb.size
    px = rgb.load()
    xs, ys = [], []
    sx = max(1, w // 300)
    sy = max(1, h // 300)
    for y in range(0, h, sy):
        for x in range(0, w, sx):
            p = px[x, y]
            if abs(p[0] - bg[0]) + abs(p[1] - bg[1]) + abs(p[2] - bg[2]) > tol:
                xs.append(x); ys.append(y)
    if not xs:
        return (0, 0, w, h)
    return (max(0, min(xs) - sx), max(0, min(ys) - sy),
            min(w, max(xs) + sx + 1), min(h, max(ys) + sy + 1))


def tile(mark, size, pad_ratio, radius_ratio, ground):
    """Centre the mark on a rounded brand-coloured tile."""
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(canvas)
    r = int(size * radius_ratio)
    box = [0, 0, size - 1, size - 1]
    if r:
        d.rounded_rectangle(box, radius=r, fill=ground + (255,))
    else:
        d.rectangle(box, fill=ground + (255,))
    inner = int(size * (1 - 2 * pad_ratio))
    m = mark.copy()
    m.thumbnail((inner, inner), Image.LANCZOS)
    canvas.paste(m, ((size - m.width) // 2, (size - m.height) // 2))
    return canvas


def main():
    src = find_source(sys.argv)
    if not src or not os.path.exists(src):
        print("No source logo found.\n"
              "  Save it as: frontend/icons/logo-source.png\n"
              "  or run:     python make_icons.py <path-to-logo>")
        return 1
    os.makedirs(ICONS, exist_ok=True)
    raw = Image.open(src).convert("RGB")
    # sample the real ground colour from the corners — never hardcode it, or a
    # seam shows where the artwork tile meets the generated tile
    w, h = raw.size
    corners = [raw.getpixel(p) for p in
               ((2, 2), (w - 3, 2), (2, h - 3), (w - 3, h - 3))]
    ground = tuple(sum(c[i] for c in corners) // len(corners) for i in range(3))

    counts = ink_rows(raw, ground)
    runs = bands(counts, min_ink=1, min_gap=max(4, h // 90))
    if not runs:
        print("could not find any artwork in the source"); return 1
    # the tallest band is the artwork; anything below it is the wordmark
    art_top, art_bot = max(runs, key=lambda r: r[1] - r[0])

    full = raw.copy()
    full.thumbnail((1024, 1024), Image.LANCZOS)
    full.save(os.path.join(ICONS, "logo.png"))
    print(f"ground={ground}  art rows {art_top}-{art_bot} of {h}"
          f"  ({len(runs)} bands: wordmark excluded)")

    art = raw.crop((0, art_top, w, art_bot + 1))
    l, t, r, b = trim_box(art, ground)
    art = art.crop((l, t, r, b))

    # square canvas for the header circle, padded so nothing is clipped
    side = int(max(art.size) * 1.06)
    mark = Image.new("RGB", (side, side), ground)
    mark.paste(art, ((side - art.width) // 2, (side - art.height) // 2))
    mark.resize((512, 512), Image.LANCZOS).save(os.path.join(ICONS, "logo-mark.png"))

    out = {
        "icon-192.png": tile(art, 192, 0.11, 0.20, ground),
        "icon-512.png": tile(art, 512, 0.11, 0.20, ground),
        "maskable-512.png": tile(art, 512, 0.21, 0.0, ground),   # Android safe zone
        "apple-180.png": tile(art, 180, 0.10, 0.0, ground),
        "favicon-32.png": tile(art, 32, 0.05, 0.22, ground),
    }
    for name, im in out.items():
        im.save(os.path.join(ICONS, name))
        print("  wrote", name, im.size)
    print("done — hard-refresh the app to see the new icons")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
