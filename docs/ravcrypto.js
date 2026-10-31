export const MAGIC = new Uint8Array([...'Ravensburgerv03\0'].map(c => c.charCodeAt(0)));
export const HEADER_LEN = 0x20;
export const KEYSTREAM_LEN = 512;
export const FLAG = 0xBE;
export const TRAILER = new Uint8Array([0x4E, 0x6C, 0x31, 0xF2, 0x65]);
export const DEFAULT_VALUE16 = 0x78;
export const DEFAULT_KEY8 = 'CommonI2';

const enc = new TextEncoder();

export function key8Bytes(key8) {
  return typeof key8 === 'string' ? enc.encode(key8) : key8;
}

export function buildHeader(value16, key8, table) {
  const k8 = key8Bytes(key8);
  if (k8.length !== 8) throw new Error('key8 must be exactly 8 bytes');

  const hdr = new Uint8Array(HEADER_LEN);
  hdr.set(MAGIC, 0);
  hdr[0x10] = value16 & 0xFF;
  hdr[0x11] = (value16 >> 8) & 0xFF;
  hdr[0x12] = FLAG;
  for (let i = 0; i < 8; i++) hdr[0x13 + i] = table[value16 + 3 + i] ^ k8[i];
  hdr.set(TRAILER, 0x1B);
  return hdr;
}

export function derive(value16, keyBlob, table) {
  const k8 = new Uint8Array(8);
  for (let i = 0; i < 8; i++) k8[i] = table[value16 + 3 + i] ^ keyBlob[i];

  let sum = 0;
  for (let i = 0; i < 8; i++) sum += k8[i];
  const checksum = (sum + value16) & 0xFFFF;

  const keystream = new Uint8Array(KEYSTREAM_LEN);
  for (let i = 0; i < KEYSTREAM_LEN; i++) keystream[i] = table[(checksum + i) & 0xFFF];

  return { key8: k8, checksum, keystream };
}

export function transform(data, keystream, start, decrypt) {
  const out = new Uint8Array(data.length);
  for (let i = 0; i < data.length; i++) {
    const p = data[i];
    const pos = start + i;
    const kb = keystream[i & 0x1FF];
    const op = pos & 3;

    if (decrypt) {
      if (op === 0) {
        if (p === 0x00 || p === 0xFF || p === kb || (p ^ kb) === 0xFF) { out[i] = p; continue; }
        out[i] = p ^ kb;
      } else if (op === 1) out[i] = (p - kb) & 0xFF;
      else if (op === 2) out[i] = (p + kb) & 0xFF;
      else out[i] = p ^ kb;
    } else {
      if (op === 0 && (p === 0x00 || p === 0xFF || p === kb || p === (kb ^ 0xFF))) { out[i] = p; continue; }
      if (op === 0) out[i] = p ^ kb;
      else if (op === 1) out[i] = (p + kb) & 0xFF;
      else if (op === 2) out[i] = (p - kb) & 0xFF;
      else out[i] = p ^ kb;
    }
  }
  return out;
}

export function encryptRav(payload, table, value16 = DEFAULT_VALUE16, key8 = DEFAULT_KEY8) {
  const hdr = buildHeader(value16, key8, table);
  const { keystream } = derive(value16, hdr.subarray(0x13, 0x1B), table);
  const body = transform(payload, keystream, HEADER_LEN, false);
  const out = new Uint8Array(hdr.length + body.length);
  out.set(hdr, 0);
  out.set(body, hdr.length);
  return out;
}

export function decryptRav(bytes, table) {
  for (let i = 0; i < 16; i++) {
    if (bytes[i] !== MAGIC[i]) throw new Error('not a Ravensburger RAV file (bad magic)');
  }
  const value16 = bytes[0x10] | (bytes[0x11] << 8);
  const { key8, checksum, keystream } = derive(value16, bytes.subarray(0x13, 0x1B), table);
  const plaintext = transform(bytes.subarray(HEADER_LEN), keystream, HEADER_LEN, true);
  return { value16, key8, checksum, plaintext };
}
