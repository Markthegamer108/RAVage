"""RAV maker - turns any audio file into a .rav for the tiptoi pen.

Run:  python rav_gui.py     (or double-click run_gui.bat)
"""

import os
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from rav_tool import convert, ravcrypto  # noqa: E402

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


class RavGui:
    def __init__(self, root):
        self.root = root
        self.running = False
        self.events = queue.Queue()

        root.title("make .rav files")
        root.resizable(False, False)

        self.var_input = tk.StringVar()
        self.var_outdir = tk.StringVar()
        self.var_format = tk.StringVar(value=FORMATS[0][0])
        self.var_quality = tk.StringVar(value=QUALITIES[1][0])
        self.var_sound = tk.StringVar(value=SOUNDS[0][0])
        self.auto_out = None

        self._build()
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        root.after(80, self._drain_events)
        root.after(300, self._center)

    def _build(self):
        pad = {"padx": 12, "pady": 6}
        main = tk.Frame(self.root, padx=14, pady=14)
        main.pack(fill="both", expand=True)

        tk.Label(main, text="make .rav files", font=("Segoe UI", 14, "bold")).pack(anchor="w")
        tk.Label(main, text="pick an audio file (mp3, wav, m4a, flac, ...) "
                            "and get a .rav the tiptoi pen can play",
                 justify="left").pack(anchor="w", pady=(2, 10))

        row1 = tk.Frame(main)
        row1.pack(fill="x")
        tk.Label(row1, text="audio file:").pack(side="left")
        self.ent_input = tk.Entry(row1, textvariable=self.var_input)
        self.ent_input.pack(side="left", fill="x", expand=True, padx=6)
        self.ent_input.bind("<Return>", lambda e: self._check_metadata(self.var_input.get()))
        self.var_input.trace_add("write", lambda *a: self.lbl_meta.config(text=""))
        tk.Button(row1, text="browse...", command=self._pick_input).pack(side="left")

        row2 = tk.Frame(main)
        row2.pack(fill="x", pady=(6, 0))
        tk.Label(row2, text="output folder:").pack(side="left")
        self.ent_outdir = tk.Entry(row2, textvariable=self.var_outdir)
        self.ent_outdir.pack(side="left", fill="x", expand=True, padx=6)
        tk.Button(row2, text="browse...", command=self._pick_outdir).pack(side="left")

        self.lbl_meta = tk.Label(main, text="", fg="#b06000", justify="left", wraplength=540)
        self.lbl_meta.pack(anchor="w", pady=(4, 0))

        row3 = tk.Frame(main)
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

        self.btn_convert = tk.Button(main, text="convert", width=24,
                                     font=("Segoe UI", 11, "bold"),
                                     command=self._convert)
        self.btn_convert.pack(pady=(12, 4))

        self.progress = ttk.Progressbar(main, mode="indeterminate")
        self.progress.pack(fill="x", pady=(2, 0))
        self.lbl_status = tk.Label(main, text="ready.", anchor="w")
        self.lbl_status.pack(fill="x", pady=(4, 0))
        self.lbl_result = tk.Label(main, text="", fg="#006e2c", justify="left", wraplength=540)
        self.lbl_result.pack(fill="x", pady=(2, 0))
        self.btn_open = tk.Button(main, text="open folder", command=self._open_outdir)
        self.btn_open.pack(anchor="w", pady=(6, 0))
        self.btn_open.config(state="disabled")

        tk.Label(main, text="copy the .rav into the songs folder of the pen, "
                            "e.g. E:\\songs\\",
                 fg="#555555", justify="left").pack(anchor="w", pady=(10, 0))

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
            messagebox.showerror("rav maker", "pick an audio file first.")
            return
        outdir = self.var_outdir.get()
        if not outdir:
            messagebox.showerror("rav maker", "pick an output folder.")
            return
        os.makedirs(outdir, exist_ok=True)
        dst = self._result_path()

        channels, rate = next(f[1:] for f in FORMATS if f[0] == self.var_format.get())
        quality = next(q[1] for q in QUALITIES if q[0] == self.var_quality.get())
        gain_db, highpass_hz, limiter = \
            next(s[1:] for s in SOUNDS if s[0] == self.var_sound.get())

        self.running = True
        self.btn_convert.config(state="disabled")
        self.btn_open.config(state="disabled")
        self.lbl_result.config(text="")
        self.lbl_status.config(text="starting...")
        self.progress.start(12)

        threading.Thread(target=self._worker,
                         args=(src, dst, channels, rate, quality,
                               gain_db, highpass_hz, limiter),
                         daemon=True).start()

    def _worker(self, src, dst, channels, rate, quality, gain_db, highpass_hz, limiter):
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
            rav = ravcrypto.encrypt_rav(payload, table)
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
                    self.lbl_status.config(text=ev[1])
                elif kind == "meta":
                    _, path, is_yt, hits = ev
                    if path != self.var_input.get():
                        continue
                    if is_yt:
                        self.lbl_meta.config(
                            text=f"looks like a youtube download ({', '.join(hits)} in "
                                 f"the file tags) - don't worry, the metadata gets "
                                 f"stripped automatically.")
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
                        text=f"saved {os.path.basename(dst)} ({size:,} bytes). "
                             f"copy it to E:\\songs\\ on the pen.")
                elif kind == "error":
                    self.progress.stop()
                    self.running = False
                    self.btn_convert.config(state="normal")
                    self.lbl_status.config(text="failed.")
                    self.lbl_result.config(text="")
                    messagebox.showerror("rav maker", f"that didn't work:\n\n{ev[1]}")
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
            if not messagebox.askyesno("rav maker", "still converting. quit anyway?"):
                return
        self.root.destroy()


def main():
    root = tk.Tk()
    RavGui(root)
    root.mainloop()


if __name__ == "__main__":
    main()
