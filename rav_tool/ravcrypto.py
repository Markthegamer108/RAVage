"""rav crypto for the tiptoi pen (3203L).

a .rav file is a 0x20 byte header followed by an encrypted Ogg Vorbis
stream. we worked all of this out by disassembling the firmware update
(Update3203L.upd) - the short version of what we found:

header layout:
    0x00  magic          "Ravensburgerv03\\x00" (16 bytes)
    0x10  value16        little-endian u16
    0x12  flag           0xBE
    0x13  key blob       8 bytes: TABLE[value16 + 3 + i] ^ key8[i]
    0x1B  trailer        fixed 4E 6C 31 F2 65

key derivation:
    key8       = "CommonI2"              (same in every stock file we had)
    checksum   = (sum(key8) + value16) & 0xFFFF
    keystream  = TABLE[(checksum + i) & 0xFFF]   for i in 0..511

body cipher (payload starts at file offset 0x20):
    kb = keystream[(pos - 0x20) & 0x1FF],  op = pos & 3
    op 0  XOR with pass-through:  c in (0x00, 0xFF, kb) or (c ^ kb) == 0xFF
                                  -> keep c, otherwise out = c ^ kb
    op 1  out = (c - kb) & 0xFF
    op 2  out = (c + kb) & 0xFF
    op 3  out = c ^ kb              (no pass-through here)

the pass-through rules are a quirk of the firmware loop at 0x8DF3B4: bytes
that would collide with the keystream are just left alone. the encoder
mirrors them exactly so encryption is lossless (official pen files are
lossy at those spots, ours round-trip byte-exact).

fun facts: the pen ignores ogg page crcs, and stock files carry ~1 KB of
junk after the last page that never gets read. none of that matters to us.
"""

import os
import sys

MAGIC = b"Ravensburgerv03\x00"
HEADER_LEN = 0x20
TABLE_SIZE = 0x1000
KEYSTREAM_LEN = 512
KEY8 = b"CommonI2"
FLAG = 0xBE
TRAILER = b"\x4E\x6C\x31\xF2\x65"
DEFAULT_VALUE16 = 0x78

_DEFAULT_TABLE = None


def _default_table_path():
    # bundled copy lives in data/ next to the package, unless RAV_KEYTABLE
    # points somewhere else. also works from a pyinstaller bundle where the
    # files get unpacked to sys._MEIPASS.
    here = os.path.dirname(os.path.abspath(__file__))
    meipass = getattr(sys, "_MEIPASS", None)
    cand = [os.environ.get("RAV_KEYTABLE"),
            os.path.join(meipass, "data", "keytable.bin") if meipass else None,
            os.path.join(here, "..", "data", "keytable.bin"),
            os.path.join(here, "data", "keytable.bin")]
    return next((p for p in cand if p and os.path.isfile(p)), None)


def load_keytable(path=None):
    """load the 4096 byte key table from a file (default: the bundled one)."""
    if path is None:
        path = _default_table_path()
        if path is None:
            raise FileNotFoundError(
                "keytable.bin not found; pass path= or set RAV_KEYTABLE, or "
                "run extract_keytable() on a firmware .upd file")
    with open(path, "rb") as fh:
        table = fh.read()
    if len(table) != TABLE_SIZE:
        raise ValueError(f"key table must be {TABLE_SIZE} bytes, got {len(table)}")
    return table


def extract_keytable(upd_path, out_path):
    """pull the key table out of a firmware .upd file (it sits at 0xDBADC)."""
    with open(upd_path, "rb") as fh:
        data = fh.read()
    table = data[0xDBADC:0xDBADC + TABLE_SIZE]
    if len(table) != TABLE_SIZE:
        raise ValueError("offset 0xDBADC out of range or invalid firmware file")
    with open(out_path, "wb") as fh:
        fh.write(table)
    return table


def derive(value16, key_blob, table):
    """recover (key8, checksum, keystream) from the header's value16 + key blob."""
    # the key blob in the file is table[value16+3+i] XOR key8[i], so XOR back
    key8 = bytes(table[value16 + 3 + i] ^ key_blob[i] for i in range(8))
    checksum = (sum(key8) + value16) & 0xFFFF
    # the & 0xFFF applies to (checksum + i) only, not the table base.
    # misreading that cost us a couple of days.
    keystream = bytes(table[(checksum + i) & 0xFFF] for i in range(KEYSTREAM_LEN))
    return key8, checksum, keystream


