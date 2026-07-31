"""audio conversion helpers.

ffmpeg does the heavy lifting: anything it can decode gets turned into
Ogg Vorbis at the pen's native settings (mono 22050 Hz).

ffmpeg is found via the RAV_FFMPEG env var, then PATH, then the static
binary that ships with imageio-ffmpeg (if installed).
"""

import os
import re
import shutil
import subprocess

PEN_CHANNELS = 1
PEN_RATE = 22050

# youtube rips embed a big metadata block in the file tags (title, artist,
# a giant "synopsis" with links...). the resulting vorbis comment header
# gets too big for the pen's parser - a ~9 KB header makes it skip the
# file, ~3.6 KB works. so we strip all metadata, and these markers just
# let the gui warn the user that a file is a youtube download.
YOUTUBE_MARKERS = ("youtube", "youtu.be", "ytimg", "stream now", "apple.co",
                   "spoti.fi", "instagram.com", "twitter.com", "discord.gg",
                   "music video", "behind the scenes", "lyrics", "official",
                   "\u25b6")
META_FIELDS = re.compile(r"^\s*(?:title|artist|album|date|synopsis|description"
                         r"|genre|comment|major_brand)\s*:")


def find_ffmpeg():
    exe = os.environ.get("RAV_FFMPEG")
    if exe and os.path.isfile(exe):
        return exe
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def probe_duration(ffmpeg, src):
    """read the input length from `ffmpeg -i` stderr, no ffprobe needed."""
    try:
        p = subprocess.run([ffmpeg, "-hide_banner", "-i", src],
                           capture_output=True, timeout=30)
        m = re.search(rb"Duration: (\d+):(\d+):(\d+)\.(\d+)", p.stderr)
        if m:
            h, mn, s, fr = (int(x) for x in m.groups())
            return h * 3600 + mn * 60 + s + fr / 100.0
    except Exception:
        pass
    return None


def detect_youtube_metadata(ffmpeg, src):
    """heuristic: does this file carry youtube-ish metadata?

    only inspects the file's own tags (not the filename), returns the
    markers we found. purely cosmetic - metadata gets stripped anyway.
    """
    try:
        p = subprocess.run([ffmpeg, "-hide_banner", "-i", src],
                           capture_output=True, timeout=30)
    except Exception:
        return False, []
    meta = " ".join(line.decode("utf-8", errors="replace").lower()
                    for line in p.stderr.splitlines()
                    if META_FIELDS.match(line.decode("utf-8", errors="replace")))
    hits = [m for m in YOUTUBE_MARKERS if m in meta]
    return bool(hits), hits


def to_ogg(src, dst, channels=PEN_CHANNELS, rate=PEN_RATE,
           vorbis_quality=5, gain_db=-4.0, highpass_hz=70, limiter=True,
           on_progress=None):
    """transcode src to an Ogg Vorbis file at dst.

    the default chain tames the audio for the pen's tiny speaker: a
    high-pass at 70 Hz (sub-bass just muddies it), -4 dB, and a limiter
    so nothing clips. pass gain_db=0, highpass_hz=0, limiter=False for
    the untouched stream.

    on_progress(seconds_encoded, total_seconds) is called periodically.
    """
    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        raise RuntimeError(
            "ffmpeg not found. Install it (e.g. `winget install ffmpeg`), "
            "add it to PATH, set the RAV_FFMPEG env var, or `pip install "
            "imageio-ffmpeg` to bundle a static build.")
    total = probe_duration(ffmpeg, src)
    filters = []
    if highpass_hz:
        filters.append(f"highpass=f={highpass_hz}")
    if gain_db:
        filters.append(f"volume={gain_db}dB")
    if limiter:
        filters.append("alimiter=limit=0.891")
    args = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-i", src, "-vn", "-ac", str(channels), "-ar", str(rate),
            "-c:a", "libvorbis", "-q:a", str(vorbis_quality),
            "-map_metadata", "-1", "-progress", "pipe:1", "-nostats"]
    if filters:
        args += ["-af", ",".join(filters)]
    args.append(dst)
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        while True:
            line = proc.stdout.readline()
            if not line:
                break
            if line.startswith(b"out_time_us="):
                try:
                    us = int(line.split(b"=", 1)[1])
                    if on_progress:
                        on_progress(us / 1e6, total)
                except ValueError:
                    pass
    finally:
        stderr = proc.stderr.read().decode("utf-8", errors="replace")
        rc = proc.wait()
    if rc != 0:
        raise RuntimeError(f"ffmpeg failed (exit {rc}):\n{stderr[-800:].strip()}")
    if on_progress:
        on_progress(total or 0, total)
    return os.path.getsize(dst)
