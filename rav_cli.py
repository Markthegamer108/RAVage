"""command line converter.

examples:
    python rav_cli.py convert "My Song.mp3" -o "My Song.rav"
    python rav_cli.py decrypt "Old MacDonald Had a Farm.rav" -o song.ogg
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from rav_tool import convert, ravcrypto  # noqa: E402


def cmd_convert(args):
    table = ravcrypto.load_keytable(args.table)
    if args.keep_ogg:
        tmp_ogg = args.ogg or (os.path.splitext(args.output)[0] + ".ogg")
    else:
        tmp_ogg = os.path.splitext(args.output)[0] + ".tmp.ogg"

    def progress(sec, total):
        if total:
            print(f"\rEncoding… {sec:6.1f}s / {total:6.1f}s ({100.0*sec/total:5.1f}%)",
                  end="", flush=True)
        else:
            print(f"\rEncoding… {sec:6.1f}s", end="", flush=True)

    t0 = time.time()
    convert.to_ogg(args.input, tmp_ogg, channels=args.channels, rate=args.rate,
                   vorbis_quality=args.quality,
                   gain_db=0.0 if args.no_tame else args.gain_db,
                   highpass_hz=0 if args.no_tame else 70,
                   limiter=not args.no_tame,
                   on_progress=progress)
    with open(tmp_ogg, "rb") as fh:
        payload = fh.read()
    if not args.keep_ogg:
        os.remove(tmp_ogg)
    rav = ravcrypto.encrypt_rav(payload, table, value16=args.value16)
    with open(args.output, "wb") as fh:
        fh.write(rav)
    print(f"\nDone in {time.time()-t0:.1f}s -> {args.output} ({len(rav):,} bytes)")
    print("Copy it to the pen's music folder, e.g. E:\\songs\\")


def cmd_decrypt(args):
    # mostly here for research/curiosity - decrypt a stock .rav and poke at
    # the ogg inside
    table = ravcrypto.load_keytable(args.table)
    with open(args.input, "rb") as fh:
        data = fh.read()
    info = ravcrypto.decrypt_rav(data, table)
    out = args.output or os.path.splitext(args.input)[0] + ".ogg"
    with open(out, "wb") as fh:
        fh.write(info["plaintext"])
    print(f"value16=0x{info['value16']:04X} key8={info['key8']!r} "
          f"checksum=0x{info['checksum']:04X}")
    print(f"Decrypted {len(info['plaintext']):,} bytes -> {out}")


def main():
    parser = argparse.ArgumentParser(
        description="Convert any audio to .rav for the Ravensburger tiptoi pen (3203L).")
    parser.add_argument("--table", help="path to keytable.bin (default: bundled)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("convert", help="audio file → .rav")
    p.add_argument("input", help="input audio file (mp3, wav, m4a, flac, ...)")
    p.add_argument("-o", "--output", required=True, help="output .rav file")
    p.add_argument("--rate", type=int, default=convert.PEN_RATE,
                   help=f"sample rate (default {convert.PEN_RATE})")
    p.add_argument("--channels", type=int, default=convert.PEN_CHANNELS,
                   help=f"channels, 1=mono (default {convert.PEN_CHANNELS})")
    p.add_argument("--quality", type=int, default=5, help="Vorbis quality 0-10 (default 5)")
    p.add_argument("--gain-db", type=float, default=-4.0,
                   help="overall gain in dB (default -4.0; 0 = no gain change)")
    p.add_argument("--no-tame", action="store_true",
                   help="skip the high-pass filter and limiter (original loudness)")
    p.add_argument("--value16", type=lambda s: int(s, 0), default=ravcrypto.DEFAULT_VALUE16,
                   help="header value16 (default 0x78)")
    p.add_argument("--keep-ogg", action="store_true", help="keep the intermediate .ogg file")
    p.add_argument("--ogg", help="path for the intermediate .ogg (with --keep-ogg)")

    p = sub.add_parser("decrypt", help=".rav → Ogg Vorbis (research)")
    p.add_argument("input", help="input .rav file")
    p.add_argument("-o", "--output", help="output .ogg file (default: alongside input)")

    args = parser.parse_args()
    (cmd_convert if args.cmd == "convert" else cmd_decrypt)(args)


if __name__ == "__main__":
    main()
