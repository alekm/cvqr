# Vendored runtime dependencies

Nothing here is fetched at runtime. Both files are committed so the decoder
works with no network, and so it still works if either upstream disappears.

## codec2-wasm.js  —  LGPL-2.1, David Rowe, github.com/drowe67/codec2

Codec2 1.2.0 compiled to WebAssembly, emitted as a single file with the .wasm
binary base64-embedded (no separate fetch, no MIME-type problems on odd hosts).

Reproduce:

    git clone https://github.com/drowe67/codec2.git
    cd codec2 && git checkout 310777b1c6f1af0bc7c72f5b32f80f6fd9136962   # v1.2.0, 2026-03-17
    # codebook*.c are generated at build time, so configure a native build first
    mkdir c2native && cd c2native && cmake ../codec2 -DCMAKE_BUILD_TYPE=Release
    make -j4 codec2

    emcc -O3 \
      codec2.c sine.c nlp.c lpc.c lsp.c quantise.c phase.c postfilter.c \
      interp.c pack.c codec2_fft.c kiss_fft.c kiss_fftr.c newamp1.c mbest.c \
      dump.c <generated codebook*.c> wrapper.c \
      -s MODULARIZE=1 -s EXPORT_NAME=CVQRCodec -s SINGLE_FILE=1 \
      -s ALLOW_MEMORY_GROWTH=1 -s ENVIRONMENT=web,worker,node \
      -s EXPORTED_RUNTIME_METHODS='["cwrap","HEAP16","HEAPU8"]' \
      -s EXPORTED_FUNCTIONS='["_cvqr_create","_cvqr_destroy","_cvqr_bits_per_frame",
                              "_cvqr_bytes_per_frame","_cvqr_samples_per_frame",
                              "_cvqr_decode","_malloc","_free"]' \
      -o codec2.js

Built with emscripten 3.1.6 (Ubuntu 24.04 package 3.1.6~dfsg-7). Only the decoder path is included — no LDPC,
OFDM, FSK or FreeDV.

VERIFIED: decoding the project's own take-1 payload through this build and
through the reference `c2dec 1300` produces PCM differing in 34 samples out
of 9920, by 1 LSB each — WASM floating-point rounding, roughly -90 dB.

## jsQR.js  —  Apache-2.0, Cosmo Wolfe, github.com/cozmo/jsQR

Pure-JS QR reader, used only for the "upload a photo" path. Unmodified
dist build from npm `jsqr`.
