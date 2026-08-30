#!/usr/bin/env python3
"""
bundle_decoder.py — fold decoder/ into one self-contained .html file.

The multi-file version in decoder/ is what you edit. This is what you archive
and what you upload: a single file with the WASM, the QR reader and the app
all inside it, so recovery in thirty years needs one file and a browser rather
than a directory structure and a web server that serves .wasm with the right
MIME type.

  ./bundle_decoder.py --out release/cvqr-decoder.html
"""
import argparse
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "decoder"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=pathlib.Path, default=ROOT / "release/cvqr-decoder.html")
    args = ap.parse_args()

    html = (SRC / "index.html").read_text()

    # Inlining scripts means they are no longer 'self', so the policy has to
    # allow inline script. Everything else stays locked down; connect-src keeps
    # data:/blob: only because emscripten instantiates its embedded wasm that way.
    html = re.sub(
        r'(<meta http-equiv="Content-Security-Policy"\s+content=")[^"]*(")',
        r"\1default-src 'none'; script-src 'unsafe-inline' 'wasm-unsafe-eval' blob:; "
        r"style-src 'unsafe-inline'; img-src 'self' data: blob:; media-src blob:; "
        r"connect-src data: blob:; worker-src blob:; form-action 'none'; base-uri 'none'\2",
        html, count=1)

    def inline(match):
        src = match.group(1)
        path = (SRC / src.lstrip("./")).resolve()
        if not path.is_file():
            raise SystemExit(f"missing script referenced by index.html: {src}")
        body = path.read_text()
        # A literal </script> inside JS would close the tag early.
        body = body.replace("</script>", "<\\/script>")
        return f"<script>\n/* ---- inlined from {src} ---- */\n{body}\n</script>"

    html, n = re.subn(r'<script src="([^"]+)"></script>', inline, html)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(html)
    kb = args.out.stat().st_size / 1024
    print(f"inlined {n} scripts")
    print(f"wrote   {args.out}  ({kb:.0f} KB)")
    if "<script src=" in html:
        raise SystemExit("ERROR: an external script reference survived bundling")
    print("verified: no external references remain")


if __name__ == "__main__":
    main()
