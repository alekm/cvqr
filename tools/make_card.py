#!/usr/bin/env python3
"""
make_card.py — card-back layout in real millimetres, emitted as a two-layer
SVG for LightBurn.

Process this targets: on bare/brushed stainless, ablate the dark modules to a
shallow depth for permanence, then run a second low-power MOPA pass over the
same geometry to grow a black oxide in the recesses. Two contrast mechanisms,
independent failure modes: if the oxide ever degrades, the depth still holds
the code and a scanner can read it off shadow.

Both passes share one geometry but need different laser settings, so they are
emitted as two SVG groups with different stroke/fill colours. LightBurn maps
colour to layer, so you get two layers with independent parameters and — this
is the point — perfect registration, because they were generated from the same
origin and never move.

  ./make_card.py audio/encoded/final.txt --ecc Q --card-w 88 --card-h 64 \
      --shrink 0.02 --out artwork/card_back

Bloom compensation — read this before using --shrink. Print-world instinct says
to inset the dark modules so thermal bloom lands them on nominal. Measured
against two decoder engines, that instinct is wrong here, and dangerously
asymmetric:

    dark modules OVERSIZE  by up to 14% per side : both engines still read
    dark modules UNDERSIZE by     1.7% per side  : zbar already fails

The reason is the finder patterns. zbar is scanline-based and checks the
1:1:3:1:1 run-length ratio through each finder; thinning the dark bars breaks
that ratio long before the data modules are in any trouble. zxing does a more
robust grid fit and tolerates both directions.

So bloom is in the SAFE direction and shrink is in the dangerous one. Default
--shrink to 0. Only apply a positive value if a coupon measurement shows the
finished modules are genuinely oversize, and never go past the point where a
single light module between two dark neighbours starts closing up (about 25%
of pitch of growth per side).
"""
import argparse
import pathlib

import segno

CARD_W, CARD_H = 88.0, 64.0
MARGIN = 5.0
GUTTER = 4.0

ABLATE_COLOR = "#000000"    # LightBurn layer 1: depth pass
BLACKEN_COLOR = "#ff0000"   # LightBurn layer 2: oxide pass

# The text engraved beside the code. Whose card this is does not belong in a
# repository, so the real lines live in card_text.txt at the project root,
# which is not committed. These placeholders are what you get without it, and
# the run summary says plainly which of the two was used — a card marked with
# "YOUR NAME" is a wasted blank, and the laser does not undo.
CARD_TEXT_FILE = "card_text.txt"

PLACEHOLDER_LINES = [
    ("YOUR NAME", 3.4, 700),
    ("VOICE ARCHIVE", 1.9, 400),
    ("", 2.6, 400),
    ("CVQR/1", 2.0, 700),
    ("CODEC2 · 8 kHz", 1.5, 400),
    ("MONO · OFFLINE", 1.5, 400),
    ("OPEN RECOVERY", 1.5, 400),
    ("", 2.6, 400),
    ("MAKER", 2.0, 700),
]


def load_lines(path):
    """Read card text from a file: one `size|weight|text` row per line.

    An empty text field is a spacer. Returns None if the file is absent, so
    the caller can fall back and say so.
    """
    if path is None or not path.exists():
        return None
    lines = []
    for n, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        try:
            size, weight, text = raw.split("|", 2)
            lines.append((text, float(size), int(weight)))
        except ValueError:
            raise SystemExit(f"{path}:{n}: expected `size|weight|text`, got {raw!r}")
    if not lines:
        raise SystemExit(f"{path}: no card text found")
    return lines


