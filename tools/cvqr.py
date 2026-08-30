"""
cvqr.py — reference implementation of the CVQR/1 container.

CVQR/1 is a self-describing binary capsule carrying Codec2-compressed mono
speech, wrapped in Base45 (RFC 9285) and prefixed with the ASCII tag `CVQR1:`
so it can live inside an ordinary QR code in alphanumeric mode.

This module has NO third-party dependencies. It is deliberately written to be
readable as a specification in its own right: see FORMAT.md for the normative
description.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass

MAGIC = b"CVQR"
VERSION = 1
PREFIX = "CVQR1:"
HEADER_LEN = 24

# ---------------------------------------------------------------------------
# Codec2 mode registry
# ---------------------------------------------------------------------------
# id -> (name, bits_per_frame, bytes_per_frame_as_written_by_c2enc, frame_ms)
#
# `bytes_per_frame` is how the reference `c2enc` tool byte-aligns each frame on
# disk. CVQR/1 does NOT store that padding: frames are packed contiguously,
# MSB-first (see pack_frames/unpack_frames). At 1300 bit/s this saves ~7% of
# the payload, which is worth a whole QR version.

MODES = {
    0x01: ("700C", 28, 4, 40),
    0x02: ("1200", 48, 6, 40),
    0x03: ("1300", 52, 7, 40),
    0x04: ("1400", 56, 7, 40),
    0x05: ("1600", 64, 8, 40),
    0x06: ("2400", 48, 6, 20),
    0x07: ("3200", 64, 8, 20),
}
MODES_BY_NAME = {v[0]: k for k, v in MODES.items()}

CODEC_CODEC2 = 0x01


class CVQRError(ValueError):
    """Raised for any malformed or unsupported CVQR payload.

    The message is intended to be shown directly to a human.
    """


# ---------------------------------------------------------------------------
# Base45 (RFC 9285)
# ---------------------------------------------------------------------------

B45_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ $%*+-./:"
B45_VALUES = {c: i for i, c in enumerate(B45_ALPHABET)}


def b45_encode(data: bytes) -> str:
    out = []
    for i in range(0, len(data) - 1, 2):
        n = (data[i] << 8) | data[i + 1]
        n, c = divmod(n, 45)
        e, d = divmod(n, 45)
        out.append(B45_ALPHABET[c] + B45_ALPHABET[d] + B45_ALPHABET[e])
    if len(data) % 2:
        d, c = divmod(data[-1], 45)
        out.append(B45_ALPHABET[c] + B45_ALPHABET[d])
    return "".join(out)


def b45_decode(text: str) -> bytes:
    try:
        vals = [B45_VALUES[c] for c in text]
    except KeyError as exc:
        raise CVQRError(f"Not valid Base45: character {exc.args[0]!r} is not in the alphabet.") from None
    if len(vals) % 3 == 1:
        raise CVQRError("Not valid Base45: length leaves a single trailing character.")
    out = bytearray()
    for i in range(0, len(vals) - 2, 3):
        n = vals[i] + vals[i + 1] * 45 + vals[i + 2] * 45 * 45
        if n > 0xFFFF:
            raise CVQRError("Not valid Base45: a 3-character group exceeds 16 bits.")
        out += struct.pack(">H", n)
    if len(vals) % 3 == 2:
        n = vals[-2] + vals[-1] * 45
        if n > 0xFF:
            raise CVQRError("Not valid Base45: the final 2-character group exceeds 8 bits.")
        out.append(n)
    return bytes(out)


# ---------------------------------------------------------------------------
# Frame bit-packing
# ---------------------------------------------------------------------------

def pack_frames(raw: bytes, bits_per_frame: int, bytes_per_frame: int) -> bytes:
    """c2enc's byte-aligned frames -> contiguous MSB-first bitstream."""
    if len(raw) % bytes_per_frame:
        raise CVQRError(
            f"Codec2 file is {len(raw)} bytes, not a whole number of "
            f"{bytes_per_frame}-byte frames."
        )
    acc = 0
    nbits = 0
    out = bytearray()
    for off in range(0, len(raw), bytes_per_frame):
        frame = int.from_bytes(raw[off:off + bytes_per_frame], "big")
        # Frame occupies the TOP bits_per_frame bits of the aligned group.
        frame >>= (bytes_per_frame * 8 - bits_per_frame)
        acc = (acc << bits_per_frame) | frame
        nbits += bits_per_frame
        while nbits >= 8:
            nbits -= 8
            out.append((acc >> nbits) & 0xFF)
            acc &= (1 << nbits) - 1
    if nbits:
        out.append((acc << (8 - nbits)) & 0xFF)
    return bytes(out)


def unpack_frames(packed: bytes, n_frames: int, bits_per_frame: int, bytes_per_frame: int) -> bytes:
    """Contiguous MSB-first bitstream -> c2dec's byte-aligned frames."""
    need_bits = n_frames * bits_per_frame
    if len(packed) * 8 < need_bits:
        raise CVQRError(
            f"Payload holds {len(packed) * 8} bits but {n_frames} frames need {need_bits}."
        )
    total = int.from_bytes(packed, "big")
    total >>= (len(packed) * 8 - need_bits)  # drop trailing pad bits
    out = bytearray()
    for i in range(n_frames - 1, -1, -1):
        frame = (total >> (i * bits_per_frame)) & ((1 << bits_per_frame) - 1)
        frame <<= (bytes_per_frame * 8 - bits_per_frame)
        out += frame.to_bytes(bytes_per_frame, "big")
    return bytes(out)


