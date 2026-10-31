import { encryptRav, decryptRav } from './ravcrypto.js';
import { createEncoder } from './vendor/wasm-media-encoders.js';

const TARGET_RATE = 22050;
const VORBIS_QUALITY = 5;
const MAX_MINUTES = 20;

const $ = (id) => document.getElementById(id);
const drop = $('drop'), fileInput = $('file'), logEl = $('log');
const goBtn = $('go'), saveBtn = $('save'), statusEl = $('conv-status'), keySel = $('key');
const hintEl = $('hint'), dropTitle = $('drop-title'), dropSub = $('drop-sub'), keyRow = $('keyrow');
const modeBtns = { encrypt: $('mode-encrypt'), decrypt: $('mode-decrypt') };

const MODES = {
  encrypt: {
    title: 'Drop an audio file',
    sub: 'or click · mp3 wav m4a flac ogg aac',
    accept: 'audio/*,.mp3,.wav,.m4a,.flac,.ogg,.aac,.aiff',
    button: 'Encrypt',
    empty: ['waiting for a file', 'it never leaves this tab'],
    hint: "the pen's key is in its firmware; try CommonI2 first",
    done: "copy it into the pen's songs folder, then unplug",
  },
  decrypt: {
    title: 'Drop a .rav file',
    sub: "or click · a file from the pen's songs folder",
    accept: '.rav,application/octet-stream',
    button: 'Decrypt',
    empty: ['waiting for a .rav', 'the key comes out of its own header'],
    hint: 'the key is recovered from the file, nothing to pick',
    done: 'plays in anything that reads ogg vorbis',
  },
};

let mode = 'encrypt';
let pending = null;

function log(line, cls) {
  const p = document.createElement('p');
  if (cls) p.className = cls;
  p.textContent = line;
  logEl.appendChild(p);
  logEl.scrollTop = logEl.scrollHeight;
  while (logEl.children.length > 14) logEl.removeChild(logEl.firstChild);
}

function clearLog() { logEl.textContent = ''; }

function resetLog() {
  clearLog();
  for (const line of MODES[mode].empty) log(line, 'l-dim');
}

function setStatus(text) { statusEl.textContent = text; }

function bytes(n) { return n.toLocaleString('en-US') + ' bytes'; }

function clock(sec) {
  const m = Math.floor(sec / 60), s = Math.round(sec % 60);
  return m + ':' + String(s).padStart(2, '0');
}

function baseName(name) {
  return name.replace(/\.[^.]+$/, '') || 'output';
}

let tablePromise = null;

function loadTable() {
  if (!tablePromise) {
    tablePromise = fetch('keytable.bin').then(r => {
      if (!r.ok) throw new Error('keytable.bin missing (' + r.status + ')');
      return r.arrayBuffer();
    }).then(b => new Uint8Array(b));
  }
  return tablePromise;
}

function setMode(next) {
  mode = next;
  pending = null;
  saveBtn.hidden = true;
  goBtn.disabled = false;
  setStatus('ready');

  for (const [name, btn] of Object.entries(modeBtns)) {
    btn.setAttribute('aria-pressed', String(name === next));
  }

  const m = MODES[next];
  dropTitle.textContent = m.title;
  dropSub.textContent = m.sub;
  fileInput.setAttribute('accept', m.accept);
  goBtn.textContent = m.button;
  keyRow.hidden = next !== 'encrypt';
  hintEl.textContent = m.hint;
  resetLog();
}

function chooseFile(file) {
  if (!file) return;
  pending = file;
  saveBtn.hidden = true;
  goBtn.disabled = false;
  goBtn.textContent = MODES[mode].button;
  clearLog();
  log('> ' + file.name, 'l-prompt');
  log('  ' + (file.size / 1048576).toFixed(1) + ' MB', 'l-dim');
  setStatus('file ready');
  hintEl.textContent = mode === 'encrypt'
    ? 'encrypts locally, nothing leaves this tab'
    : 'decrypts locally, nothing leaves this tab';
}

drop.addEventListener('dragover', (e) => { e.preventDefault(); drop.dataset.over = 'true'; });
drop.addEventListener('dragleave', () => { drop.dataset.over = 'false'; });
drop.addEventListener('drop', (e) => {
  e.preventDefault();
  drop.dataset.over = 'false';
  chooseFile(e.dataTransfer.files && e.dataTransfer.files[0]);
});
fileInput.addEventListener('change', () => {
  chooseFile(fileInput.files && fileInput.files[0]);
  fileInput.value = '';
});

