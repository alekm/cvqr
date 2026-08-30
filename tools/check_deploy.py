#!/usr/bin/env python3
"""
check_deploy.py — assert that a live CVQR/1 deployment is actually correct.

Everything here is a property that cannot be checked before Cloudflare is
serving the files: MIME types, security headers, the 404, and whether the
bytes on the wire are the bytes in git.

  ./check_deploy.py https://cvqr.app
  ./check_deploy.py https://cvqr-abc.pages.dev --local deploy
"""
import argparse
import hashlib
import pathlib
import sys
import urllib.error
import urllib.request

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        print(f"  FAIL  {name}  {detail}")


def get(url):
    """Fetch a URL, returning (status, headers, body) and never raising on 4xx."""
    req = urllib.request.Request(url, headers={"User-Agent": "cvqr-check-deploy/1"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read()
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in e.headers.items()}, e.read()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("base", help="site root, e.g. https://cvqr.app")
    ap.add_argument("--local", type=pathlib.Path, default=pathlib.Path("deploy"),
                    help="local deploy directory to compare bytes against")
    args = ap.parse_args()
    base = args.base.rstrip("/")

    print(f"\n[1] The decoder is served, and it is the build that is in git")
    status, hdr, body = get(base + "/")
    check("/ returns 200", status == 200, f"got {status}")
    check("/ is text/html", hdr.get("content-type", "").startswith("text/html"),
          hdr.get("content-type", "(none)"))
    check("/ is the decoder", b"CVQR/1 Decoder" in body, "title not found in body")
    local = args.local / "index.html"
    if local.exists():
        want = hashlib.sha256(local.read_bytes()).hexdigest()
        got = hashlib.sha256(body).hexdigest()
        check("/ is byte-identical to deploy/index.html", want == got,
              f"live {got[:16]}… vs local {want[:16]}…")
    else:
        print(f"  ....  skipping byte comparison; {local} not found")

    print(f"\n[2] The spec and vectors render as text, not as downloads")
    for path in ("/FORMAT.md", "/vector1.txt", "/vector1.hex", "/robots.txt"):
        status, hdr, body = get(base + path)
        ct = hdr.get("content-type", "")
        check(f"{path} returns 200", status == 200, f"got {status}")
        check(f"{path} is text/plain", ct.startswith("text/plain"), ct or "(none)")
        check(f"{path} is not an attachment",
              "attachment" not in hdr.get("content-disposition", ""),
              hdr.get("content-disposition", ""))
    status, hdr, _ = get(base + "/sitemap.xml")
    check("/sitemap.xml is XML", "xml" in hdr.get("content-type", ""),
          hdr.get("content-type", "(none)"))

    print(f"\n[3] A missing path is not answered with the whole decoder")
    status, hdr, body = get(base + "/nonexistent-" + "x" * 12)
    check("unknown path returns 404", status == 404, f"got {status}")
    check("404 body is small", len(body) < 10_000, f"{len(body)} bytes")
    check("404 body is not the decoder", b"CVQR/1 Decoder" not in body,
          "the decoder was served for a missing path")

    print(f"\n[4] Security headers")
    _, hdr, _ = get(base + "/")
    for name, want in [("x-content-type-options", "nosniff"),
                       ("referrer-policy", "no-referrer"),
                       ("x-frame-options", "SAMEORIGIN")]:
        check(name, hdr.get(name, "").lower() == want.lower(),
              f"got {hdr.get(name, '(absent)')!r}")
    check("permissions-policy present", "permissions-policy" in hdr,
          "(absent)")
    hsts = hdr.get("strict-transport-security", "")
    check("strict-transport-security present", "max-age" in hsts, hsts or "(absent)")

    print(f"\n[5] The page needs no network of its own")
    _, _, body = get(base + "/")
    text = body.decode("utf-8", "replace")
    for token in ("<script src=", "<link rel=\"stylesheet\"", "@import", "https://cdn"):
        check(f"no {token!r}", token not in text, "external reference in the served page")

    print(f"\n{passed} passed, {failed} failed")
    if failed:
        print("\nA failure here is a Pages configuration problem, not a format problem.\n"
              "Check the build output directory is `deploy` and that _headers went up.")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
