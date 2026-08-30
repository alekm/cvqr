#!/usr/bin/env python3
"""
read_qr.py — scan a QR image file back to its text, then validate it as CVQR/1.

This is the bench proxy for "someone photographed the card". Tries two
independent decoder engines, and on failure retries with escalating image
rehabilitation (grayscale, upscale, contrast stretch, binarisation) so a
mediocre phone photo of a reflective metal card still has a chance.

  ./read_qr.py qr/take1.png
  ./read_qr.py photo.jpg --expect audio/encoded/take1.txt
"""
import argparse
import pathlib
import sys

import numpy as np
from PIL import Image, ImageOps

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from cvqr import CVQRError, from_text  # noqa: E402


def _load_engines():
    """Import the decoder engines once, at startup.

    Importing here rather than inside the read loop is the whole point: an
    absent library and an unreadable image must never produce the same
    result. When the image under test is a coupon cell, "this does not scan"
    IS the experimental result, and a missing engine that quietly reports the
    same thing would send you hunting for laser settings that were never
    wrong.
    """
    found = []
    try:
        import zxingcpp
        found.append(("zxing-cpp",
                      lambda im: [r.text for r in zxingcpp.read_barcodes(im)]))
    except ImportError:
        pass
    try:
        from pyzbar.pyzbar import decode as zbar_decode
        found.append(("zbar",
                      lambda im: [r.data.decode("utf-8", "replace") for r in zbar_decode(im)]))
    except ImportError:
        pass
    return found


ENGINES = _load_engines()

NO_ENGINES = """FAIL: no QR decoder is installed, so nothing was actually tested.

This is a toolchain problem, not a problem with the image. Install at least
one engine:

    pip install zxing-cpp     # preferred
    pip install pyzbar        # also needs the libzbar system library

Install both if you can. They disagree in the direction that matters: zbar is
scanline-based and strict about the 1:1:3:1:1 finder ratio, and it is what
cheap and embedded scanners are built on. A code that reads only on zxing-cpp
has not earned a pass."""


def engines(img):
    """Yield (engine_name, decoded_text) for every engine that reads `img`."""
    for name, read in ENGINES:
        try:
            for text in read(img):
                yield name, text
        except Exception:  # noqa: BLE001 - this engine choked; others may not
            continue


def variants(img):
    """Progressively more aggressive rehabilitation of a poor photo."""
    g = ImageOps.grayscale(img)
    yield "as-is", img
    yield "grayscale", g
    yield "autocontrast", ImageOps.autocontrast(g)
    for factor in (2, 3):
        yield f"upscale x{factor}", g.resize((g.width * factor, g.height * factor), Image.LANCZOS)
    a = np.asarray(ImageOps.autocontrast(g), dtype=np.uint8)
    yield "otsu", Image.fromarray(((a > _otsu(a)) * 255).astype(np.uint8))


def _otsu(a):
    hist = np.bincount(a.ravel(), minlength=256).astype(float)
    total = hist.sum()
    w = np.cumsum(hist)
    m = np.cumsum(hist * np.arange(256))
    with np.errstate(invalid="ignore", divide="ignore"):
        between = (m[-1] * w / total - m) ** 2 / (w * (total - w))
    return int(np.nanargmax(between))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image", type=pathlib.Path)
    ap.add_argument("--expect", type=pathlib.Path, help="file with the payload this should equal")
    ap.add_argument("--save-text", type=pathlib.Path, help="write the recovered text here")
    args = ap.parse_args()

    if not ENGINES:
        sys.exit(NO_ENGINES)
    if not any(n == "zbar" for n in (name for name, _ in ENGINES)):
        print("warning       zbar is not installed; only the lenient engine is "
              "checking this.", file=sys.stderr)

    img = Image.open(args.image)
    img.load()

    text = engine = how = None
    for how, candidate in variants(img):
        for engine, text in engines(candidate):
            if text:
                break
        else:
            text = None
            continue
        break

    tried = ", ".join(name for name, _ in ENGINES)
    if not text:
        sys.exit(f"FAIL: no QR code found in {args.image} after all rehabilitation "
                 f"attempts, using: {tried}.")

    print(f"engines       {tried}")
    print(f"read via      {engine}  (image preparation: {how})")
    print(f"recovered     {len(text)} characters")

    try:
        cap = from_text(text)
    except CVQRError as e:
        sys.exit(f"REFUSED: {e}")
    print(f"validated     CVQR/1, Codec2 {cap.mode_name}, {cap.duration_ms} ms, CRC-32 OK")

    if args.save_text:
        args.save_text.write_text(text + "\n")
        print(f"wrote         {args.save_text}")

    if args.expect:
        want = args.expect.read_text().strip()
        if want == text.strip():
            print("comparison    EXACT MATCH with the expected payload")
        else:
            sys.exit(f"MISMATCH: recovered text differs from {args.expect}")


if __name__ == "__main__":
    main()
