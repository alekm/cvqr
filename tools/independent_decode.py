#!/usr/bin/env python3
"""
independent_decode.py — a from-scratch CVQR/1 reader written ONLY from
FORMAT.md, importing nothing from this project.

Its whole purpose is to answer one question honestly: is FORMAT.md sufficient?
If this file ever needs to consult cvqr.py to work, the specification has a
hole and the hole must be closed in FORMAT.md, not here.

  ./independent_decode.py "CVQR1:..."      -> writes recovered.raw, prints metadata
"""
import struct
import sys
import zlib

ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ $%*+-./:"

# FORMAT.md section 3, transcribed by hand.
MODES = {0x01: ("700C", 28, 4, 40), 0x02: ("1200", 48, 6, 40),
         0x03: ("1300", 52, 7, 40), 0x04: ("1400", 56, 7, 40),
         0x05: ("1600", 64, 8, 40), 0x06: ("2400", 48, 6, 20),
         0x07: ("3200", 64, 8, 20)}


def main():
    text = sys.argv[1].strip() if len(sys.argv) > 1 else sys.stdin.read().strip()

    # FORMAT.md section 6
    assert text.upper().startswith("CVQR1:"), "missing prefix"
    body = text[6:]
    vals = [ALPHABET.index(c) for c in body]
    assert len(vals) % 3 != 1, "bad Base45 length"
    blob = bytearray()
    for i in range(0, len(vals) - 2, 3):
        blob += struct.pack(">H", vals[i] + vals[i + 1] * 45 + vals[i + 2] * 2025)
    if len(vals) % 3 == 2:
        blob.append(vals[-2] + vals[-1] * 45)
    blob = bytes(blob)

    # FORMAT.md section 5
    magic, ver, codec, mode, flags, rate, ch, bps, dur, nfr, plen, crc = \
        struct.unpack(">4sBBBBHBBIHHI", blob[:24])
    assert magic == b"CVQR" and ver == 1 and codec == 1, "not a CVQR/1 capsule"
    assert mode in MODES, f"unknown mode 0x{mode:02X}"
    payload = blob[24:]
    assert len(payload) == plen, "payload length mismatch"
    assert zlib.crc32(blob[:20] + b"\0\0\0\0" + blob[24:]) & 0xFFFFFFFF == crc, "CRC mismatch"

    name, bits, balign, frame_ms = MODES[mode]
    assert plen == -(-nfr * bits // 8), "frame count / payload length disagree"

    # FORMAT.md section 4
    stream = int.from_bytes(payload, "big") >> (len(payload) * 8 - nfr * bits)
    out = bytearray()
    for i in range(nfr - 1, -1, -1):
        frame = (stream >> (i * bits)) & ((1 << bits) - 1)
        out += (frame << (balign * 8 - bits)).to_bytes(balign, "big")

    open("recovered.c2raw", "wb").write(bytes(out))
    print(f"Codec2 {name}, {nfr} frames x {frame_ms} ms = {dur} ms, "
          f"{rate} Hz {ch}ch {bps}-bit, CRC OK")
    print(f"wrote recovered.c2raw ({len(out)} bytes) -> c2dec {name} recovered.c2raw out.raw")


if __name__ == "__main__":
    main()
