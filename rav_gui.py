import math
import os
import queue
import struct
import sys
import threading
import wave
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from rav_tool import convert, ravcrypto

FORMATS = [
    ("mono 22050 Hz", 1, 22050),
    ("mono 44100 Hz", 1, 44100),
    ("stereo 44100 Hz", 2, 44100),
    ("mono 32000 Hz", 1, 32000),
    ("keep original", None, None),
]
QUALITIES = [("low", 4), ("medium", 5), ("high", 8)]
SOUNDS = [("softer, bass-tamed", -4.0, 70, True),
          ("much softer", -8.0, 70, True),
          ("original loudness", 0.0, 0, False)]


def find_tiptoi_drive():
    name = sys.platform
    if name == "win32":
        return _find_tiptoi_win32()
    elif name == "darwin":
        return _find_tiptoi_posix("/Volumes")
    else:
        for base in ("/media", "/mnt", "/run/media"):
            found = _find_tiptoi_posix(base)
            if found:
                return found
        home = os.path.expanduser("~")
        return _find_tiptoi_posix(os.path.join(home, "media"))


def _find_tiptoi_win32():
    import ctypes
    import string
    bitmask = ctypes.windll.kernel32.GetLogicalDrives()
    for letter in string.ascii_uppercase:
        if bitmask & 1:
            drive = f"{letter}:\\"
            try:
                vol = ctypes.create_unicode_buffer(256)
                ctypes.windll.kernel32.GetVolumeInformationW(
                    drive, vol, 256, None, None, None, None, 0)
                if vol.value and "tiptoi" in vol.value.lower():
                    return drive
            except Exception:
                pass
        bitmask >>= 1


def _find_tiptoi_posix(base):
    if not os.path.isdir(base):
        return
    try:
        for entry in os.listdir(base):
            if "tiptoi" in entry.lower():
                path = os.path.join(base, entry)
                if os.path.ismount(path):
                    return path
    except PermissionError:
        pass


def _songs_folder(pen_path):
    songs = os.path.join(pen_path, "songs")
    os.makedirs(songs, exist_ok=True)
    return songs


