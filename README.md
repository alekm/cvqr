# CVQR/1

A short voice recording carried inside an ordinary QR code — no server, no
network, no account, and no dependency on any service that has to still exist
when the code is read.

```
speech -> 8 kHz mono PCM -> Codec2 -> bit-packed capsule -> Base45 -> QR
```

Every layer is either an open published standard (Codec2, RFC 9285 Base45,
ISO/IEC 18004) or fully specified in [`FORMAT.md`](FORMAT.md), which is
normative. Someone with a photograph of a code and that one page can reconstruct
the audio, using nothing from this repository. That is the only property the
format promises, and it is the one worth promising.

The format does not encrypt. Anyone holding the code and a decoder can hear the
recording.

## The decoder

`deploy/index.html` is a single self-contained file — the Codec2 WASM, the QR
reader and the app all inlined. It runs offline, uploads nothing, and keeps no
state that outlives the tab. `decoder/` is the editable source; rebuild with:

```
python3 tools/bundle_decoder.py --out release/cvqr-decoder.html
cp release/cvqr-decoder.html deploy/index.html
```

Cloudflare Pages serves `deploy/` straight from this repository:

| Setting | Value |
|---|---|
| Build command | *(none)* |
| Build output directory | `deploy` |
| Root directory | `/` |

There is no build step on Cloudflare's side, so a decoder change must be rebuilt
and committed. See [`deploy/README-DEPLOY.txt`](deploy/README-DEPLOY.txt) for the
post-deploy checks.

## Verifying

```
python3 tools/selftest.py
python3 tools/independent_decode.py "$(cat test-vectors/vector1.txt)"
sha256sum -c checksums/SHA256SUMS
```

`selftest.py`'s image checks need a QR engine — `pip install zxing-cpp pyzbar`.
Without one they report SKIP, not PASS and not FAIL: a check that could not run
is not a check that passed. Install both if you can. They disagree in the
direction that matters — zbar is scanline-based and strict about the 1:1:3:1:1
finder ratio, and it is what cheap and embedded scanners are built on. A code
that reads only on zxing-cpp has not earned a pass.

`independent_decode.py` is written from `FORMAT.md` alone and imports nothing
from this repository. If it ever needs to consult `tools/cvqr.py`, the
specification has a hole, and the hole gets closed in `FORMAT.md`, not in the
decoder.

`test-vectors/` holds the canonical capsule from FORMAT.md §9 — synthetic, 44
bytes, no speech in it. An implementation that reproduces it is compatible.

## Notes that cost real time to discover

**Space is a valid Base45 character.** Stripping whitespace from a pasted
payload to be tidy silently corrupts most of them. Strip only `\r\n\t`, and try
the string untrimmed first so real data always wins.

**Never invert a QR.** zxing reads inverted codes; zbar does not, and zbar is
what a lot of cheap and embedded scanners are built on. Mark the dark modules.

**Do not bloom-compensate an engraved QR.** The tolerance is violently
asymmetric: dark modules oversize by 14% per side still read on both engines,
undersize by 1.7% per side already breaks zbar, because thinning the dark bars
breaks the finder pattern's run-length ratio long before any data module is at
risk. Bloom is the safe direction.

**Error correction is a physical decision.** Raising ECC grows the symbol, which
at fixed physical size shrinks every module. On laser-marked metal the dominant
failure is a camera failing to resolve modules at all under glare, and
redundancy cannot recover data the sensor never captured. Spend the budget on
module size: prefer Q, consider M, reach for H only if the pitch stays above
~0.5 mm.

**Force standard QR in generators.** segno picks Micro QR for short payloads,
and many phone scanners will not read it. Pass `micro=False`.

**Bit-pack the Codec2 frames.** `c2enc` byte-aligns each 52-bit 1300 frame into
7 bytes; packing them contiguously saves ~7%, which is worth a whole QR version.

## Layout

```
FORMAT.md                     normative spec, CC0, with the hex test vector
tools/cvqr.py                 reference implementation
tools/encode_voice.py         WAV -> Codec2 -> capsule -> CVQR1: text
tools/decode_voice.py         the inverse, back to WAV
tools/make_qr.py              QR + module-pitch table for candidate sizes
tools/read_qr.py              scan an image back, with photo rehabilitation
tools/make_coupon.py          parameter-sweep coupon plate for laser settings
tools/bundle_decoder.py       decoder/ -> one self-contained html
tools/selftest.py             adversarial checks
tools/independent_decode.py   spec-sufficiency proof
decoder/                      editable decoder source
release/cvqr-decoder.html     single-file build
deploy/                       what Cloudflare Pages serves
test-vectors/                 the canonical capsule from FORMAT.md §9
```

## Licensing

Apache-2.0 for the code ([`LICENSE`](LICENSE)), CC0 for `FORMAT.md`, and Codec2
remains LGPL-2.1 (`LICENSES/`). The Apache patent grant is the binding promise
not to patent the format.
