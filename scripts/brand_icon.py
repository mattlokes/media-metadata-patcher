"""Generate the brand icon: a music note on a tile cut into jigsaw pieces,
with one piece in gold.

Usage: uv run --no-project --with pillow python scripts/brand_icon.py
Writes custom_components/media_metadata_patcher/brand/icon.png (256px) and
icon@2x.png (512px). Drawn at 1024px and downsampled for smooth edges.
"""

from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

S = 1024
OUT = Path(__file__).resolve().parent.parent / "custom_components/media_metadata_patcher/brand"

BLUE = (3, 169, 244)
GOLD = (245, 189, 39)
BLACK = (17, 17, 17)
WHITE = (255, 255, 255)

# Beamed-quaver geometry on the 1024 canvas.
STEM_W = 112
L_STEM_X, R_STEM_X = 340, 660
L_TOP, R_TOP = 200, 150  # the beam slopes up to the right
BEAM_H = 150
L_HEAD, R_HEAD = (300, 750), (620, 690)
HEAD_RX, HEAD_RY = 150, 112

KNOB_R = 62  # jigsaw knob radius
GAP = 6  # half-width of the seams between pieces
GOLD_PIECE = "br"


def note_mask() -> Image.Image:
    m = Image.new("L", (S, S), 0)
    d = ImageDraw.Draw(m)
    for hx, hy in (L_HEAD, R_HEAD):
        size = int(HEAD_RX * 2.6)
        head = Image.new("L", (size, size), 0)
        c = size / 2
        ImageDraw.Draw(head).ellipse((c - HEAD_RX, c - HEAD_RY, c + HEAD_RX, c + HEAD_RY), fill=255)
        head = head.rotate(24, resample=Image.BICUBIC)
        m.paste(255, (int(hx - c), int(hy - c)), head)
    d.rectangle((L_STEM_X, L_TOP, L_STEM_X + STEM_W, L_HEAD[1] - 30), fill=255)
    d.rectangle((R_STEM_X, R_TOP, R_STEM_X + STEM_W, R_HEAD[1] - 30), fill=255)
    d.polygon(
        [
            (L_STEM_X, L_TOP),
            (R_STEM_X + STEM_W, R_TOP),
            (R_STEM_X + STEM_W, R_TOP + BEAM_H),
            (L_STEM_X, L_TOP + BEAM_H),
        ],
        fill=255,
    )
    return m


def tile_mask() -> Image.Image:
    m = Image.new("L", (S, S), 0)
    ImageDraw.Draw(m).rounded_rectangle((32, 32, S - 32, S - 32), radius=210, fill=255)
    return m


def jigsaw_cells() -> dict[str, Image.Image]:
    """A 2x2 grid whose shared edges have interlocking knobs."""
    mid = S / 2
    boxes = {"tl": (0, 0, mid, mid), "tr": (mid, 0, S, mid), "bl": (0, mid, mid, S), "br": (mid, mid, S, S)}
    cells = {}
    for name, box in boxes.items():
        m = Image.new("L", (S, S), 0)
        ImageDraw.Draw(m).rectangle(box, fill=255)
        cells[name] = m

    def knob(owner: str, other: str, at: tuple[float, float], direction: tuple[int, int]) -> None:
        (px, py), (dx, dy) = at, direction
        cx, cy = px + dx * KNOB_R * 0.95, py + dy * KNOB_R * 0.95
        neck = KNOB_R * 0.55
        shape = Image.new("L", (S, S), 0)
        d = ImageDraw.Draw(shape)
        d.ellipse((cx - KNOB_R, cy - KNOB_R, cx + KNOB_R, cy + KNOB_R), fill=255)
        if dx:
            d.rectangle((min(px, cx), py - neck, max(px, cx), py + neck), fill=255)
        else:
            d.rectangle((px - neck, min(py, cy), px + neck, max(py, cy)), fill=255)
        cells[owner] = ImageChops.lighter(cells[owner], shape)
        cells[other] = ImageChops.subtract(cells[other], shape)

    q1, q3 = S * 0.28, S * 0.72
    knob("tl", "tr", (mid, q1), (1, 0))
    knob("tr", "br", (q3, mid), (0, 1))
    knob("br", "bl", (mid, q3), (-1, 0))
    knob("bl", "tl", (q1, mid), (0, -1))
    return cells


def draw() -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    tile = tile_mask()
    note = note_mask()
    # White underlay: the seams between pieces show white on any background.
    img.paste(WHITE + (255,), (0, 0), tile)
    for name, cell in jigsaw_cells().items():
        piece = ImageChops.multiply(tile, cell).filter(ImageFilter.MinFilter(GAP * 2 + 1))
        img.paste((GOLD if name == GOLD_PIECE else BLUE) + (255,), (0, 0), piece)
        img.paste(BLACK + (255,), (0, 0), ImageChops.multiply(note, piece))
    return img


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    icon = draw()
    for size, name in ((256, "icon.png"), (512, "icon@2x.png")):
        icon.resize((size, size), Image.LANCZOS).save(OUT / name, optimize=True)
        print(OUT / name)


if __name__ == "__main__":
    main()
