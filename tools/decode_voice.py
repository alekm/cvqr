#!/usr/bin/env python3
"""
decode_voice.py — `CVQR1:` text (or a .cvqr capsule) -> validated -> WAV.

This is the low-tech recovery path. Given only FORMAT.md, a Codec2 build and
this file's logic, the recording comes back.

  ./decode_voice.py audio/encoded/take1.txt --out audio/decoded/take1.wav
  ./decode_voice.py --text "CVQR1:XXXX..." --out out.wav
"""
import argparse
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from cvqr import MODES, Capsule, CVQRError, from_text, unpack_frames  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("path", nargs="?", type=pathlib.Path, help=".txt payload or .cvqr capsule")
    src.add_argument("--text", help="payload as a literal string")
    ap.add_argument("--out", type=pathlib.Path, required=True, help="output .wav")
    args = ap.parse_args()

    try:
        if args.text is not None:
            cap = from_text(args.text)
        elif args.path.suffix == ".cvqr":
            cap = Capsule.parse(args.path.read_bytes())
        else:
            cap = from_text(args.path.read_text())
    except CVQRError as e:
        sys.exit(f"REFUSED: {e}")

    name, bits, balign, frame_ms = MODES[cap.mode_id]
    aligned = unpack_frames(cap.payload, cap.frame_count, bits, balign)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    tmp_c2 = args.out.with_suffix(".c2raw")
    tmp_raw = args.out.with_suffix(".raw")
    tmp_c2.write_bytes(aligned)

    for cmd in (["c2dec", name, str(tmp_c2), str(tmp_raw)],
                ["ffmpeg", "-y", "-loglevel", "error", "-f", "s16le", "-ar", "8000",
                 "-ac", "1", "-i", str(tmp_raw), str(args.out)]):
        p = subprocess.run(cmd, capture_output=True)
        if p.returncode != 0:
            sys.exit(f"command failed: {' '.join(cmd)}\n{p.stderr.decode(errors='replace')}")

    print("integrity     OK (CRC-32 verified)")
    print(f"codec         Codec2 {name}  ({bits} bits / {frame_ms} ms frame)")
    print(f"audio         {cap.sample_rate} Hz, {cap.channels} ch, {cap.bits_per_sample}-bit")
    print(f"duration      {cap.duration_ms} ms  ({cap.frame_count} frames)")
    print(f"wrote         {args.out}")


if __name__ == "__main__":
    main()
