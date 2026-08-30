/* app.js — CVQR/1 decoder UI. No network, no storage, no state that outlives the tab. */
'use strict';

(() => {
  const $ = (id) => document.getElementById(id);

  /* A real recording rather than a synthetic vector: one spoken word, 488 ms.
   * Encoded at 3200 bit/s — the highest mode the format defines — because this
   * is a demonstration and should sound like the format at its best. It lands
   * in the same QR version as a far longer clip at 1300 would, so it is also
   * an honest picture of the size involved. */
  const EXAMPLE = 'CVQR1:3N8SCAW50$*0Z.3260000%A0O00C40P 7JSF8OPVZDX*Q5GB.URO-CKH2R1VERU+*8C3K%9N$11Y$O2YJR38S29+-DQIR*Z3-7S37L0H24D3ZRR$4IW-BHZ2*RRSYLUJBNJ5JRR4*KGH3E05-PRL5LTG3:O67ES9%S273MP7JASG.P969WI4ODS%:9J7Q2J6BRRXP5F3ISH6QFW$TDOHHFMH9ZP2AU77I3+3DAQV/TF-HUD35*PP$H1XP4:I* P*6MH%11G6I%O/-PH9BQ0J.2S.J80 J%+6FMRLY9.ZJ.K5TNO-$HV42M/4BZU1RH6KAQDD';
  let codecModule = null;   // lazily instantiated WASM
  let audioCtx = null;      // fallback only; see play()
  let audioEl = null;       // the media element that actually plays on phones
  let wavUrl = null;        // object URL for the current capsule's WAV
  let current = null;       // { cap, pcm }
  let peaks = null;         // cached waveform envelope
  let rafId = null;         // playhead animation

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

  /* Peak envelope, one value per device pixel column. Cached because it is
   * recomputed on every animation frame otherwise, and a phone will feel it. */
  function computePeaks(pcm, cols) {
    const peaks = new Float32Array(cols);
    const step = pcm.length / cols;
    for (let x = 0; x < cols; x++) {
      const a = Math.floor(x * step), b = Math.min(pcm.length, Math.floor((x + 1) * step));
      let peak = 0;
      for (let i = a; i < b; i++) { const v = Math.abs(pcm[i]); if (v > peak) peak = v; }
      peaks[x] = peak;
    }
    // Normalise to the loudest peak. Codec2 output rarely approaches full
    // scale, and a waveform drawn against 32768 is a flat line with a wiggle
    // in it — accurate, and useless as a picture of the sound.
    let max = 0;
    for (let i = 0; i < peaks.length; i++) if (peaks[i] > max) max = peaks[i];
    const scale = max > 64 ? 1 / max : 0;      // near-silence stays flat
    for (let i = 0; i < peaks.length; i++) peaks[i] *= scale;
    return peaks;
  }

  /* progress is 0..1; everything left of it is drawn as played. */
  function drawWave(progress) {
    const cv = $('wave');
    const dpr = window.devicePixelRatio || 1;
    const w = cv.clientWidth, h = cv.clientHeight;
    if (!w || !h || !current) return;
    if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) {
      cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr);
      peaks = null;
    }
    if (!peaks || peaks.length !== Math.round(w)) peaks = computePeaks(current.pcm, Math.round(w));

    const g = cv.getContext('2d');
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, w, h);
    const mid = h / 2, head = (progress || 0) * w;
    const css = getComputedStyle(document.documentElement);
    const played = (css.getPropertyValue('--accent') || '#7fb2e5').trim();
    const unplayed = (css.getPropertyValue('--faint') || '#5d666f').trim();

    // baseline
    g.strokeStyle = unplayed; g.globalAlpha = .35;
    g.beginPath(); g.moveTo(0, mid + .5); g.lineTo(w, mid + .5); g.stroke();
    g.globalAlpha = 1;

    for (let x = 0; x < peaks.length; x++) {
      const a = Math.max(0.75, peaks[x] * (h / 2) * 0.92);
      g.fillStyle = x <= head ? played : unplayed;
      g.fillRect(x, mid - a, 1, a * 2);
    }
    if (progress > 0 && progress < 1) {
      g.fillStyle = played;
      g.fillRect(Math.min(w - 1, head), 2, 1, h - 4);
    }
  }

  function fmtTime(sec) {
    if (!isFinite(sec) || sec < 0) sec = 0;
    const m = Math.floor(sec / 60), s = sec - m * 60;
    return m + ':' + (s < 10 ? '0' : '') + s.toFixed(2);
  }

  function setTimes(cur, total) {
    $('tCur').textContent = fmtTime(cur);
    $('tTot').textContent = fmtTime(total);
  }

  function stopTracking() {
    if (rafId) { cancelAnimationFrame(rafId); rafId = null; }
  }

  function track() {
    stopTracking();
    const step = () => {
      if (!audioEl || audioEl.paused) return;
      const d = audioEl.duration || 0;
      drawWave(d ? audioEl.currentTime / d : 0);
      setTimes(audioEl.currentTime, d);
      rafId = requestAnimationFrame(step);
    };
    rafId = requestAnimationFrame(step);
  }

  function present(cap, pcm) {
    // A new capsule invalidates the previous WAV, or Play would replay the old one.
    if (wavUrl) { URL.revokeObjectURL(wavUrl); wavUrl = null; }
    note('');
    $('play').textContent = 'Play';
    current = { cap, pcm };
    const [name, bits, , frameMs] = CVQR.MODES[cap.modeId];
    const rows = [
      ['Format', 'CVQR/1'],
      ['Codec', `Codec2 ${name} bit/s`],
      ['Frames', `${cap.frameCount} × ${frameMs} ms (${bits} bits each)`],
      ['Audio', `${cap.sampleRate} Hz · ${cap.channels === 1 ? 'mono' : cap.channels + ' ch'} · ${cap.bitsPerSample}-bit`],
      ['Duration', `${(cap.durationMs / 1000).toFixed(2)} s`],
      ['Payload', `${cap.payload.length} bytes`],
    ];
    $('meta').innerHTML = rows
      .map(([k, v]) => `<div class="k">${k}</div><div class="v">${v}</div>`).join('');
    hide($('error'));
    show($('result'));
    peaks = null;
    drawWave(0);
    setTimes(0, pcm.length / cap.sampleRate);
    $('crcBadge').textContent = 'CRC-32 ' + cap.crc.toString(16).toUpperCase().padStart(8, '0');
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

  /* PCM -> a complete WAV file. Shared by playback and by Save, so the bytes
   * you hear and the bytes you keep are built by the same code. */
  function wavBytes(pcm, sampleRate) {
    const hdr = new ArrayBuffer(44);
    const dv = new DataView(hdr);
    const wr = (o, s) => { for (let i = 0; i < s.length; i++) dv.setUint8(o + i, s.charCodeAt(i)); };
    const bytes = pcm.length * 2;
    wr(0, 'RIFF'); dv.setUint32(4, 36 + bytes, true); wr(8, 'WAVE');
    wr(12, 'fmt '); dv.setUint32(16, 16, true); dv.setUint16(20, 1, true);
    dv.setUint16(22, 1, true); dv.setUint32(24, sampleRate, true);
    dv.setUint32(28, sampleRate * 2, true); dv.setUint16(32, 2, true);
    dv.setUint16(34, 16, true); wr(36, 'data'); dv.setUint32(40, bytes, true);
    return new Blob([hdr, pcm.buffer], { type: 'audio/wav' });
  }

  function note(text, bad) {
    const el = $('playNote');
    el.textContent = text || '';
    el.classList.toggle('bad', !!bad);
    el.hidden = !text;
  }

  /* Web Audio, kept only as a fallback.
   *
   * Two reasons it is not the primary path on a phone. Safari refuses
   * createBuffer below 22050 Hz, and this format is 8000 Hz by definition —
   * so the buffer is built at the context's own rate and resampled here.
   * And iOS silences Web Audio with the hardware Ring/Silent switch, which a
   * media element is not subject to.
   */
  function playViaWebAudio() {
    if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    if (audioCtx.state === 'suspended') audioCtx.resume();
    const { pcm, cap } = current;
    const rate = audioCtx.sampleRate || cap.sampleRate;
    const ratio = rate / cap.sampleRate;
    const n = Math.max(1, Math.round(pcm.length * ratio));
    const buf = audioCtx.createBuffer(1, n, rate);
    const ch = buf.getChannelData(0);
    for (let i = 0; i < n; i++) {
      const t = i / ratio, i0 = Math.floor(t), f = t - i0;
      const a = pcm[Math.min(i0, pcm.length - 1)] / 32768;
      const b = pcm[Math.min(i0 + 1, pcm.length - 1)] / 32768;
      ch[i] = a + (b - a) * f;
    }
    const src = audioCtx.createBufferSource();
    src.buffer = buf;
    src.connect(audioCtx.destination);
    src.start();
  }

  /* Play through a media element carrying a WAV blob.
   *
   * This is the path that works on a phone: the platform decodes the WAV, so
   * the 8 kHz rate is its problem rather than ours, and the audio goes out on
   * the media channel where the silent switch does not reach it.
   */
  async function play() {
    if (!current) return;
    const btn = $('play');

    // A second press stops it. A dead-looking control that ignores you is the
    // same bug as a Play button that does nothing.
    if (audioEl && !audioEl.paused) {
      audioEl.pause();
      return;
    }

    try {
      if (!audioEl) {
        audioEl = new Audio();
        audioEl.preload = 'auto';
        const reset = () => {
          btn.textContent = 'Play';
          stopTracking();
          drawWave(0);
          setTimes(0, audioEl.duration || current.pcm.length / current.cap.sampleRate);
        };
        audioEl.addEventListener('ended', reset);
        audioEl.addEventListener('pause', () => {
          btn.textContent = 'Play';
          stopTracking();
        });
        audioEl.addEventListener('play', () => { btn.textContent = 'Stop'; track(); });
      }
      if (!wavUrl) {
        wavUrl = URL.createObjectURL(wavBytes(current.pcm, current.cap.sampleRate));
        audioEl.src = wavUrl;
      }
      note('');
      audioEl.currentTime = 0;
      await audioEl.play();
    } catch (e) {
      btn.textContent = 'Play';
      stopTracking();
      try {
        playViaWebAudio();
        note('Playing. If you hear nothing, check the side switch — iPhones mute '
           + 'this kind of audio when the ringer is off.');
      } catch (e2) {
        note('This browser would not play the audio: '
           + String((e2 && e2.message) || e2)
           + '. "Save as WAV" still works, and the file is a normal 8 kHz mono WAV.', true);
      }
    }
  }

  function downloadWav() {
    if (!current) return;
    const a = document.createElement('a');
    a.href = URL.createObjectURL(wavBytes(current.pcm, current.cap.sampleRate));
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
    $('example').addEventListener('click', () => {
      $('paste').value = EXAMPLE;
      handleText(EXAMPLE);
    });
    $('file').addEventListener('change', (e) => {
      if (e.target.files[0]) handleImage(e.target.files[0]);
    });
    $('play').addEventListener('click', play);

    /* Click the waveform to seek. Only meaningful once a media element exists,
     * so before the first play it just previews the position. */
    $('wave').addEventListener('click', (e) => {
      if (!current) return;
      const r = e.currentTarget.getBoundingClientRect();
      const p = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width));
      const total = current.pcm.length / current.cap.sampleRate;
      if (audioEl && audioEl.duration) {
        audioEl.currentTime = p * audioEl.duration;
        drawWave(p);
        setTimes(audioEl.currentTime, audioEl.duration);
      } else {
        drawWave(p);
        setTimes(p * total, total);
      }
    });

    let resizeTimer = null;
    window.addEventListener('resize', () => {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(() => {
        if (!current) return;
        peaks = null;
        const d = audioEl && audioEl.duration ? audioEl.currentTime / audioEl.duration : 0;
        drawWave(audioEl && !audioEl.paused ? d : 0);
      }, 120);
    });
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
