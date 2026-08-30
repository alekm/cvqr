Cloudflare Pages
----------------
This directory is what Pages serves. It is GENERATED — index.html is built from
decoder/ by tools/bundle_decoder.py. Edit decoder/, not this.

  index.html     the decoder — one file, no build step, no dependencies
  FORMAT.md      the normative spec, served as plain text
  vector1.txt    canonical test vector, text form
  vector1.hex    canonical test vector, hex dump
  _headers       security headers and content types for Pages
  404.html       so a missing path is not answered with 558 KB of decoder
  robots.txt     asks to be indexed; "CVQR1:" must stay a searchable term
  sitemap.xml    points at cvqr.app — see the note below

The last three are the fix for Pages answering every unknown path with
index.html; a robots.txt request returned the whole decoder before they existed.

Deploying from git (current setup)
----------------------------------
Pages is connected to the repository. Settings:

  Build command             (leave empty)
  Build output directory    deploy
  Root directory            /

There is no build step on Cloudflare's side. If you change the decoder, rebuild
and commit the result — Pages only publishes what is in the repo:

  python3 tools/bundle_decoder.py --out release/cvqr-decoder.html
  cp release/cvqr-decoder.html deploy/index.html

Then add cvqr.app as a custom domain. Since Cloudflare already holds the DNS,
Pages will offer to create the record itself and issue the certificate.

sitemap.xml and robots.txt both hardcode https://cvqr.app. Until the custom
domain is attached they point at a hostname that does not serve this site yet —
harmless, but they only start being true once the domain is live. On the
*.pages.dev preview URL, expect them to be wrong.

Deploying by hand (fallback)
----------------------------
If the git integration is ever unavailable, upload the CONTENTS of this folder
(not the folder itself) to a Pages project via drag and drop. All eight files.

Check after deploying
---------------------
  1. Open cvqr.app on a phone. Choose a photo of the QR. It should play.
  2. Open cvqr.app/FORMAT.md — it must render as readable text, not download.
  3. Open cvqr.app/nonexistent — it must be the small 404, not the decoder.
  4. Turn off wifi and mobile data, reload from cache, decode again. The whole
     point is that it still works.
