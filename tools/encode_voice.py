#!/usr/bin/env python3
"""
encode_voice.py — WAV -> mono 8 kHz -> Codec2 -> CVQR/1 capsule -> `CVQR1:` text.

The input file is never modified. Intermediates are written next to the output
so every step of the archive is reproducible and inspectable.

  ./encode_voice.py audio/source/master.wav --mode 1300 --out audio/encoded/take1
"""
import argparse
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from cvqr import MODES, MODES_BY_NAME, Capsule, pack_frames, to_text  # noqa: E402


def run(cmd):
    p = subprocess.run(cmd, capture_output=True)
    if p.returncode != 0:
        sys.exit(f"command failed: {' '.join(map(str, cmd))}\n{p.stderr.decode(errors='replace')}")
    return p


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("wav", type=pathlib.Path, help="source recording (any format ffmpeg reads)")
    ap.add_argument("--mode", default="1300", choices=sorted(MODES_BY_NAME), help="Codec2 mode")
    ap.add_argument("--out", type=pathlib.Path, required=True, help="output basename, no extension")
    ap.add_argument("--start", type=float, default=None, help="trim start, seconds")
    ap.add_argument("--end", type=float, default=None, help="trim end, seconds")
    ap.add_argument("--gain", type=float, default=None, help="gain in dB applied before encoding")
    args = ap.parse_args()

    if not args.wav.is_file():
        sys.exit(f"no such file: {args.wav}")
    args.out.parent.mkdir(parents=True, exist_ok=True)

    mode_id = MODES_BY_NAME[args.mode]
    name, bits, balign, frame_ms = MODES[mode_id]

    # 1. Normalise to the one representation Codec2 accepts: 8 kHz mono s16le.
    raw = args.out.with_suffix(".raw")
    filt = []
    if args.gain is not None:
        filt.append(f"volume={args.gain}dB")
    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    if args.start is not None:
        cmd += ["-ss", str(args.start)]
    cmd += ["-i", str(args.wav)]
    if args.end is not None:
        cmd += ["-to", str(args.end - (args.start or 0))]
    if filt:
        cmd += ["-af", ",".join(filt)]
    cmd += ["-ac", "1", "-ar", "8000", "-f", "s16le", "-acodec", "pcm_s16le", str(raw)]
    run(cmd)

    n_samples = raw.stat().st_size // 2
    duration_ms = round(n_samples * 1000 / 8000)

    # 2. Codec2 encode. c2enc byte-aligns each frame; we strip that padding.
    c2 = args.out.with_suffix(".c2raw")
    run(["c2enc", name, str(raw), str(c2)])
    aligned = c2.read_bytes()
    frame_count = len(aligned) // balign
    payload = pack_frames(aligned, bits, balign)

    # 3. Capsule + Base45 + prefix.
    cap = Capsule(mode_id=mode_id, duration_ms=duration_ms,
                  frame_count=frame_count, payload=payload)
    blob = cap.serialize()
    text = to_text(cap)

    args.out.with_suffix(".cvqr").write_bytes(blob)
    args.out.with_suffix(".txt").write_text(text + "\n")

    saved = len(aligned) - len(payload)
    print(f"source        {args.wav}")
    print(f"mode          Codec2 {name}  ({bits} bits / {frame_ms} ms frame)")
    print(f"duration      {duration_ms} ms  ({frame_count} frames)")
    print(f"codec bytes   {len(payload)}  (bit-packed; {len(aligned)} byte-aligned, saved {saved})")
    print(f"capsule       {len(blob)} bytes")
    print(f"QR text       {len(text)} characters")
    print(f"wrote         {args.out.with_suffix('.txt')}")


if __name__ == "__main__":
    main()