async function runEncrypt(file, key8) {
  const ac = new AudioContext();
  let decoded;
  try {
    decoded = await ac.decodeAudioData(await file.arrayBuffer());
  } catch (err) {
    throw new Error(/\.rav$/i.test(file.name)
      ? 'that is a .rav file, switch to Decrypt'
      : 'this browser cannot decode that file');
  } finally {
    ac.close();
  }

  log('  decoded ' + clock(decoded.duration) + ', ' + decoded.sampleRate + ' Hz, ' + decoded.numberOfChannels + ' ch', 'l-dim');
  if (decoded.duration > MAX_MINUTES * 60) {
    throw new Error('over ' + MAX_MINUTES + ' minutes; a browser runs out of memory there, use the desktop build');
  }

  const frames = Math.ceil(decoded.duration * TARGET_RATE);
  const off = new OfflineAudioContext(1, frames, TARGET_RATE);
  const src = off.createBufferSource();
  src.buffer = decoded;

  const hp = off.createBiquadFilter();
  hp.type = 'highpass';
  hp.frequency.value = 70;
  hp.Q.value = 0.7;

  const trim = off.createGain();
  trim.gain.value = Math.pow(10, -4 / 20);

  const limiter = off.createDynamicsCompressor();
  limiter.threshold.value = -1;
  limiter.knee.value = 0;
  limiter.ratio.value = 20;
  limiter.attack.value = 0.003;
  limiter.release.value = 0.1;

  src.connect(hp).connect(trim).connect(limiter).connect(off.destination);
  src.start();

  const rendered = await off.startRendering();
  const pcm = rendered.getChannelData(0);
  log('  resampled and shaped, ' + TARGET_RATE + ' Hz mono (' + bytes(pcm.length * 4) + ')', 'l-dim');

  const wasm = await (await fetch('vendor/ogg.wasm')).arrayBuffer();
  const enc = await createEncoder('audio/ogg', wasm);
  enc.configure({ channels: 1, sampleRate: TARGET_RATE, vbrQuality: VORBIS_QUALITY });

  const parts = [];
  parts.push(enc.encode([pcm]).slice());
  parts.push(enc.finalize().slice());

  let total = 0;
  for (const p of parts) total += p.length;
  const ogg = new Uint8Array(total);
  let o = 0;
  for (const p of parts) { ogg.set(p, o); o += p.length; }
  log('  encoded ogg vorbis, ' + bytes(ogg.length), 'l-dim');

  const table = await loadTable();
  const rav = encryptRav(ogg, table, 0x78, key8);
  log('  encrypted with key8 = ' + key8, 'l-dim');

  const name = baseName(file.name) + '.rav';
  log('  wrote ' + name + ', ' + bytes(rav.length), 'l-ok');
  return { blob: new Blob([rav], { type: 'application/octet-stream' }), name };
}

async function runDecrypt(file) {
  const input = new Uint8Array(await file.arrayBuffer());
  const table = await loadTable();
  const info = decryptRav(input, table);
  const key = new TextDecoder().decode(info.key8);

  log('  header ok, value16 0x' + info.value16.toString(16).padStart(4, '0'), 'l-dim');
  log('  key8 ' + key + ', checksum 0x' + info.checksum.toString(16).padStart(4, '0'), 'l-dim');

  const sig = String.fromCharCode(...info.plaintext.subarray(0, 4));
  if (sig !== 'OggS') throw new Error('no ogg vorbis inside, the key table may be wrong');

  log('  decrypted ' + bytes(info.plaintext.length) + ' of ogg vorbis', 'l-dim');
  const name = baseName(file.name) + '.ogg';
  log('  wrote ' + name, 'l-ok');
  return { blob: new Blob([info.plaintext], { type: 'audio/ogg' }), name };
}

for (const [name, btn] of Object.entries(modeBtns)) {
  btn.addEventListener('click', () => setMode(name));
}

goBtn.addEventListener('click', async () => {
  if (!pending) { fileInput.click(); return; }
  const file = pending;
  const job = mode;

  goBtn.disabled = true;
  for (const btn of Object.values(modeBtns)) btn.disabled = true;
  saveBtn.hidden = true;
  setStatus('working');

  try {
    const out = job === 'encrypt' ? await runEncrypt(file, keySel.value) : await runDecrypt(file);
    saveBtn.href = URL.createObjectURL(out.blob);
    saveBtn.download = out.name;
    saveBtn.hidden = false;
    saveBtn.textContent = 'Download ' + out.name;
    setStatus('done');
    hintEl.textContent = MODES[job].done;
  } catch (err) {
    log('! ' + err.message, 'l-err');
    setStatus('failed');
  } finally {
    goBtn.disabled = false;
    for (const btn of Object.values(modeBtns)) btn.disabled = false;
  }
});

keySel.addEventListener('change', () => {
  if (mode !== 'encrypt') return;
  hintEl.textContent = keySel.value === 'CommonI2'
    ? 'the default on every pen tested so far'
    : 'newer pens; decrypt a stock .rav to confirm';
});

setMode('encrypt');
