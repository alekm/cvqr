#!/usr/bin/env python3
"""
make_coupon.py — parameter-sweep test plate for a 4x4 inch stainless coupon.

Fills the plate with a grid of small QR codes marked at the SAME module pitch
as the final card, so each cell answers "does this parameter set produce a
readable module at 0.58 mm?" without spending a real card per data point.

Each cell's QR encodes its own coordinates, so a successful scan tells you
which cell you just read — no key to keep, no ambiguity when 25 codes look
identical. Cells that don't scan simply stay silent, which is the answer.

Same two-layer output as make_card.py:
    #000000  pass 1 — ablate to depth
    #ff0000  pass 2 — MOPA black oxide in the recesses

Assign the sweep however you like — the usual arrangement is one axis for
heat input (power x speed) and the other for the oxide pass (frequency or
pulse width). Write down which is which before you start; five identical rows
of marks are impossible to reconstruct afterwards from memory.

  ./make_coupon.py --pitch 0.581 --out artwork/coupon_a
"""
import argparse
import pathlib

import segno

PLATE = 101.6           # 4 inches
MARGIN = 6.0
GAP = 1.5
SWATCH = 4.0            # solid squares along the bottom, for depth/darkness checks


def merge_runs(matrix, n):
    runs = []
    for y in range(n):
        x = 0
        while x < n:
            if not matrix[y][x]:
                x += 1
                continue
            start = x
            while x < n and matrix[y][x]:
                x += 1
            runs.append((start, y, x - start))
    return runs


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pitch", type=float, required=True,
                    help="module pitch in mm — must match the final card")
    ap.add_argument("--plate-w", type=float, default=PLATE, help="coupon width, mm")
    ap.add_argument("--plate-h", type=float, default=None, help="coupon height, mm (default: square)")
    ap.add_argument("--margin", type=float, default=MARGIN)
    ap.add_argument("--label", default="CVQR", help="prefix inside each cell's payload")
    ap.add_argument("--out", type=pathlib.Path, required=True)
    args = ap.parse_args()
    pw = args.plate_w
    ph = args.plate_h if args.plate_h is not None else pw

    # Size one cell from a representative payload, then see how many fit.
    probe = segno.make(f"{args.label} R1C1", error="Q", mode="alphanumeric",
                       boost_error=False, micro=False)
    n = probe.symbol_size(border=0)[0]
    block = (n + 8) * args.pitch
    usable_w = pw - 2 * args.margin
    usable_h = ph - 2 * args.margin
    cols = int((usable_w + GAP) // (block + GAP))
    if cols < 2:
        raise SystemExit(f"cell is {block:.1f} mm; only {cols} fit across {usable_w:.1f} mm")
    rows = int((usable_h - SWATCH - GAP) // (block + GAP))

    grid_w = cols * block + (cols - 1) * GAP
    x0 = (pw - grid_w) / 2
    y0 = args.margin

    rects, labels = [], []
    for r in range(rows):
        for c in range(cols):
            payload = f"{args.label} R{r + 1}C{c + 1}"
            qr = segno.make(payload, error="Q", mode="alphanumeric",
                             boost_error=False, micro=False)
            m = [list(row) for row in qr.matrix]
            size = len(m)
            if size != n:      # keep every cell dimensionally identical
                continue
            bx = x0 + c * (block + GAP)
            by = y0 + r * (block + GAP)
            ox, oy = bx + 4 * args.pitch, by + 4 * args.pitch
            for mx, my, mw in merge_runs(m, size):
                rects.append((ox + mx * args.pitch, oy + my * args.pitch,
                              mw * args.pitch, args.pitch))

    # solid swatches along the bottom: one per column, for depth and darkness
    sy = y0 + rows * (block + GAP)
    for c in range(cols):
        sx = x0 + c * (block + GAP) + (block - SWATCH) / 2
        rects.append((sx, sy, SWATCH, SWATCH))
        labels.append((sx + SWATCH + 0.8, sy + SWATCH * 0.75, str(c + 1), 2.4))
    for r in range(rows):
        labels.append((x0 - 4.2, y0 + r * (block + GAP) + block / 2, chr(65 + r), 2.4))

    def svg_body():
        out = [f'      <rect x="{x:.4f}" y="{y:.4f}" width="{w:.4f}" height="{h:.4f}"/>'
               for x, y, w, h in rects]
        out += [f'      <text x="{x:.3f}" y="{y:.3f}" font-size="{s}" font-weight="700" '
                f'font-family="Helvetica, Arial, sans-serif">{t}</text>'
                for x, y, t, s in labels]
        return "\n".join(out)

    body = svg_body()
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{pw}mm" height="{ph}mm"
     viewBox="0 0 {pw} {ph}">
  <!-- CVQR test coupon. 1 user unit = 1 mm. Module pitch {args.pitch} mm.
       Two layers, identical geometry:
         #000000  pass 1 — ablate to depth
         #ff0000  pass 2 — MOPA black oxide
       Vary parameters per CELL, not per plate. Each cell's QR reports its own
       coordinates when it scans. -->
  <g id="pass1-ablate" fill="#000000" stroke="none">
{body}
  </g>
  <g id="pass2-blacken" fill="#ff0000" stroke="none">
{body}
  </g>
</svg>
'''
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.with_suffix(".svg").write_text(svg)

    prev = svg.replace('fill="#000000"', 'fill="#0d0d0f"').replace('fill="#ff0000"', 'fill="#0d0d0f"')
    prev = prev.replace('<g id="pass1-ablate"',
                        f'<rect width="{pw}" height="{ph}" rx="3" fill="#b8bcc0"/>\n  <g id="pass1-ablate"')
    args.out.with_name(args.out.name + "_preview").with_suffix(".svg").write_text(prev)

    print(f"coupon        {pw} x {ph} mm")
    print(f"module pitch  {args.pitch} mm  (matches the card)")
    print(f"cell          QR version {probe.version}, {n}x{n} modules, {block:.1f} mm block")
    print(f"grid          {rows} rows x {cols} cols = {rows * cols} parameter cells")
    print(f"swatches      {cols} solid {SWATCH} mm squares for depth/darkness measurement")
    print(f"cells encode  '{args.label} R<row>C<col>' — a scan identifies itself")
    print(f"wrote         {args.out.with_suffix('.svg')} + _preview.svg")


if __name__ == "__main__":
    main()
