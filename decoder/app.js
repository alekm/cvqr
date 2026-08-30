/* app.js — CVQR/1 decoder UI. No network, no storage, no state that outlives the tab. */
'use strict';

(() => {
  const $ = (id) => document.getElementById(id);
  let codecModule = null;   // lazily instantiated WASM
  let audioCtx = null;
  let current = null;       // { cap, pcm }

  /* ---------------------------------------------------------------- decode */

  async function getCodec() {
    if (!codecModule) codecModule = await CVQRCodec();
    return codecModule;
  }

  async function decodeToPcm(cap) {
    const M = await getCodec();
    const codec2Mode = CVQR.MODES[cap.modeId][4];
    const c = M._cvqr_create(codec2Mode);
    try {
      const bytesPerFrame = M._cvqr_bytes_per_frame(c);
      const samplesPerFrame = M._cvqr_samples_per_frame(c);
      const aligned = CVQR.unpackFrames(cap);
      const inPtr = M._malloc(bytesPerFrame);
      const outPtr = M._malloc(samplesPerFrame * 2);
      const pcm = new Int16Array(cap.frameCount * samplesPerFrame);
      try {
        for (let f = 0; f < cap.frameCount; f++) {
          M.HEAPU8.set(aligned.subarray(f * bytesPerFrame, (f + 1) * bytesPerFrame), inPtr);
          M._cvqr_decode(c, outPtr, inPtr);
          pcm.set(M.HEAP16.subarray(outPtr >> 1, (outPtr >> 1) + samplesPerFrame),
                  f * samplesPerFrame);
        }
      } finally {
        M._free(inPtr); M._free(outPtr);
      }
      return pcm;
    } finally {
      M._cvqr_destroy(c);
    }
  }

  /* ------------------------------------------------------------------- ui */

  function show(el) { el.hidden = false; }
  function hide(el) { el.hidden = true; }

  function fail(message, detail) {
    hide($('result'));
    $('errorMsg').textContent = message;
    $('errorDetail').textContent = detail || '';
    $('errorDetail').hidden = !detail;
    show($('error'));
    current = null;
  }

  function drawWave(pcm) {
    const cv = $('wave');
    const dpr = window.devicePixelRatio || 1;
    const w = cv.clientWidth, h = cv.clientHeight;
    cv.width = w * dpr; cv.height = h * dpr;
    const g = cv.getContext('2d');
    g.scale(dpr, dpr);
    g.clearRect(0, 0, w, h);
    g.strokeStyle = getComputedStyle(cv).color;
    g.lineWidth = 1;
    g.beginPath();
    const step = Math.max(1, Math.floor(pcm.length / w));
    for (let x = 0; x < w; x++) {
      let peak = 0;
      for (let i = x * step; i < (x + 1) * step && i < pcm.length; i++) {
        peak = Math.max(peak, Math.abs(pcm[i]));
      }
      const a = (peak / 32768) * (h / 2) * 0.95;
      g.moveTo(x + 0.5, h / 2 - a);
      g.lineTo(x + 0.5, h / 2 + a);
    }
    g.stroke();
  }

  function present(cap, pcm) {
    current = { cap, pcm };
    const [name, bits, , frameMs] = CVQR.MODES[cap.modeId];
    const rows = [
      ['Format', 'CVQR/1'],
      ['Codec', `Codec2 ${name} bit/s`],
      ['Frames', `${cap.frameCount} × ${frameMs} ms (${bits} bits each)`],
      ['Audio', `${cap.sampleRate} Hz · ${cap.channels === 1 ? 'mono' : cap.channels + ' ch'} · ${cap.bitsPerSample}-bit`],
      ['Duration', `${(cap.durationMs / 1000).toFixed(2)} s`],
      ['Payload', `${cap.payload.length} bytes`],
      ['Integrity', `CRC-32 ${cap.crc.toString(16).toUpperCase().padStart(8, '0')} — verified`],
    ];
    $('meta').innerHTML = rows
      .map(([k, v]) => `<div class="k">${k}</div><div class="v">${v}</div>`).join('');
    hide($('error'));
    show($('result'));
    drawWave(pcm);
    $('play').disabled = false;
    $('play').focus();
  }

  async function handleText(text) {
    let cap;
    try {
      cap = CVQR.fromText(text);
    } catch (e) {
      return fail(e instanceof CVQR.CVQRError ? e.message : 'Could not read that payload.',
                  e instanceof CVQR.CVQRError ? '' : String(e));
    }
    try {
      present(cap, await decodeToPcm(cap));
    } catch (e) {
      fail('The capsule is valid but the audio could not be decoded.', String(e));
    }
  }

  /* Decode a file to something drawable.
   *
   * createImageBitmap is the fast path, but Safari rejects some camera files
   * through it — HEIC in particular — so fall back to an <img> and a blob URL,
   * which goes through the platform's own image decoder and handles anything
   * the OS can display.
   */
  async function loadImage(file) {
    try {
      const bmp = await createImageBitmap(file);
      return { src: bmp, w: bmp.width, h: bmp.height, close: () => bmp.close && bmp.close() };
    } catch {
      const url = URL.createObjectURL(file);
      try {
        const img = await new Promise((res, rej) => {
          const i = new Image();
          i.onload = () => res(i);
          i.onerror = () => rej(new Error('decode failed'));
          i.src = url;
        });
        return { src: img, w: img.naturalWidth, h: img.naturalHeight,
                 close: () => URL.revokeObjectURL(url) };
      } catch (e) {
        URL.revokeObjectURL(url);
        throw e;
      }
    }
  }

  /* One scan attempt at a given pixel size. Returns the decoded text or null.
   *
   * The canvas is explicitly zeroed afterwards. iOS caps total canvas memory
   * per page, and a 12-megapixel photo is ~48 MB per canvas; leaving three of
   * them alive is enough for the next getContext to return null on a phone,
   * which is how "nothing happened at all" used to occur.
   */
  function scanAt(image, w, h) {
    const cv = document.createElement('canvas');
    try {
      cv.width = w; cv.height = h;
      const g = cv.getContext('2d', { willReadFrequently: true });
      if (!g) return null;                        // out of canvas memory
      g.drawImage(image.src, 0, 0, w, h);
      const img = g.getImageData(0, 0, w, h);
      for (const opts of [{}, { inversionAttempts: 'invertFirst' }]) {
        const res = jsQR(img.data, w, h, opts);
        if (res && res.data) return res.data;
      }
      return null;
    } finally {
      cv.width = 0; cv.height = 0;
    }
  }

  const MAX_PIXELS = 16000000;   // a single canvas above this fails on iOS

  /* Read a QR from an image, trying progressively harder before giving up.
   *
   * Downscale FIRST. A phone photo is far larger than a QR reader needs — a
   * 69-module symbol wants a few hundred pixels, not four thousand — and the
   * smaller pass is both quicker and less noisy, so it usually wins outright.
   * Full resolution is the fallback for a code that is small in frame, not the
   * opening move.
   */
  async function handleImage(file) {
    let image = null;
    try {
      $('status').textContent = 'Reading image…';
      await new Promise((r) => setTimeout(r, 0));   // let that paint first

      try {
        image = await loadImage(file);
      } catch {
        return fail('That file could not be opened as an image.',
                    'If it came from an iPhone it may be HEIC; sharing or exporting it as JPEG works.');
      }
      if (!image.w || !image.h) {
        return fail('That image has no dimensions this browser can read.');
      }

      const longest = Math.max(image.w, image.h);
      const targets = [1400, 2400, longest, longest * 2];
      const tried = new Set();
      let n = 0;
      for (const target of targets) {
        const scale = Math.min(target / longest, 4);
        const w = Math.round(image.w * scale), h = Math.round(image.h * scale);
        const key = w + 'x' + h;
        if (w < 32 || h < 32 || w * h > MAX_PIXELS || tried.has(key)) continue;
        tried.add(key);

        $('status').textContent = `Looking for a code… (pass ${++n}, ${w}×${h})`;
        await new Promise((r) => setTimeout(r, 0));   // keep the UI alive

        let text = null;
        try {
          text = scanAt(image, w, h);
        } catch {
          continue;                                   // this size failed; try another
        }
        if (text) {
          $('paste').value = text;
          return handleText(text);
        }
      }

      fail('No QR code found in that image.',
           'Try a straighter, closer photo with even light. Glare across the code is the usual culprit on metal.');
    } catch (e) {
      // Nothing may fail silently here. A photo that does nothing at all is
      // indistinguishable from a broken page.
      fail('Something went wrong reading that image.', String(e && e.message || e));
    } finally {
      if (image) { try { image.close(); } catch {} }
      $('status').textContent = '';
    }
  }

  /* ---------------------------------------------------------------- play */

  function play() {
    if (!current) return;
    if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    if (audioCtx.state === 'suspended') audioCtx.resume();
    const { pcm, cap } = current;
    const buf = audioCtx.createBuffer(1, pcm.length, cap.sampleRate);
    const ch = buf.getChannelData(0);
    for (let i = 0; i < pcm.length; i++) ch[i] = pcm[i] / 32768;
    const src = audioCtx.createBufferSource();
    src.buffer = buf;
    src.connect(audioCtx.destination);
    src.start();
  }

  function downloadWav() {
    if (!current) return;
    const { pcm, cap } = current;
    const hdr = new ArrayBuffer(44);
    const dv = new DataView(hdr);
    const wr = (o, s) => { for (let i = 0; i < s.length; i++) dv.setUint8(o + i, s.charCodeAt(i)); };
    const bytes = pcm.length * 2;
    wr(0, 'RIFF'); dv.setUint32(4, 36 + bytes, true); wr(8, 'WAVE');
    wr(12, 'fmt '); dv.setUint32(16, 16, true); dv.setUint16(20, 1, true);
    dv.setUint16(22, 1, true); dv.setUint32(24, cap.sampleRate, true);
    dv.setUint32(28, cap.sampleRate * 2, true); dv.setUint16(32, 2, true);
    dv.setUint16(34, 16, true); wr(36, 'data'); dv.setUint32(40, bytes, true);
    const blob = new Blob([hdr, pcm.buffer], { type: 'audio/wav' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'cvqr-recovered.wav';
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 10000);
  }

  /* --------------------------------------------------------------- wiring */

  document.addEventListener('DOMContentLoaded', () => {
    $('decodeText').addEventListener('click', () => {
      const v = $('paste').value;
      if (!v) return fail('Nothing to decode.', 'Paste a payload beginning with CVQR1:');
      handleText(v);
    });
    $('file').addEventListener('change', (e) => {
      if (e.target.files[0]) handleImage(e.target.files[0]);
    });
    $('play').addEventListener('click', play);
    $('save').addEventListener('click', downloadWav);

    const drop = $('drop');
    ['dragenter', 'dragover'].forEach((t) => drop.addEventListener(t, (e) => {
      e.preventDefault(); drop.classList.add('over');
    }));
    ['dragleave', 'drop'].forEach((t) => drop.addEventListener(t, (e) => {
      e.preventDefault(); drop.classList.remove('over');
    }));
    drop.addEventListener('drop', (e) => {
      const f = e.dataTransfer.files[0];
      if (f) handleImage(f);
    });
    document.addEventListener('paste', (e) => {
      const item = [...(e.clipboardData?.items || [])].find((i) => i.type.startsWith('image/'));
      if (item) { handleImage(item.getAsFile()); e.preventDefault(); }
    });
  });
})();
