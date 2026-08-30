#!/usr/bin/env python3
"""selftest.py — adversarial checks on the CVQR/1 implementation."""
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from cvqr import (MODES, Capsule, CVQRError, b45_decode, b45_encode, from_text,  # noqa: E402
                  pack_frames, to_text, unpack_frames)

ROOT = pathlib.Path(__file__).resolve().parent.parent
passed = failed = skipped = 0
images_read = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        print(f"  FAIL  {name}  {detail}")


def skip(name, why):
    """Not run, and saying so plainly.

    A check that could not run is not a check that passed, and it is not a
    check that failed either. Calling a missing toolchain a FAIL trains you to
    ignore red, which is the one habit this suite cannot afford.
    """
    global skipped
    skipped += 1
    print(f"  SKIP  {name}  {why}")


def refuses(name, fn, fragment):
    try:
        fn()
    except CVQRError as e:
        check(name, fragment.lower() in str(e).lower(), f"message was: {e}")
    except Exception as e:  # noqa: BLE001
        check(name, False, f"wrong exception type: {type(e).__name__}: {e}")
    else:
        check(name, False, "accepted a payload it should have refused")


print("\n[1] Base45 against RFC 9285 test vectors")
for plain, encoded in [(b"AB", "BB8"), (b"Hello!!", "%69 VD92EX0"),
                       (b"base-45", "UJCLQE7W581"), (b"ietf!", "QED8WEX0")]:
    check(f"encode {plain!r}", b45_encode(plain) == encoded, f"got {b45_encode(plain)!r}")
    check(f"decode {encoded!r}", b45_decode(encoded) == plain)

print("\n[2] Base45 rejects malformed input")
refuses("single trailing char", lambda: b45_decode("BB8B"), "single trailing")
refuses("out-of-alphabet char", lambda: b45_decode("BB!"), "alphabet")
refuses("group exceeds 16 bits", lambda: b45_decode(":::"), "16 bits")

print("\n[3] Bit-packing is lossless for every mode")
for mid, (name, bits, balign, _) in MODES.items():
    n = 37
    aligned = bytes((i * 7 + 3) & 0xFF for i in range(n * balign))
    # zero the pad bits that byte-alignment leaves, so equality is meaningful
    pad = balign * 8 - bits
    fixed = bytearray()
    for off in range(0, len(aligned), balign):
        v = int.from_bytes(aligned[off:off + balign], "big") >> pad << pad
        fixed += v.to_bytes(balign, "big")
    fixed = bytes(fixed)
    packed = pack_frames(fixed, bits, balign)
    expect_len = -(-n * bits // 8)
    check(f"{name}: packed length", len(packed) == expect_len, f"{len(packed)} != {expect_len}")
    check(f"{name}: unpack restores frames", unpack_frames(packed, n, bits, balign) == fixed)

print("\n[4] Capsule round-trips byte-for-byte")
cap = Capsule(mode_id=0x03, duration_ms=1876, frame_count=46,
              payload=bytes((i * 31 + 7) & 0xFF for i in range(299)))
blob = cap.serialize()
back = Capsule.parse(blob)
check("serialize/parse identity", back.serialize() == blob)
check("payload preserved", back.payload == cap.payload)
check("text round trip", from_text(to_text(cap)).serialize() == blob)

print("\n[5] CRC-32 catches corruption")
detected = 0
for byte_i in range(len(blob)):
    if 20 <= byte_i < 24:
        continue  # the CRC field itself
    for bit in range(8):
        bad = bytearray(blob)
        bad[byte_i] ^= 1 << bit
        try:
            Capsule.parse(bytes(bad))
        except CVQRError:
            detected += 1
        else:
            pass
total_flips = (len(blob) - 4) * 8
check(f"all {total_flips} single-bit flips refused", detected == total_flips,
      f"{total_flips - detected} slipped through")

print("\n[6] Malformed capsules are refused with a readable reason")
refuses("bad magic", lambda: Capsule.parse(b"XXXX" + blob[4:]), "magic")
refuses("future version", lambda: Capsule.parse(blob[:4] + b"\x02" + blob[5:]), "version")
refuses("unknown codec", lambda: Capsule.parse(blob[:5] + b"\x99" + blob[6:]), "codec")
refuses("unknown mode", lambda: Capsule.parse(blob[:6] + b"\x99" + blob[7:]), "mode")
refuses("truncated header", lambda: Capsule.parse(blob[:10]), "truncated")
refuses("payload short", lambda: Capsule.parse(blob[:-5]), "payload")
refuses("missing prefix", lambda: from_text("HELLO WORLD"), "prefix")
refuses("prefix but junk", lambda: from_text("CVQR1:BB8"), "")

print("\n[7] End-to-end: a QR image recovers its exact payload")
# The example is committed, so this section actually runs in a fresh clone.
# The stand-ins are part of the private artifact and skip when absent.
CASES = [(f"hello {m}", ROOT / f"examples/hello_{m}.txt", ROOT / f"examples/hello_{m}_Q.png")
         for m in ("1300", "3200")]
for m in ("700C", "1300"):
    CASES.append((f"stand-in {m}", ROOT / f"audio/encoded/standin_{m}.txt",
                  ROOT / f"qr/standin_{m}_Q.png"))

for mode, src, png in CASES:
    if not (src.exists() and png.exists()):
        # A clone of this repository carries the format, the tools and the
        # decoder, but not the private artifact these fixtures came from.
        skip(f"{mode}: QR image -> exact payload",
             "fixtures absent; run encode_voice.py + make_qr.py to create them")
        continue
    r = subprocess.run([sys.executable, str(ROOT / "tools/read_qr.py"), str(png),
                        "--expect", str(src)], capture_output=True, text=True)
    if "no QR decoder is installed" in r.stdout + r.stderr:
        skip(f"{mode}: QR image -> exact payload", "no QR engine installed")
    else:
        images_read += 1
        check(f"{mode}: QR image -> exact payload", "EXACT MATCH" in r.stdout, r.stdout + r.stderr)

summary = f"\n{passed} passed, {failed} failed"
if skipped:
    summary += f", {skipped} SKIPPED"
print(summary)
if not images_read:
    # Distinct from "some fixtures were missing": here nothing read an image at
    # all, so this run says nothing whatever about whether a code scans.
    print("\nNo image was read. Install zxing-cpp and pyzbar before trusting this\n"
          "run to say anything about whether a code scans.")
elif skipped:
    print(f"\n{images_read} image check(s) ran; the skips above are fixtures this\n"
          "clone does not carry, which is expected outside the private working copy.")
sys.exit(1 if failed else 0)
