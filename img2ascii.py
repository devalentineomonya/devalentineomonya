"""Convert avatar.png into coloured ASCII art (ascii_art.json).

    pip install pillow numpy
    python img2ascii.py avatar.png --mask mask.png

mask.png is optional: white = subject, black = background, dark grey (64) = areas
to leave in shadow (the face). From the background only the light sources are kept.
Without a mask the whole picture is converted.
"""
import argparse
import json

import numpy as np
from PIL import Image, ImageFilter

RAMP = " .':-=+*#%@"
COLS, ROWS = 96, 53  # matches a 7px font in a square box


def convert(path, mask_path=None):
    img = Image.open(path).convert("RGB").filter(ImageFilter.UnsharpMask(radius=4, percent=90))
    rgb = np.asarray(img.resize((COLS, ROWS), Image.LANCZOS), dtype=float) / 255
    lum = rgb @ [0.2126, 0.7152, 0.0722]
    if mask_path:
        m = Image.open(mask_path).convert("L").resize((COLS, ROWS), Image.BOX)
        values = np.asarray(m)
        fg = values > 32
        void = fg & (values < 110)
    else:
        fg = np.ones(lum.shape, bool)
        void = np.zeros(lum.shape, bool)

    rows = []
    for y in range(ROWS):
        row = []
        for x in range(COLS):
            if fg[y, x]:
                # gamma lifts the shadows; the face stays an empty void
                level = np.clip((lum[y, x] - 0.012) / 0.68, 0, 1) ** 0.55
                if not void[y, x]:
                    level = max(level, 0.1)  # texture, so the body reads as solid
                elif lum[y, x] < 0.09:
                    level = 0  # inside the hood
                edge = any(
                    0 <= y + dy < ROWS and 0 <= x + dx < COLS and not fg[y + dy, x + dx]
                    for dy, dx in ((0, 1), (0, -1), (-1, 0), (1, 0))
                )
                if edge:
                    level = max(level, 0.32)  # keep the silhouette readable
                kind = "s"
            else:
                level = np.clip((lum[y, x] - 0.22) / 0.7, 0, 1) ** 0.9
                kind = "b"
            ch = RAMP[int(round(level * (len(RAMP) - 1)))]
            row.append([ch, kind, round(float(level), 2), [int(v * 255) for v in rgb[y, x]]])
        rows.append(row)
    return rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--mask")
    ap.add_argument("--out", default="ascii_art.json")
    a = ap.parse_args()
    art = convert(a.image, a.mask)
    with open(a.out, "w") as f:
        json.dump(art, f, separators=(",", ":"))
    print("\n".join("".join(c[0] for c in r).rstrip() for r in art))
