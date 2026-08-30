#!/usr/bin/env python3
"""
make_qr.py — `CVQR1:` text -> plain square-module QR as SVG + high-res PNG,
with the physical module pitch reported for candidate engraved sizes.

No styling, no logo, no rounded modules, 4-module quiet zone, alphanumeric
mode (Base45's alphabet is exactly the QR alphanumeric set, so this is always
available and always the efficient encoding).

  ./make_qr.py audio/encoded/take1.txt --ecc Q --out qr/take1
"""
import argparse
import pathlib
import sys

import segno

SIZES_MM = (30, 35, 40, 45, 50)
# Practical floor for a phone camera reading a laser mark on stainless.
COMFORTABLE_PITCH_MM = 0.50
MARGINAL_PITCH_MM = 0.40


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("path", nargs="?", type=pathlib.Path, help="file holding the CVQR1: text")
    src.add_argument("--text", help="payload as a literal string")
    ap.add_argument("--ecc", default="Q", choices=list("LMQH"), help="error correction level")
    ap.add_argument("--out", type=pathlib.Path, required=True, help="output basename, no extension")
    ap.add_argument("--png-scale", type=int, default=20, help="PNG pixels per module")
    args = ap.parse_args()

    text = (args.text if args.text is not None else args.path.read_text()).strip()
    if not text.upper().startswith("CVQR1:"):
        print("warning: payload does not start with CVQR1:", file=sys.stderr)

    qr = segno.make(text, error=args.ecc, mode="alphanumeric", boost_error=False)
    modules = qr.symbol_size(border=0)[0]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    svg = args.out.with_suffix(".svg")
    png = args.out.with_suffix(".png")
    qr.save(str(svg), border=4, scale=10, dark="#000000", light="#ffffff")
    qr.save(str(png), border=4, scale=args.png_scale, dark="#000000", light="#ffffff")

    print(f"payload       {len(text)} characters")
    print(f"symbol        QR version {qr.version}, ECC {args.ecc}, {modules}x{modules} modules")
    print(f"quiet zone    4 modules on all sides (total {modules + 8} modules across)")
    print(f"wrote         {svg}  {png}")
    print()
    print("  physical size   module pitch   verdict")
    for mm in SIZES_MM:
        pitch = mm / modules
        verdict = ("comfortable" if pitch >= COMFORTABLE_PITCH_MM
                   else "marginal" if pitch >= MARGINAL_PITCH_MM
                   else "TOO DENSE for engraved metal")
        print(f"  {mm:>10} mm   {pitch:>9.3f} mm   {verdict}")
    print()
    print("  Pitch is the code area only. Add 8 more modules of quiet zone:")
    for mm in SIZES_MM:
        print(f"  {mm} mm code -> {mm * (modules + 8) / modules:.1f} mm of clear card needed")


if __name__ == "__main__":
    main()