def merge_runs(matrix, n, want_dark=True):
    """Merge horizontal runs of same-valued modules into (x, y, w) rectangles."""
    runs = []
    for y in range(n):
        x = 0
        while x < n:
            if bool(matrix[y][x]) != want_dark:
                x += 1
                continue
            start = x
            while x < n and bool(matrix[y][x]) == want_dark:
                x += 1
            runs.append((start, y, x - start))
    return runs


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("path", nargs="?", type=pathlib.Path)
    src.add_argument("--text", help="payload as a literal string")
    ap.add_argument("--ecc", default="Q", choices=list("LMQH"))
    ap.add_argument("--out", type=pathlib.Path, required=True, help="basename, no extension")
    ap.add_argument("--card-w", type=float, default=CARD_W, help="measured card width, mm")
    ap.add_argument("--card-h", type=float, default=CARD_H, help="measured card height, mm")
    ap.add_argument("--margin", type=float, default=MARGIN)
    ap.add_argument("--shrink", type=float, default=0.0,
                    help="inset each dark module by this many mm to compensate for bloom")
    ap.add_argument("--lines", type=pathlib.Path, default=None,
                    help=f"card text file; defaults to {CARD_TEXT_FILE} at the project root")
    ap.add_argument("--marks", default="dark", choices=("dark", "light"),
                    help="dark = mark the dark modules (bare stock). "
                         "light = mark the light modules (pre-blackened stock).")
    args = ap.parse_args()

    text_path = args.lines or (pathlib.Path(__file__).resolve().parent.parent / CARD_TEXT_FILE)
    lines = load_lines(text_path)
    text_source = str(text_path) if lines else f"PLACEHOLDER — no {CARD_TEXT_FILE} found"
    if lines is None:
        lines = PLACEHOLDER_LINES

    cw, ch, m = args.card_w, args.card_h, args.margin
    payload = (args.text if args.text is not None else args.path.read_text()).strip()
    qr = segno.make(payload, error=args.ecc, mode="alphanumeric", boost_error=False)
    matrix = [list(r) for r in qr.matrix]
    n = len(matrix)

    block = ch - 2 * m                      # code + quiet zone, square
    pitch = block / (n + 8)
    code = pitch * n
    bx, by = cw - m - block, m              # right-aligned
    ox, oy = bx + 4 * pitch, by + 4 * pitch

    want_dark = args.marks == "dark"
    runs = merge_runs(matrix, n, want_dark)

    # A run is inset on all four sides. Insetting a horizontal run shortens it
    # at both ends, which is correct: its neighbours in x are light modules.
    d = args.shrink
    rects = []
    for mx, my, mw in runs:
        x, y = ox + mx * pitch + d, oy + my * pitch + d
        w, h = mw * pitch - 2 * d, pitch - 2 * d
        if w > 0 and h > 0:
            rects.append((x, y, w, h))

    quiet = []
    if not want_dark:
        # Marking light modules means the quiet zone must be marked too, or the
        # code has no defined edge.
        quiet = [(bx, by, block, 4 * pitch),
                 (bx, oy + code, block, 4 * pitch),
                 (bx, oy, 4 * pitch, code),
                 (ox + code, oy, 4 * pitch, code)]

    def rect_svg(rs):
        return "\n".join(f'      <rect x="{x:.4f}" y="{y:.4f}" '
                         f'width="{w:.4f}" height="{h:.4f}"/>' for x, y, w, h in rs)

    ty = (ch - sum(s * 1.75 for _, s, _ in lines)) / 2
    text = []
    for line, size, weight in lines:
        ty += size * 1.75
        if line:
            text.append(f'      <text x="{m:.3f}" y="{ty:.3f}" font-size="{size}" '
                        f'font-weight="{weight}" letter-spacing="{size * 0.08:.3f}" '
                        f'font-family="Helvetica, Arial, sans-serif">{line}</text>')
    geometry = rect_svg(quiet + rects) + "\n" + "\n".join(text)

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{cw}mm" height="{ch}mm"
     viewBox="0 0 {cw} {ch}">
  <!-- CVQR/1 card back. 1 user unit = 1 mm.
       Two layers, identical geometry, different laser settings:
         #000000  pass 1 — ablate to depth
         #ff0000  pass 2 — MOPA black oxide in the recesses
       Run pass 1 completely, clean the part, then run pass 2 WITHOUT
       re-homing or moving the part. -->
  <g id="pass1-ablate" fill="{ABLATE_COLOR}" stroke="none">
{geometry}
  </g>
  <g id="pass2-blacken" fill="{BLACKEN_COLOR}" stroke="none">
{geometry}
  </g>
</svg>
'''
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.with_suffix(".svg").write_text(svg)

    # Preview: brushed steel card, marked areas black.
    prev = svg.replace(f'<g id="pass2-blacken" fill="{BLACKEN_COLOR}"',
                       '<g id="pass2-blacken" fill="#0d0d0f"')
    prev = prev.replace(f'<g id="pass1-ablate" fill="{ABLATE_COLOR}"',
                        '<g id="pass1-ablate" fill="#0d0d0f"')
    prev = prev.replace('<g id="pass1-ablate"',
                        f'<rect width="{cw}" height="{ch}" rx="3" fill="#b8bcc0"/>\n  <g id="pass1-ablate"')
    args.out.with_name(args.out.name + "_preview").with_suffix(".svg").write_text(prev)

    marked = sum(w * h for _, _, w, h in rects + quiet)
    print(f"payload       {len(payload)} characters")
    print(f"symbol        QR version {qr.version}, ECC {args.ecc}, {n}x{n} modules")
    print(f"card          {cw} x {ch} mm, {m} mm margins")
    print(f"QR block      {block:.2f} mm square at x={bx:.2f} y={by:.2f}")
    print(f"code area     {code:.2f} mm   module pitch {pitch:.3f} mm")
    print(f"quiet zone    {4 * pitch:.2f} mm, {'MARKED' if quiet else 'left as substrate'}")
    print(f"marking       {args.marks} modules, shrink {d:.3f} mm/side")
    print(f"marked area   {marked:.0f} mm^2  ({100 * marked / (block * block):.0f}% of the block), x2 passes")
    print(f"objects       {len(rects) + len(quiet)} rects per layer, 2 layers")
    print(f"card text     {text_source}")
    print(f"wrote         {args.out.with_suffix('.svg')} + _preview.svg")


if __name__ == "__main__":
    main()
