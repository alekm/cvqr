# CVQR/1 decoder

Static, offline, no backend. Two forms of the same thing:

- `decoder/` — the editable source. Serve the directory over anything.
- `release/cvqr-decoder.html` — one file, everything inlined. This is the
  archival copy and what gets uploaded to cvqr.app.

Rebuild the single file after editing the source:

    python3 tools/bundle_decoder.py

## Verified

A headless Chromium run (`tools/` has no test runner; the script lives in the
commit message history) checks, against both forms:

- pasted `CVQR1:` payload decodes, and the metadata panel reports Codec2 1300,
  1.25 s, and CRC verified
- a photo of the QR recovers the payload byte-for-byte
- a single corrupted character is refused as an integrity failure and the
  result panel stays hidden — nothing plays
- non-CVQR text gets a readable message naming the missing prefix
- **zero external network requests** — every request off localhost is blocked
  in the test and none is attempted

## Deploying to cvqr.app

Upload `release/cvqr-decoder.html` as `index.html`. Any static host works;
`.app` is HSTS-preloaded so TLS is mandatory — GitHub Pages, Cloudflare Pages
and Netlify all issue certificates free.

No build step, no dependencies to install, nothing to keep patched.