def _make_beep_wav(path):
    sr = 22050
    freq = 440
    beep = int(sr * 0.2)
    silence = int(sr * 0.3)
    with wave.open(path, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        for i in range(5):
            for s in range(beep):
                val = int(16000 * math.sin(2 * math.pi * freq * s / sr))
                wf.writeframes(struct.pack("<h", val))
            if i < 4:
                wf.writeframes(b"\x00\x00" * silence)
        wf.writeframes(b"\x00\x00" * silence)


class RavGui:
    def __init__(self, root):
        self.root = root
        self.running = False
        self.events = queue.Queue()
        self.pen_path = None
        self.confirmed_key8 = None
        self._testing_key = ""

        root.title("RAVage - make .rav files")
        root.resizable(False, False)

        self.var_input = tk.StringVar()
        self.var_outdir = tk.StringVar()
        self.var_format = tk.StringVar(value=FORMATS[0][0])
        self.var_quality = tk.StringVar(value=QUALITIES[1][0])
        self.var_sound = tk.StringVar(value=SOUNDS[0][0])
        self.var_key8 = tk.StringVar(value=ravcrypto.KEY8.decode())
        self.var_variant = tk.StringVar(value="standard (CommonI2)")
        self.auto_out = None

        self._build_test_screen()
        self._build_convert_screen()

        root.protocol("WM_DELETE_WINDOW", self._on_close)
        root.after(80, self._drain_events)
        root.after(300, self._center)
        root.after(400, self._start_pen_scan)

    def _build_test_screen(self):
        self.frame_test = tk.Frame(self.root, padx=14, pady=14)
        self.frame_test.pack(fill="both", expand=True)

        tk.Label(self.frame_test, text="RAVage: make .rav files",
                 font=("Segoe UI", 14, "bold")).pack(anchor="w")

        self.lbl_test_status = tk.Label(
            self.frame_test, text="looking for your tiptoi...",
            justify="left", wraplength=480)
        self.lbl_test_status.pack(anchor="w", pady=(8, 0))

        self.progress_test = ttk.Progressbar(self.frame_test, mode="indeterminate")
        self.progress_test.pack(fill="x", pady=(8, 0))

        self.lbl_test_result = tk.Label(
            self.frame_test, text="", justify="left", wraplength=480)
        self.lbl_test_result.pack(anchor="w", pady=(8, 0))

        row_btns = tk.Frame(self.frame_test)
        row_btns.pack(anchor="w", pady=(10, 0))
        self.btn_yes = tk.Button(row_btns, text="Yes, I heard 5 beeps",
                                 command=self._on_yes)
        self.btn_yes.pack(side="left", padx=(0, 8))
        self.btn_no = tk.Button(row_btns, text="No, I got an error",
                                command=self._on_no)
        self.btn_no.pack(side="left")
        self.btn_yes.pack_forget()
        self.btn_no.pack_forget()

        self.btn_retry = tk.Button(self.frame_test, text="retry",
                                   command=self._start_pen_scan)
        self.btn_retry.pack(anchor="w", pady=(10, 0))
        self.btn_retry.pack_forget()

        self.btn_ok = tk.Button(self.frame_test, text="OK",
                                command=self._show_convert_screen)
        self.btn_ok.pack(anchor="w", pady=(6, 0))
        self.btn_ok.pack_forget()

    def _build_convert_screen(self):
        self.frame_convert = tk.Frame(self.root, padx=14, pady=14)

        tk.Label(self.frame_convert, text="RAVage: make .rav files",
                 font=("Segoe UI", 14, "bold")).pack(anchor="w")
        self.lbl_pen_info = tk.Label(
            self.frame_convert, text="", fg="#006e2c", justify="left")
        self.lbl_pen_info.pack(anchor="w")
        tk.Label(self.frame_convert, text="pick an audio file (mp3, wav, m4a, flac, ...) "
                                         "and get a .rav the tiptoi pen can play",
                 justify="left").pack(anchor="w", pady=(2, 10))

        row1 = tk.Frame(self.frame_convert)
        row1.pack(fill="x")
        tk.Label(row1, text="audio file:").pack(side="left")
        self.ent_input = tk.Entry(row1, textvariable=self.var_input)
        self.ent_input.pack(side="left", fill="x", expand=True, padx=6)
        self.ent_input.bind("<Return>", lambda e: self._check_metadata(self.var_input.get()))
        self.var_input.trace_add("write", lambda *a: self.lbl_meta.config(text=""))
        tk.Button(row1, text="browse...", command=self._pick_input).pack(side="left")

        row2 = tk.Frame(self.frame_convert)
        row2.pack(fill="x", pady=(6, 0))
        tk.Label(row2, text="output folder:").pack(side="left")
        self.ent_outdir = tk.Entry(row2, textvariable=self.var_outdir)
        self.ent_outdir.pack(side="left", fill="x", expand=True, padx=6)
        tk.Button(row2, text="browse...", command=self._pick_outdir).pack(side="left")

        self.lbl_meta = tk.Label(self.frame_convert, text="", fg="#b06000",
                                 justify="left", wraplength=540)
        self.lbl_meta.pack(anchor="w", pady=(4, 0))

        row3 = tk.Frame(self.frame_convert)
        row3.pack(fill="x", pady=(10, 0))
        tk.Label(row3, text="format:").pack(side="left")
        self.cmb_format = ttk.Combobox(row3, textvariable=self.var_format,
                                       values=[f[0] for f in FORMATS],
                                       state="readonly", width=16)
        self.cmb_format.pack(side="left", padx=(4, 14))
        tk.Label(row3, text="quality:").pack(side="left")
        self.cmb_quality = ttk.Combobox(row3, textvariable=self.var_quality,
                                        values=[q[0] for q in QUALITIES],
                                        state="readonly", width=10)
        self.cmb_quality.pack(side="left", padx=(4, 14))
        tk.Label(row3, text="sound:").pack(side="left")
        self.cmb_sound = ttk.Combobox(row3, textvariable=self.var_sound,
                                       values=[s[0] for s in SOUNDS],
                                       state="readonly", width=20)
        self.cmb_sound.pack(side="left", padx=4)

        self.row_variant = tk.Frame(self.frame_convert)
        self.row_variant.pack(fill="x", pady=(8, 0))
        tk.Label(self.row_variant, text="variant:").pack(side="left")
        self.cmb_variant = ttk.Combobox(self.row_variant, textvariable=self.var_variant,
                                        values=["standard (CommonI2)",
                                                "Te4/Tn4 serial (CommonID)"],
                                        state="readonly", width=24)
        self.cmb_variant.pack(side="left", padx=6)
        self.cmb_variant.bind("<<ComboboxSelected>>", self._on_variant_change)
        tk.Label(self.row_variant, text="(auto-detected if pen was tested)",
                 fg="#555555").pack(side="left")

        self.btn_convert = tk.Button(self.frame_convert, text="convert", width=24,
                                     font=("Segoe UI", 11, "bold"),
                                     command=self._convert)
        self.btn_convert.pack(pady=(12, 4))

        self.progress = ttk.Progressbar(self.frame_convert, mode="indeterminate")
        self.progress.pack(fill="x", pady=(2, 0))
        self.lbl_status = tk.Label(self.frame_convert, text="ready.", anchor="w")
        self.lbl_status.pack(fill="x", pady=(4, 0))
        self.lbl_result = tk.Label(self.frame_convert, text="", fg="#006e2c",
                                   justify="left", wraplength=540)
        self.lbl_result.pack(fill="x", pady=(2, 0))
        self.btn_open = tk.Button(self.frame_convert, text="open folder",
                                  command=self._open_outdir)
        self.btn_open.pack(anchor="w", pady=(6, 0))
        self.btn_open.config(state="disabled")

        tk.Label(self.frame_convert, text="save the .rav wherever you like, then copy it to the pen. "
                                         "if you save it straight to the pen, unplug it when done.",
                 fg="#555555", justify="left", wraplength=540).pack(anchor="w", pady=(10, 0))

        self.btn_retest = tk.Button(self.frame_convert, text="re-test pen variant",
                                    command=self._back_to_test)
        self.btn_retest.pack(anchor="w", pady=(10, 0))

    def _show_convert_screen(self):
        self.frame_test.pack_forget()
        self.frame_convert.pack(fill="both", expand=True)
        if self.confirmed_key8:
            self.row_variant.pack_forget()
            self.lbl_pen_info.config(
                text=f"pen at {self.pen_path} - {self.confirmed_key8.decode()}")
        else:
            self.row_variant.pack(fill="x", pady=(8, 0))
            self.lbl_pen_info.config(text="")

    def _back_to_test(self):
        self.frame_convert.pack_forget()
        self.frame_test.pack(fill="both", expand=True)
        self.lbl_test_status.config(text="looking for your tiptoi...")
        self.lbl_test_result.config(text="")
        self.btn_yes.pack_forget()
        self.btn_no.pack_forget()
        self.btn_retry.pack_forget()
        self.progress_test.start(12)
        self._start_pen_scan()

    def _start_pen_scan(self):
        self.btn_retry.pack_forget()
        self.btn_yes.pack_forget()
        self.btn_no.pack_forget()
        self.btn_ok.pack_forget()
        self.lbl_test_status.config(text="looking for your tiptoi...")
        self.lbl_test_result.config(text="")
        self.progress_test.start(12)
        threading.Thread(target=self._scan_worker, daemon=True).start()

    def _scan_worker(self):
        pen = find_tiptoi_drive()
        self.events.put(("pen_found", pen))

    def _begin_variant_test(self):
        self.lbl_test_status.config(
            text=f"found pen at {self.pen_path}\ntesting CommonID first...")
        self.progress_test.start(12)
        threading.Thread(target=self._test_variant_worker,
                         args=("CommonID",), daemon=True).start()

    def _test_variant_worker(self, key_name):
        try:
            songs = _songs_folder(self.pen_path)
            dst = os.path.join(songs, "test.rav")
            tmp_wav = os.path.join(songs, "_test_beeps.tmp.wav")
            tmp_ogg = os.path.join(songs, "_test_beeps.tmp.ogg")

            self.events.put(("status", f"generating test beeps ({key_name})..."))
            _make_beep_wav(tmp_wav)

            self.events.put(("status", f"converting test beeps ({key_name})..."))
            convert.to_ogg(tmp_wav, tmp_ogg, gain_db=0.0, highpass_hz=0, limiter=False)

            with open(tmp_ogg, "rb") as fh:
                payload = fh.read()
            os.remove(tmp_wav)
            os.remove(tmp_ogg)

            key8 = key_name.encode("ascii")
            table = ravcrypto.load_keytable()
            rav = ravcrypto.encrypt_rav(payload, table, key8=key8)
            with open(dst, "wb") as fh:
                fh.write(rav)

            self.events.put(("variant_test_ready", key_name))
        except Exception as exc:
            self.events.put(("error", str(exc)))

    def _cleanup_test_rav(self):
        if self.pen_path:
            test = os.path.join(self.pen_path, "songs", "test.rav")
            try:
                os.remove(test)
            except OSError:
                pass

    def _on_yes(self):
        self.confirmed_key8 = self._testing_key.encode("ascii")
        self._cleanup_test_rav()
        self.progress_test.stop()
        self.root.title(f"RAVage - pen: {self.confirmed_key8.decode()}")
        self._show_convert_screen()

    def _on_no(self):
        self._cleanup_test_rav()
        if self._testing_key == "CommonID":
            self._testing_key = "CommonI2"
            self.lbl_test_status.config(
                text="unplug the pen, then plug it back in\nso we can try CommonI2...")
            self.lbl_test_result.config(text="")
            self.btn_yes.pack_forget()
            self.btn_no.pack_forget()
            self.progress_test.start(12)
            threading.Thread(target=self._rescan_for_pen, daemon=True).start()
        else:
            self.progress_test.stop()
            self.btn_yes.pack_forget()
            self.btn_no.pack_forget()
            self.lbl_test_status.config(
                text="couldn't figure out which pen you have.\n"
                     "you can still pick the variant on the next screen.")
            self.lbl_test_result.config(
                text="neither CommonID nor CommonI2 worked.\n"
                     "just pick it manually below.")
            self.confirmed_key8 = None
            self.btn_ok.pack(anchor="w", pady=(6, 0))

    def _rescan_for_pen(self):
        pen = find_tiptoi_drive()
        self.events.put(("pen_found_for_test2", pen))

    def _pick_input(self):
        path = filedialog.askopenfilename(
            title="choose an audio file",
            filetypes=[("audio files", "*.mp3 *.wav *.m4a *.flac *.ogg *.aac *.wma "
                                       "*.opus *.mp4 *.avi *.webm"),
                       ("all files", "*.*")])
        if not path:
            return
        self.var_input.set(path)
        stem = os.path.splitext(os.path.basename(path))[0] + ".rav"
        new_auto = os.path.join(os.path.dirname(path), stem)
        if self.auto_out is None or self.var_outdir.get() == "" or \
                os.path.join(self.var_outdir.get(), os.path.basename(self.auto_out)) == self.auto_out:
            self.auto_out = new_auto
            self.var_outdir.set(os.path.dirname(new_auto))
        self._check_metadata(path)

    def _pick_outdir(self):
        path = filedialog.askdirectory(title="choose output folder")
        if path:
            self.var_outdir.set(path)
            self.auto_out = None

    def _on_variant_change(self, _event=None):
        variant = self.var_variant.get()
        if "CommonID" in variant:
            self.var_key8.set("CommonID")
        else:
            self.var_key8.set("CommonI2")

    def _open_outdir(self):
        d = self.var_outdir.get()
        if d and os.path.isdir(d):
            os.startfile(d)

    def _result_path(self):
        stem = os.path.splitext(os.path.basename(self.var_input.get()))[0] + ".rav"
        return os.path.join(self.var_outdir.get(), stem)

    def _check_metadata(self, path):
        self.lbl_meta.config(text="")
        ff = convert.find_ffmpeg()
        if not ff or not os.path.isfile(path):
            return

        def work():
            try:
                is_yt, hits = convert.detect_youtube_metadata(ff, path)
                self.events.put(("meta", path, is_yt, hits))
            except Exception:
                pass

        threading.Thread(target=work, daemon=True).start()

    def _convert(self):
        if self.running:
            return
        src = self.var_input.get()
        if not src or not os.path.isfile(src):
            messagebox.showerror("RAVage", "pick an audio file first")
            return
        outdir = self.var_outdir.get()
        if not outdir:
            messagebox.showerror("RAVage", "pick an output folder")
            return
        os.makedirs(outdir, exist_ok=True)
        dst = self._result_path()

        channels, rate = next(f[1:] for f in FORMATS if f[0] == self.var_format.get())
        quality = next(q[1] for q in QUALITIES if q[0] == self.var_quality.get())
        gain_db, highpass_hz, limiter = \
            next(s[1:] for s in SOUNDS if s[0] == self.var_sound.get())
        key8_str = self.var_key8.get().strip()
        try:
            key8 = key8_str.encode("ascii")
        except UnicodeEncodeError:
            messagebox.showerror("RAVage", "key has to be ascii, like CommonI2")
            return
        if len(key8) != 8:
            messagebox.showerror("RAVage", "needs to be exactly 8 characters (CommonI2 or CommonID)")
            return

        self.running = True
        self.btn_convert.config(state="disabled")
        self.btn_open.config(state="disabled")
        self.lbl_result.config(text="")
        self.lbl_status.config(text="starting...")
        self.progress.start(12)

        threading.Thread(target=self._worker,
                         args=(src, dst, channels, rate, quality,
                               gain_db, highpass_hz, limiter, key8),
                         daemon=True).start()

    def _worker(self, src, dst, channels, rate, quality, gain_db, highpass_hz, limiter, key8):
        try:
            table = ravcrypto.load_keytable()
            tmp_ogg = dst[:-4] + ".tmp.ogg"

            def progress(sec, total):
                self.events.put(("progress", sec, total))

            convert.to_ogg(src, tmp_ogg, channels=channels, rate=rate,
                           vorbis_quality=quality, gain_db=gain_db,
                           highpass_hz=highpass_hz, limiter=limiter,
                           on_progress=progress)
            with open(tmp_ogg, "rb") as fh:
                payload = fh.read()
            os.remove(tmp_ogg)

            self.events.put(("status", "encrypting..."))
            rav = ravcrypto.encrypt_rav(payload, table, key8=key8)
            with open(dst, "wb") as fh:
                fh.write(rav)
            self.events.put(("done", dst, len(rav)))
        except Exception as exc:
            self.events.put(("error", str(exc)))

    def _drain_events(self):
        try:
            while True:
                ev = self.events.get_nowait()
                kind = ev[0]
                if kind == "progress":
                    sec, total = ev[1], ev[2]
                    if total:
                        self.lbl_status.config(
                            text=f"converting... {sec:.1f}s / {total:.1f}s")
                    else:
                        self.lbl_status.config(text=f"converting... {sec:.1f}s")
                elif kind == "status":
                    self.lbl_test_result.config(text=ev[1])
                    self.lbl_status.config(text=ev[1])
                elif kind == "pen_found":
                    self.progress_test.stop()
                    pen = ev[1]
                    if pen:
                        self.pen_path = pen
                        self.lbl_test_status.config(
                            text=f"found pen at {pen}\nstarting variant test...")
                        self._begin_variant_test()
                    else:
                        self.lbl_test_status.config(
                            text="couldn't find a tiptoi pen.\n"
                                 "plug it in and hit retry")
                        self.btn_retry.pack(anchor="w", pady=(10, 0))
                elif kind == "variant_test_ready":
                    self.progress_test.stop()
                    key_name = ev[1]
                    self._testing_key = key_name
                    self.lbl_test_status.config(
                        text=f"found pen at {self.pen_path}\n"
                             f"test.rav ({key_name}) is on the pen now.\n\n"
                             f"unplug the pen, then use the pen's player to play\n"
                             f"test.rav and listen for 5 beeps.")
                    self.lbl_test_result.config(
                        text="did you hear 5 beeps?")
                    self.btn_yes.pack(side="left", padx=(0, 8))
                    self.btn_no.pack(side="left")
                elif kind == "pen_found_for_test2":
                    pen = ev[1]
                    if pen:
                        self.pen_path = pen
                        self.lbl_test_status.config(
                            text=f"found pen at {pen}\ntesting CommonI2...")
                        self.progress_test.start(12)
                        threading.Thread(target=self._test_variant_worker,
                                         args=("CommonI2",), daemon=True).start()
                    else:
                        self.progress_test.stop()
                        self.lbl_test_status.config(
                            text="pen not found.\nplug it in and hit retry")
                        self.btn_retry.pack(anchor="w", pady=(10, 0))
                elif kind == "meta":
                    _, path, is_yt, hits = ev
                    if path != self.var_input.get():
                        continue
                    if is_yt:
                        self.lbl_meta.config(
                            text=f"looks like a youtube download ({', '.join(hits)} in "
                                 f"the file tags) - don't worry, the metadata gets "
                                 f"stripped automatically")
                    else:
                        self.lbl_meta.config(text="")
                elif kind == "done":
                    _, dst, size = ev
                    self.progress.stop()
                    self.running = False
                    self.btn_convert.config(state="normal")
                    self.btn_open.config(state="normal")
                    self.lbl_status.config(text="done!")
                    self.lbl_result.config(
                        text=f"saved {os.path.basename(dst)} ({size:,} bytes).\n\n"
                             f"now that you got your .rav file in your destination, copy it to the pen.\n"
                             f"or if you selected the pen as the destination, you can just unplug the pen "
                             f"and start playing! have fun!")
                elif kind == "error":
                    self.progress.stop()
                    self.progress_test.stop()
                    self.running = False
                    self.btn_convert.config(state="normal")
                    self.lbl_status.config(text="failed.")
                    self.lbl_result.config(text="")
                    self.lbl_test_result.config(text="")
                    messagebox.showerror("RAVage", f"something went wrong:\n\n{ev[1]}")
        except queue.Empty:
            pass
        self.root.after(80, self._drain_events)

    def _center(self):
        self.root.update_idletasks()
        w, h = self.root.winfo_width(), self.root.winfo_height()
        x = (self.root.winfo_screenwidth() - w) // 2
        y = (self.root.winfo_screenheight() - h) // 3
        self.root.geometry(f"+{x}+{y}")

    def _on_close(self):
        if self.running:
            if not messagebox.askyesno("RAVage", "still working. quit anyway?"):
                return
        self._cleanup_test_rav()
        self.root.destroy()


def main():
    root = tk.Tk()
    RavGui(root)
    root.mainloop()

if __name__ == "__main__":
    main()
