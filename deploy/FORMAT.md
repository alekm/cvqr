# CVQR/1 — a self-contained voice capsule for QR codes

**Status:** version 1, frozen.
**Purpose:** carry a few seconds of recognisable human speech inside an
ordinary QR code, with no server, no network, no account, and no dependency on
any service that must still exist when the code is read.

This document is normative. It is written so that someone with no access to
this repository — only a photograph of the QR code and this page — can
reconstruct the audio. If you are that person, skip to
[§8 Recovery from scratch](#8-recovery-from-scratch).

---

## 1. Layer cake

```
speech (any format)
  -> 8000 Hz, mono, signed 16-bit little-endian PCM
  -> Codec2 encode                       (§3)
  -> contiguous MSB-first frame packing  (§4)
  -> CVQR/1 binary capsule               (§5)
  -> Base45, RFC 9285                    (§6)
  -> ASCII prefix "CVQR1:"               (§6)
  -> QR Code, alphanumeric mode          (§7)
  -> laser mark / print / paste anywhere
```

Every layer is either an open published standard (Codec2, RFC 9285, ISO/IEC
18004) or fully specified on this page.

## 2. Why these choices

**Codec2** is the only widely-available open codec that produces intelligible
speech at ~1 kbit/s. Nothing else fits seconds of voice into a QR code.

**Base45** rather than Base64: its 45-character alphabet is exactly the QR
alphanumeric character set, so the QR encoder can use alphanumeric mode
(5.5 bits/char) rather than byte mode (8 bits/char). Base45 expands the data
by 1.5×, but alphanumeric mode packs it back down, and the result beats raw
byte mode while remaining copy-pasteable text. Storing raw binary in a QR is
possible but interoperates badly: scanners hand back mojibake, and the payload
cannot survive being written down, emailed, or read aloud.

**The `CVQR1:` prefix** means a generic phone scanner shows a human a visible,
selectable string beginning with a searchable identifier, rather than silently
failing or offering to open a URL. It is the difference between "this is
broken" and "this is something, let me look it up."

**CRC-32, not a hash.** The threat here is accidental corruption — a
misdecoded module, a smudge — not forgery. CRC-32 costs 4 bytes and detects
every single-bit error. Archive-copy integrity is a different job, handled by
SHA-256 in a sidecar manifest where bytes are free.

## 3. Codec2 modes

| Mode ID | Codec2 mode | Bits/frame | Frame (ms) | Bytes/frame as written by `c2enc` |
|---:|---|---:|---:|---:|
| `0x01` | 700C | 28 | 40 | 4 |
| `0x02` | 1200 | 48 | 40 | 6 |
| `0x03` | 1300 | 52 | 40 | 7 |
| `0x04` | 1400 | 56 | 40 | 7 |
| `0x05` | 1600 | 64 | 40 | 8 |
| `0x06` | 2400 | 48 | 20 | 6 |
| `0x07` | 3200 | 64 | 20 | 8 |

Audio is always 8000 Hz, mono, 16-bit after decoding. A CVQR/1 capsule
contains exactly one mode; modes are never mixed within a capsule.

> These IDs are a plain registry, deliberately not derived from the bitrate.
> An encoding like "0x0D means 1300" looks tidy until 700C arrives and has no
> number.

## 4. Frame packing

`c2enc` pads every frame up to a whole number of bytes. CVQR/1 does not store
that padding.

Frames are concatenated as a single bitstream, most-significant bit first,
each frame contributing exactly its `bits/frame` from the table above. The
final byte is zero-padded to a byte boundary. Payload length in bytes is
therefore:

```
payload_len = ceil(frame_count * bits_per_frame / 8)
```

To recover `c2dec`-compatible input, read `bits_per_frame` bits per frame from
the stream and left-align each into a `bytes_per_frame` group, zero-filling
the low bits.

At 1300 bit/s this saves 7% of the payload — which, at these sizes, is worth
a whole QR version, which is worth about 0.05 mm of module pitch on the card.
That is why the complication is justified.

## 5. The capsule

All multi-byte integers are **big-endian**. The header is exactly 24 bytes.

| Offset | Bytes | Field | Value |
|---:|---:|---|---|
| 0 | 4 | Magic | ASCII `CVQR` = `43 56 51 52` |
| 4 | 1 | Version | `0x01` |
| 5 | 1 | Codec ID | `0x01` = Codec2. No other value defined. |
| 6 | 1 | Codec mode ID | From §3 |
| 7 | 1 | Flags | `0x00`. Reserved; a v1 decoder must refuse nothing on this field but must not interpret it. |
| 8 | 2 | Sample rate | `8000` = `0x1F40` |
| 10 | 1 | Channels | `0x01` |
| 11 | 1 | Bits per sample after decode | `0x10` = 16 |
| 12 | 4 | Duration | Milliseconds of the trimmed source |
| 16 | 2 | Frame count | Number of Codec2 frames |
| 18 | 2 | Payload length | Bytes following the header |
| 20 | 4 | CRC-32 | See below |
| 24 | N | Payload | Packed Codec2 frames (§4) |

### CRC-32

Algorithm: CRC-32/ISO-HDLC — the one in zlib, PNG, and gzip. Polynomial
`0x04C11DB7` reflected (`0xEDB88320`), initial value `0xFFFFFFFF`, input and
output reflected, final XOR `0xFFFFFFFF`.

**Coverage: the entire capsule, header and payload together, with the four
CRC bytes at offset 20 replaced by `00 00 00 00`.** Computing it over a
discontiguous range is a classic source of incompatible reimplementations;
zeroing the field keeps the covered range simple and contiguous.

### A decoder must refuse

- magic ≠ `CVQR`
- version ≠ 1
- codec ID ≠ `0x01`
- a mode ID not in §3
- fewer than 24 bytes total
- payload length ≠ the actual bytes following the header
- CRC mismatch
- `payload_len ≠ ceil(frame_count * bits_per_frame / 8)`

Refusal must be visible and must not produce audio. Playing a corrupted
capsule as noise is worse than saying no.

## 6. Text wrapping

Base45 per **RFC 9285**, alphabet:

```
0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ $%*+-./:
```

Each 2 input bytes become 3 characters (little-endian base-45 digits: `c + d*45
+ e*45²` where the value is `b0*256 + b1`). A trailing odd byte becomes 2
characters. A Base45 string whose length mod 3 is 1 is invalid.

The final payload is the ASCII string `CVQR1:` followed by the Base45 text,
with no whitespace. Decoders should accept surrounding whitespace and a
case-insensitive prefix, because humans will retype this.

## 7. QR encoding

- Standard QR Code (ISO/IEC 18004), **alphanumeric mode**.
- Square modules only. No rounded modules, no gradient, no logo, no colour.
- Quiet zone: **at least 4 modules on every side**, containing nothing —
  no border rule, no registration mark, no text.
- Error correction level is a physical decision, not a format one. See the
  note below.

### Choosing error correction for engraved metal

Higher error correction is the instinctive choice for something permanent, and
it is usually the wrong one here. Raising ECC from Q to H adds redundancy, but
it also grows the symbol — which, at a fixed physical size, *shrinks every
module*. On a laser-marked metal card the dominant failure is not damaged
modules, it is a phone camera failing to resolve modules at all under glare and
at an angle. Redundancy cannot recover data the sensor never captured; larger
modules can.

Spend the capacity budget on module size. Prefer Q, consider M, and reach for
H only if the physical size is generous enough that the pitch stays above
~0.5 mm.

## 8. Recovery from scratch

You have a photograph of a QR code and this page. In order:

1. Scan the QR with any scanner. You get text starting `CVQR1:`.
   (Any generic phone scanner will show it; nothing special is required.)
2. Strip the `CVQR1:` prefix.
3. Base45-decode the rest per RFC 9285 → binary capsule.
4. Parse the 24-byte header per §5. Verify the CRC.
5. Look up the mode ID in §3 to get bits-per-frame and frame duration.
6. Unpack the bitstream per §4 into byte-aligned Codec2 frames.
7. Decode with any Codec2 implementation at that mode
   (`c2dec 1300 in.c2raw out.raw`) → 8 kHz mono 16-bit little-endian PCM.
8. Add a WAV header, or play the raw PCM directly.

Codec2 is by David Rowe, LGPL-2.1, at `github.com/drowe67/codec2`. If that
repository is gone, the codec is described in published papers and the
algorithm is not secret. Steps 1–6 need nothing but this page.

## 9. Canonical test vector

A synthetic capsule: Codec2 mode 1300 (`0x03`), 3 frames, 120 ms, payload
bytes defined by `byte[i] = (i * 17 + 5) mod 256` for `i` = 0..19.

```
0000  43 56 51 52 01 01 03 00 1F 40 01 10 00 00 00 78
0010  00 03 00 14 8F 2A B6 CC 05 16 27 38 49 5A 6B 7C
0020  8D 9E AF C0 D1 E2 F3 04 15 26 37 48
```

44 bytes. CRC-32 field = `8F2AB6CC`. Text form:

```
CVQR1:3N8SCAW503H0Z.3260000U20300K00K4I-4N.S05/4DC9LQDT+H$9M0OQMWUEU2M:6
```

An implementation that produces this capsule from those inputs, and this text
from that capsule, is compatible. Copies live at `test-vectors/vector1.cvqr`,
`.hex`, and `.txt`.

## 10. What this format does not do

It does not encrypt. Anyone holding the card and a decoder can hear the
recording. This is a sentimental object, not a secret. If a future version
needs privacy, it must be a new, explicitly incompatible version with its own
magic or version byte — never a hidden behaviour change inside CVQR/1, which
would silently break every existing card.

It does not claim permanence. It claims to be *self-contained*: the recovery
path depends on published standards and this document, not on any running
service. That is a real property, and it is the only one worth promising.
