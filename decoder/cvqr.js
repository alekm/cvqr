/*
 * cvqr.js — CVQR/1 reader. Mirrors tools/cvqr.py exactly; FORMAT.md is normative.
 * No dependencies, no network, no state.
 */
'use strict';

const CVQR = (() => {
  const MAGIC = [0x43, 0x56, 0x51, 0x52];      // "CVQR"
  const VERSION = 1;
  const PREFIX = 'CVQR1:';
  const HEADER_LEN = 24;

  // id -> [name, bitsPerFrame, bytesPerFrameAligned, frameMs, codec2ModeId]
  const MODES = {
    0x01: ['700C', 28, 4, 40, 8],
    0x02: ['1200', 48, 6, 40, 5],
    0x03: ['1300', 52, 7, 40, 4],
    0x04: ['1400', 56, 7, 40, 3],
    0x05: ['1600', 64, 8, 40, 2],
    0x06: ['2400', 48, 6, 20, 1],
    0x07: ['3200', 64, 8, 20, 0],
  };

  class CVQRError extends Error {}

  const B45 = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ $%*+-./:';
  const B45_VAL = new Map([...B45].map((c, i) => [c, i]));

  function b45Decode(text) {
    const vals = [];
    for (const ch of text) {
      const v = B45_VAL.get(ch);
      if (v === undefined) {
        throw new CVQRError(`Not valid Base45: the character "${ch}" is not in the alphabet.`);
      }
      vals.push(v);
    }
    if (vals.length % 3 === 1) {
      throw new CVQRError('Not valid Base45: the length leaves a single trailing character.');
    }
    const out = [];
    let i = 0;
    for (; i + 2 < vals.length; i += 3) {
      const n = vals[i] + vals[i + 1] * 45 + vals[i + 2] * 2025;
      if (n > 0xffff) throw new CVQRError('Not valid Base45: a 3-character group exceeds 16 bits.');
      out.push((n >> 8) & 0xff, n & 0xff);
    }
    if (vals.length % 3 === 2) {
      const n = vals[vals.length - 2] + vals[vals.length - 1] * 45;
      if (n > 0xff) throw new CVQRError('Not valid Base45: the final group exceeds 8 bits.');
      out.push(n);
    }
    return new Uint8Array(out);
  }

  // CRC-32/ISO-HDLC, the zlib/PNG/gzip one.
  const CRC_TABLE = (() => {
    const t = new Uint32Array(256);
    for (let n = 0; n < 256; n++) {
      let c = n;
      for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
      t[n] = c >>> 0;
    }
    return t;
  })();

  function crc32(bytes, skipFrom, skipTo) {
    let c = 0xffffffff;
    for (let i = 0; i < bytes.length; i++) {
      // bytes in [skipFrom, skipTo) are covered as zero — see FORMAT.md §5
      const b = i >= skipFrom && i < skipTo ? 0 : bytes[i];
      c = CRC_TABLE[(c ^ b) & 0xff] ^ (c >>> 8);
    }
    return (c ^ 0xffffffff) >>> 0;
  }

  function parseCapsule(blob) {
    if (blob.length < HEADER_LEN) {
      throw new CVQRError(`Truncated capsule: ${blob.length} bytes, need at least ${HEADER_LEN}.`);
    }
    const dv = new DataView(blob.buffer, blob.byteOffset, blob.byteLength);
    for (let i = 0; i < 4; i++) {
      if (blob[i] !== MAGIC[i]) {
        throw new CVQRError('Bad magic: this is not a CVQR capsule.');
      }
    }
    const version = blob[4], codecId = blob[5], modeId = blob[6], flags = blob[7];
    if (version !== VERSION) {
      throw new CVQRError(`Capsule declares version ${version}; this decoder implements 1.`);
    }
    if (codecId !== 0x01) {
      throw new CVQRError(`Unsupported codec id 0x${codecId.toString(16)}; only Codec2 (0x01) is defined.`);
    }
    if (!(modeId in MODES)) {
      throw new CVQRError(`Unsupported Codec2 mode id 0x${modeId.toString(16).padStart(2, '0')}.`);
    }
    const sampleRate = dv.getUint16(8);
    const channels = blob[10];
    const bitsPerSample = blob[11];
    const durationMs = dv.getUint32(12);
    const frameCount = dv.getUint16(16);
    const payloadLen = dv.getUint16(18);
    const crcClaimed = dv.getUint32(20);

    const payload = blob.subarray(HEADER_LEN);
    if (payload.length !== payloadLen) {
      throw new CVQRError(
        `Header declares a ${payloadLen}-byte payload but ${payload.length} bytes follow.`);
    }
    const crcActual = crc32(blob, 20, 24);
    if (crcActual !== crcClaimed) {
      throw new CVQRError(
        `Integrity check failed: CRC-32 is ${crcActual.toString(16).toUpperCase().padStart(8, '0')}, ` +
        `capsule claims ${crcClaimed.toString(16).toUpperCase().padStart(8, '0')}. The payload is damaged.`);
    }
    const [name, bits] = MODES[modeId];
    const need = Math.ceil((frameCount * bits) / 8);
    if (payloadLen !== need) {
      throw new CVQRError(
        `${frameCount} frames at ${bits} bits need ${need} bytes, but the payload is ${payloadLen}.`);
    }
    return { modeId, modeName: name, codecId, flags, sampleRate, channels,
             bitsPerSample, durationMs, frameCount, payload, crc: crcClaimed };
  }

  /* Contiguous MSB-first bitstream -> c2dec-compatible byte-aligned frames. */
  function unpackFrames(cap) {
    const [, bits, aligned] = MODES[cap.modeId];
    const out = new Uint8Array(cap.frameCount * aligned);
    let bitPos = 0;
    for (let f = 0; f < cap.frameCount; f++) {
      for (let b = 0; b < bits; b++, bitPos++) {
        const bit = (cap.payload[bitPos >> 3] >> (7 - (bitPos & 7))) & 1;
        if (bit) {
          const dst = f * aligned + (b >> 3);
          out[dst] |= 1 << (7 - (b & 7));
        }
      }
    }
    return out;
  }

  /*
   * SPACE IS A VALID BASE45 CHARACTER. Stripping whitespace to be tidy about
   * pasted text silently corrupts any payload that contains one — which is
   * most of them. So only line breaks and tabs are removed here, because
   * those cannot appear in the alphabet and do appear when a payload is
   * wrapped across lines.
   *
   * Edge spaces are genuinely ambiguous: they may be data, or they may be a
   * sloppy selection. Try the string as-is first, and only fall back to
   * trimming them if that fails — so real data always wins.
   */
  function fromText(text) {
    const cleaned = String(text).replace(/[\r\n\t]+/g, '');
    const attempt = (s) => {
      if (!s.toUpperCase().startsWith(PREFIX)) {
        const head = s.slice(0, 16) + (s.length > 16 ? '…' : '');
        throw new CVQRError(`Missing the CVQR1: prefix. This payload starts "${head}".`);
      }
      return parseCapsule(b45Decode(s.slice(PREFIX.length)));
    };
    try {
      return attempt(cleaned);
    } catch (first) {
      const trimmed = cleaned.trim();
      if (trimmed === cleaned) throw first;
      try { return attempt(trimmed); } catch { throw first; }
    }
  }

  return { MODES, PREFIX, CVQRError, b45Decode, crc32, parseCapsule, unpackFrames, fromText };
})();

if (typeof module !== 'undefined') module.exports = CVQR;
