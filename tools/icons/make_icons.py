"""
Draws the Toolbox app icons (roadmap G1) into core_plugins/ui/icons/: a white toolbox on the accent blue.
Run once after changing the design:  python3 tools/icons/make_icons.py   (needs Pillow; host-side only)

  icon-192.png / icon-512.png   "any" purpose — rounded square, used for the window/taskbar/app menu
  icon-maskable-512.png         full-bleed square, artwork inside the 80 % safe zone (round/squircle launchers)
  favicon-32.png                browser tab icon (also served as /favicon.ico)
"""

from pathlib import Path

from PIL import Image, ImageDraw

ACCENT = (79, 94, 240)     # --accent in theme-tokens.css / workspace.html
DARK = (52, 64, 196)
WHITE = (255, 255, 255)
OUT = Path(__file__).resolve().parents[2] / "core_plugins" / "ui" / "icons"
S = 1024  # draw big, scale down (smooth edges)


def toolbox(d: ImageDraw.ImageDraw, cx: float, cy: float, w: float) -> None:
    """A toolbox centred at (cx, cy), `w` wide."""
    h = w * 0.58
    x0, y0, x1, y1 = cx - w / 2, cy - h / 2 + w * 0.08, cx + w / 2, cy + h / 2 + w * 0.08
    hw, ht = w * 0.36, w * 0.16                      # handle
    d.rounded_rectangle((cx - hw / 2, y0 - ht, cx + hw / 2, y0 + w * 0.04), radius=w * 0.06, outline=WHITE,
                        width=int(w * 0.07))
    d.rounded_rectangle((x0, y0, x1, y1), radius=w * 0.08, fill=WHITE)  # body
    d.rectangle((x0, y0 + h * 0.36, x1, y0 + h * 0.36 + w * 0.045), fill=DARK)  # lid line
    lw, lh = w * 0.16, w * 0.13                      # latch
    d.rounded_rectangle((cx - lw / 2, y0 + h * 0.36 - lh * 0.3, cx + lw / 2, y0 + h * 0.36 + lh * 0.7),
                        radius=w * 0.025, fill=DARK)


def rounded(size: int) -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, S - 1, S - 1), radius=S * 0.22, fill=ACCENT)
    toolbox(d, S / 2, S / 2, S * 0.62)
    return img.resize((size, size), Image.LANCZOS)


def maskable(size: int) -> Image.Image:
    img = Image.new("RGBA", (S, S), ACCENT + (255,))
    toolbox(ImageDraw.Draw(img), S / 2, S / 2, S * 0.50)  # inside the 80 % safe circle
    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for n in (192, 512):
        rounded(n).save(OUT / f"icon-{n}.png", optimize=True)
    maskable(512).save(OUT / "icon-maskable-512.png", optimize=True)
    rounded(32).save(OUT / "favicon-32.png", optimize=True)
    print("wrote", ", ".join(sorted(p.name for p in OUT.glob("*.png"))))


if __name__ == "__main__":
    main()
