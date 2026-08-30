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

  /* Read a QR from an image, trying progressively harder before giving up. */
  async function handleImage(file) {
    $('status').textContent = 'Reading image…';
    let bitmap;
    try {
      bitmap = await createImageBitmap(file);
    } catch {
      $('status').textContent = '';
      return fail('That file could not be opened as an image.');
    }
    const attempts = [1, 2, 0.5];
    for (const scale of attempts) {
      const w = Math.round(bitmap.width * scale), h = Math.round(bitmap.height * scale);
      if (w < 32 || h < 32 || w > 8000 || h > 8000) continue;
      const cv = document.createElement('canvas');
      cv.width = w; cv.height = h;
      const g = cv.getContext('2d', { willReadFrequently: true });
      g.drawImage(bitmap, 0, 0, w, h);
      const img = g.getImageData(0, 0, w, h);
      for (const opts of [{}, { inversionAttempts: 'invertFirst' }]) {
        const res = jsQR(img.data, w, h, opts);
        if (res && res.data) {
          $('status').textContent = '';
          $('paste').value = res.data;
          return handleText(res.data);
        }
      }
    }
    $('status').textContent = '';
    fail('No QR code found in that image.',
         'Try a straighter, closer photo with even light. Glare across the code is the usual culprit on metal.');
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