# ---------------------------------------------------------------------------
# Capsule
# ---------------------------------------------------------------------------

@dataclass
class Capsule:
    mode_id: int
    duration_ms: int
    frame_count: int
    payload: bytes          # contiguously bit-packed Codec2 frames
    codec_id: int = CODEC_CODEC2
    flags: int = 0
    sample_rate: int = 8000
    channels: int = 1
    bits_per_sample: int = 16

    @property
    def mode_name(self) -> str:
        return MODES[self.mode_id][0]

    def serialize(self) -> bytes:
        if self.mode_id not in MODES:
            raise CVQRError(f"Unknown Codec2 mode id 0x{self.mode_id:02X}.")
        for name, val, limit in (
            ("duration_ms", self.duration_ms, 0xFFFFFFFF),
            ("frame_count", self.frame_count, 0xFFFF),
            ("payload length", len(self.payload), 0xFFFF),
            ("sample_rate", self.sample_rate, 0xFFFF),
        ):
            if not 0 <= val <= limit:
                raise CVQRError(f"{name} = {val} does not fit its field.")
        head = struct.pack(
            ">4sBBBBHBBIHHI",
            MAGIC, VERSION, self.codec_id, self.mode_id, self.flags,
            self.sample_rate, self.channels, self.bits_per_sample,
            self.duration_ms, self.frame_count, len(self.payload), 0,
        )
        assert len(head) == HEADER_LEN, len(head)
        blob = head + self.payload
        crc = zlib.crc32(blob) & 0xFFFFFFFF
        return blob[:20] + struct.pack(">I", crc) + blob[24:]

    @classmethod
    def parse(cls, blob: bytes) -> "Capsule":
        if len(blob) < HEADER_LEN:
            raise CVQRError(f"Truncated capsule: {len(blob)} bytes, need at least {HEADER_LEN}.")
        (magic, version, codec_id, mode_id, flags, sample_rate,
         channels, bits_per_sample, duration_ms, frame_count,
         payload_len, crc) = struct.unpack(">4sBBBBHBBIHHI", blob[:HEADER_LEN])

        if magic != MAGIC:
            raise CVQRError(f"Bad magic {magic!r}: this is not a CVQR capsule.")
        if version != VERSION:
            raise CVQRError(f"Capsule declares version {version}; this decoder implements 1.")
        if codec_id != CODEC_CODEC2:
            raise CVQRError(f"Unsupported codec id 0x{codec_id:02X}; only Codec2 (0x01) is defined.")
        if mode_id not in MODES:
            raise CVQRError(f"Unsupported Codec2 mode id 0x{mode_id:02X}.")

        payload = blob[HEADER_LEN:]
        if len(payload) != payload_len:
            raise CVQRError(
                f"Header declares a {payload_len}-byte payload but {len(payload)} bytes follow."
            )

        zeroed = blob[:20] + b"\x00\x00\x00\x00" + blob[24:]
        actual = zlib.crc32(zeroed) & 0xFFFFFFFF
        if actual != crc:
            raise CVQRError(
                f"Integrity check failed: CRC-32 is {actual:08X}, capsule claims {crc:08X}. "
                "The payload is damaged."
            )

        bits_per_frame = MODES[mode_id][1]
        need = -(-frame_count * bits_per_frame // 8)
        if payload_len != need:
            raise CVQRError(
                f"{frame_count} frames at {bits_per_frame} bits need {need} bytes, "
                f"but the payload is {payload_len}."
            )
        return cls(mode_id=mode_id, duration_ms=duration_ms, frame_count=frame_count,
                   payload=payload, codec_id=codec_id, flags=flags,
                   sample_rate=sample_rate, channels=channels,
                   bits_per_sample=bits_per_sample)


# ---------------------------------------------------------------------------
# Text wrapping
# ---------------------------------------------------------------------------

def to_text(capsule: Capsule) -> str:
    return PREFIX + b45_encode(capsule.serialize())


def from_text(text: str) -> Capsule:
    """Parse `CVQR1:`-prefixed text.

    SPACE IS A VALID BASE45 CHARACTER, so whitespace cannot simply be stripped
    — doing so silently corrupts most payloads. Only line breaks and tabs are
    removed (they can never appear in the alphabet, and do appear when a
    payload is wrapped). Edge spaces are ambiguous, so the string is tried
    as-is first and only trimmed as a fallback: real data always wins.
    """
    cleaned = text.replace("\r", "").replace("\n", "").replace("\t", "")

    def attempt(s: str) -> Capsule:
        if not s.upper().startswith(PREFIX):
            head = s[:16] + ("..." if len(s) > 16 else "")
            raise CVQRError(f"Missing the CVQR1: prefix. This payload starts {head!r}.")
        return Capsule.parse(b45_decode(s[len(PREFIX):]))

    try:
        return attempt(cleaned)
    except CVQRError:
        trimmed = cleaned.strip()
        if trimmed == cleaned:
            raise
        return attempt(trimmed)