def build_header(value16, key8, table):
    """build the 0x20 byte header for the given value16 and key (default "CommonI2")."""
    hdr = bytearray(HEADER_LEN)
    hdr[0:16] = MAGIC
    hdr[0x10] = value16 & 0xFF
    hdr[0x11] = (value16 >> 8) & 0xFF
    hdr[0x12] = FLAG
    hdr[0x13:0x1B] = bytes(table[value16 + 3 + i] ^ key8[i] for i in range(8))
    hdr[0x1B:0x20] = TRAILER
    return bytes(hdr)


def transform(data, keystream, start, decrypt):
    """apply the body cipher to a payload.

    start is the file offset of data[0] (normally 0x20). the keystream
    index is relative to the payload, the op comes from the absolute
    position. mixing those up once produced files the pen silently
    skipped, so don't "simplify" this.
    """
    n = len(data)
    if n == 0:
        return data
    try:
        import numpy as np
    except ImportError:
        return _transform_pure(data, keystream, start, decrypt)

    idx = np.arange(n, dtype=np.int64)
    kb = np.frombuffer(keystream, dtype=np.uint8)[(idx & 0x1FF).astype(np.int64)]
    kb = kb.astype(np.uint16)
    c = np.frombuffer(data, dtype=np.uint8).astype(np.uint16)
    op = ((idx + start) & 3).astype(np.uint16)

    xor = (c ^ kb) & 0xFF
    sub = (c + (256 - kb)) & 0xFF   # (c - kb) without signed-arithmetic fuss
    add = (c + kb) & 0xFF
    if decrypt:
        out = np.where(op == 1, sub, np.where(op == 2, add, xor))
    else:
        out = np.where(op == 1, add, np.where(op == 2, sub, xor))
    # pass-through rules only apply to op 0, the other ops are plain math
    if decrypt:
        keep = (op == 0) & ((c == 0) | (c == 0xFF) | (c == kb) | (xor == 0xFF))
    else:
        keep = (op == 0) & ((c == 0) | (c == 0xFF) | (c == kb) | (c == (kb ^ 0xFF)))
    out = np.where(keep, c, out)
    return out.astype(np.uint8).tobytes()


def _transform_pure(data, keystream, start, decrypt):
    # same thing without numpy, for machines that don't have it
    out = bytearray(len(data))
    for i, p in enumerate(data):
        pos = start + i
        kb = keystream[i & 0x1FF]
        op = pos & 3
        if decrypt:
            if op == 0:
                # ciphertext bytes the decoder would misinterpret stay as-is
                if p in (0x00, 0xFF) or p == kb or (p ^ kb) == 0xFF:
                    out[i] = p
                    continue
                out[i] = p ^ kb
            elif op == 1:
                out[i] = (p - kb) & 0xFF
            elif op == 2:
                out[i] = (p + kb) & 0xFF
            else:
                out[i] = p ^ kb
        else:
            # encoder mirror: plaintext that would land in a pass-through
            # case is emitted unchanged, everything else gets transformed
            if op == 0 and (p == 0x00 or p == 0xFF or p == kb or p == (kb ^ 0xFF)):
                out[i] = p
                continue
            if op == 0:
                out[i] = p ^ kb
            elif op == 1:
                out[i] = (p + kb) & 0xFF
            elif op == 2:
                out[i] = (p - kb) & 0xFF
            else:
                out[i] = p ^ kb
    return bytes(out)


def encrypt_rav(payload, table, value16=DEFAULT_VALUE16, key8=KEY8):
    """encrypt an audio payload (Ogg Vorbis bytes) into a complete .rav file."""
    hdr = build_header(value16, key8, table)
    _, _, keystream = derive(value16, hdr[0x13:0x1B], table)
    body = transform(payload, keystream, HEADER_LEN, decrypt=False)
    return hdr + body


def decrypt_rav(data, table):
    """decrypt a complete .rav file; returns key8/checksum/plaintext.

    plaintext = data[0x20:] with the cipher removed (the Ogg Vorbis payload).
    """
    if data[:16] != MAGIC:
        raise ValueError("not a Ravensburger RAV file (bad magic)")
    value16 = data[0x10] | (data[0x11] << 8)
    key8, checksum, keystream = derive(value16, data[0x13:0x1B], table)
    body = transform(data[HEADER_LEN:], keystream, HEADER_LEN, decrypt=True)
    return {"value16": value16, "key8": key8, "checksum": checksum, "plaintext": body}


def load_default_table():
    global _DEFAULT_TABLE
    if _DEFAULT_TABLE is None:
        _DEFAULT_TABLE = load_keytable()
    return _DEFAULT_TABLE
