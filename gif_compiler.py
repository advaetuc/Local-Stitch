import os, re
import queue
import threading
import tkinter.filedialog as filedialog

import customtkinter
from PIL import Image, ImageOps

EXTS = {".png", ".jpg", ".jpeg", ".webp"}
BG = (255, 255, 255)
DITHER = Image.Dither.NONE
SAMPLE_FRAMES = 12
MIN_FPS, MAX_FPS = 1, 50

def natural_key(name: str):
    return ([int(t) if t.isdigit() else t.lower() for t in re.split(r"([0-9]+)", name)], name)

def list_images(folder):
    names = [n for n in os.listdir(folder)
             if os.path.splitext(n)[1].lower() in EXTS and os.path.isfile(os.path.join(folder, n))]
    return [os.path.join(folder, n) for n in sorted(names, key=natural_key)]

def color_count(s: int) -> int:
    s = max(0, min(100, int(s)))
    if s <= 25:
        return 256
    if s <= 75:
        return round(256 - (s - 25) / 50 * 192)    # 252 .. 64
    return max(16, round(63 - (s - 76) / 24 * 47))  # 63 .. 16

def frame_durations(fps: float, n: int):
    ideal = 1000.0 / fps
    out, prev = [], 0
    for i in range(1, n + 1):
        target = int(i * ideal / 10 + 0.5) * 10
        out.append(target - prev)
        prev = target
    return out

def load_rgb(path):
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im)
        if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
            rgba = im.convert("RGBA")
            canvas = Image.new("RGBA", rgba.size, BG + (255,))
            return Image.alpha_composite(canvas, rgba).convert("RGB")
        return im.convert("RGB")

def fit_frame(path, size):
    im = load_rgb(path)
    if im.size != size:
        im = ImageOps.pad(im, size, method=Image.Resampling.LANCZOS, color=BG)
    return im

def target_size(first_path, scale: float = 1.0):
    orig_w, orig_h = load_rgb(first_path).size
    w = max(1, round(orig_w * scale))
    h = max(1, round(orig_h * scale))
    return (w, h)

def build_palette(paths, size, colors):
    if len(paths) > SAMPLE_FRAMES:
        idx = sorted({round(i * (len(paths) - 1) / (SAMPLE_FRAMES - 1)) for i in range(SAMPLE_FRAMES)})
    else:
        idx = list(range(len(paths)))
    tw = min(size[0], 256); th = max(1, round(size[1] * tw / size[0]))
    montage = Image.new("RGB", (tw * len(idx), th), BG)
    for k, i in enumerate(idx):
        thumb = fit_frame(paths[i], size).resize((tw, th), Image.Resampling.LANCZOS)
        montage.paste(thumb, (k * tw, 0))
    return montage.quantize(colors, method=Image.Quantize.MEDIANCUT)

def render(paths, out_path, fps, slider, scale: float = 1.0, progress=None, cancel=None):
    size = target_size(paths[0], scale)
    ref = build_palette(paths, size, color_count(slider))
    durs = frame_durations(fps, len(paths))
    n = len(paths)

    def prepare(i):
        if cancel and cancel.is_set():
            raise InterruptedError
        fr = fit_frame(paths[i], size).quantize(palette=ref, dither=DITHER)
        if progress:
            progress(i + 1, n)
        return fr

    first = prepare(0)
    tmp = out_path + ".tmp"
    try:
        first.save(tmp, format="GIF", save_all=True,
                   append_images=(prepare(i) for i in range(1, n)),
                   duration=durs, loop=0, optimize=True)
        os.replace(tmp, out_path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise

class App(customtkinter.CTk):
    def __init__(self):
        customtkinter.set_appearance_mode("dark")
        customtkinter.set_default_color_theme("blue")
        super().__init__()

        self.title("Local Stitch")
        self.geometry("450x720")
        self.resizable(False, False)

        self.paths = []
        self.preview_image = None
        self._queue = None
        self._cancel = None
        self._worker = None
        self._rendering = False
        self._closing = False
        self._close_timeout = None
        self._resize_count = 0

        self.folder_button = customtkinter.CTkButton(
            self, text="Choose Image Directory", command=self._choose_folder
        )
        self.folder_button.pack(fill="x", padx=16, pady=(16, 8))

        self.path_label = customtkinter.CTkLabel(
            self, text="Path: —\n0 images found", justify="left", anchor="w",
            wraplength=418
        )
        self.path_label.pack(fill="x", padx=16, pady=8)

        self.preview_label = customtkinter.CTkLabel(
            self, text="Choose a directory to preview its first image.", width=200,
            height=200
        )
        self.preview_label.pack(padx=16, pady=8)

        self.fps_entry = customtkinter.CTkEntry(
            self, placeholder_text="FPS (1–50)", width=180
        )
        self.fps_entry.insert(0, "24")
        self.fps_entry.pack(fill="x", padx=16, pady=(8, 4))
        self.fps_entry.bind("<KeyRelease>", self._update_effective_speed)

        self.speed_label = customtkinter.CTkLabel(
            self, text="Effective: 24 fps (GIF timing is in 10 ms steps)",
            anchor="w"
        )
        self.speed_label.pack(fill="x", padx=16, pady=(0, 8))

        self.compression_slider = customtkinter.CTkSlider(
            self, from_=0, to=100, number_of_steps=100,
            command=self._update_compression
        )
        self.compression_slider.set(20)
        self.compression_slider.pack(fill="x", padx=16, pady=(8, 4))

        self.compression_label = customtkinter.CTkLabel(
            self, text=f"Compression 20% → {color_count(20)} colors", anchor="w"
        )
        self.compression_label.pack(fill="x", padx=16, pady=(0, 8))

        self.scale_slider = customtkinter.CTkSlider(
            self, from_=10, to=100, number_of_steps=90,
            command=self._update_scale
        )
        self.scale_slider.set(100)
        self.scale_slider.pack(fill="x", padx=16, pady=(8, 4))

        self.scale_label = customtkinter.CTkLabel(
            self, text="Scale: 100%", anchor="w"
        )
        self.scale_label.pack(fill="x", padx=16, pady=(0, 8))

        self.progress_bar = customtkinter.CTkProgressBar(self)
        self.progress_bar.set(0)
        self.progress_bar.pack(fill="x", padx=16, pady=(8, 4))

        self.status_label = customtkinter.CTkLabel(
            self, text="No supported images found", anchor="w", wraplength=418
        )
        self.status_label.pack(fill="x", padx=16, pady=8)

        self.render_button = customtkinter.CTkButton(
            self, text="RENDER & EXPORT GIF", command=self._start_render,
            state="disabled"
        )
        self.render_button.pack(fill="x", padx=16, pady=(8, 4))

        self.cancel_button = customtkinter.CTkButton(
            self, text="Cancel", command=self._cancel_render, state="disabled"
        )
        self.cancel_button.pack(fill="x", padx=16, pady=(4, 16))

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _set_status(self, text, error=False):
        self.status_label.configure(
            text=text, text_color="#ff5c5c" if error else "white"
        )

    def _truncate_path(self, path, limit=54):
        if len(path) <= limit:
            return path
        keep = (limit - 1) // 2
        return f"{path[:keep]}…{path[-keep:]}"

    def _choose_folder(self):
        folder = filedialog.askdirectory(parent=self)
        if not folder:
            return

        try:
            paths = list_images(folder)
        except OSError as exc:
            self.paths = []
            self.path_label.configure(text=f"Path: {self._truncate_path(folder)}\n0 images found")
            self.render_button.configure(state="disabled")
            self._set_status(f"{type(exc).__name__}: {exc}", error=True)
            return

        self.paths = paths
        self.path_label.configure(
            text=f"Path: {self._truncate_path(folder)}\n{len(paths)} images found"
        )
        self.preview_image = None
        self.preview_label.configure(image=None, text="")
        self._resize_count = 0

        if not paths:
            self.render_button.configure(state="disabled")
            self.preview_label.configure(text="No supported images found.")
            self._set_status("No supported images found", error=True)
            return

        try:
            with Image.open(paths[0]) as first:
                preview = ImageOps.exif_transpose(first).convert("RGBA")
                preview.thumbnail((200, 200), Image.Resampling.LANCZOS)
                self.preview_image = customtkinter.CTkImage(
                    light_image=preview, dark_image=preview, size=preview.size
                )
                self.preview_label.configure(image=self.preview_image, text="")
                reference_size = ImageOps.exif_transpose(first).size
        except Exception as exc:
            self.preview_label.configure(text="Preview unavailable.")
            self._set_status(f"{type(exc).__name__}: {exc}", error=True)
            reference_size = None

        if reference_size is not None:
            for path in paths[1:]:
                try:
                    with Image.open(path) as frame:
                        if ImageOps.exif_transpose(frame).size != reference_size:
                            self._resize_count += 1
                except Exception:
                    # Rendering reports unreadable frames from the worker.
                    continue

        self.render_button.configure(state="normal")
        if len(paths) == 1:
            self._set_status("Single frame, GIF will not animate")
        elif self._resize_count:
            self._set_status(f"{self._resize_count} frames resized")
        elif reference_size is not None:
            self._set_status("Ready to render")

    def _update_effective_speed(self, _event=None):
        value = self.fps_entry.get().strip()
        try:
            fps = float(value)
            if not 1 <= fps <= 50:
                raise ValueError
        except ValueError:
            self.speed_label.configure(text="FPS must be a number between 1 and 50")
            return
        shown = f"{fps:g}"
        self.speed_label.configure(
            text=f"Effective: {shown} fps (GIF timing is in 10 ms steps)"
        )

    def _update_compression(self, value):
        slider = int(round(value))
        self.compression_label.configure(
            text=f"Compression {slider}% → {color_count(slider)} colors"
        )

    def _update_scale(self, value):
        self.scale_label.configure(text=f"Scale: {int(round(value))}%")

    def _validated_inputs(self):
        value = self.fps_entry.get().strip()
        try:
            fps = float(value)
        except ValueError:
            self._set_status("FPS must be a number between 1 and 50", error=True)
            return None
        if not 1 <= fps <= 50:
            self._set_status("FPS must be a number between 1 and 50", error=True)
            return None

        if not self.paths:
            self._set_status("No supported images found", error=True)
            return None
        return fps

    def _start_render(self):
        if self._rendering:
            return
        values = self._validated_inputs()
        if values is None:
            return
        fps = values
        out_path = filedialog.asksaveasfilename(
            parent=self, defaultextension=".gif",
            filetypes=(("GIF image", "*.gif"), ("All files", "*.*"))
        )
        if not out_path:
            return

        self._rendering = True
        self._set_inputs_enabled(False)
        self.cancel_button.configure(state="normal")
        self.progress_bar.set(0)
        self._queue = queue.Queue()
        self._cancel = threading.Event()
        paths = list(self.paths)
        slider = int(round(self.compression_slider.get()))
        scale = int(round(self.scale_slider.get())) / 100.0

        def worker():
            try:
                render(
                    paths, out_path, fps, slider, scale=scale,
                    progress=lambda cur, total: self._queue.put(("progress", cur, total)),
                    cancel=self._cancel
                )
                self._queue.put(("done", out_path))
            except InterruptedError:
                self._queue.put(("cancelled",))
            except Exception as exc:
                self._queue.put(("error", f"{type(exc).__name__}: {exc}"))

        self._worker = threading.Thread(target=worker, daemon=True)
        self._worker.start()
        self.after(50, self._poll)

    def _set_inputs_enabled(self, enabled):
        state = "normal" if enabled else "disabled"
        for widget in (
            self.folder_button, self.fps_entry, self.compression_slider,
            self.scale_slider, self.render_button
        ):
            widget.configure(state=state)

    def _cancel_render(self):
        if self._cancel is not None:
            self._cancel.set()
            self.cancel_button.configure(state="disabled")

    def _poll(self):
        latest_progress = None
        terminal = None
        while True:
            try:
                message = self._queue.get_nowait()
            except queue.Empty:
                break
            if message[0] == "progress":
                latest_progress = message
            else:
                terminal = message

        if latest_progress is not None and terminal is None:
            _, cur, total = latest_progress
            self.progress_bar.set(cur / total if total else 0)
            self._set_status(f"Processing frame {cur} of {total}…")

        if terminal is not None:
            kind = terminal[0]
            self._rendering = False
            self._set_inputs_enabled(True)
            self.cancel_button.configure(state="disabled")
            self.progress_bar.set(0)
            if kind == "done":
                self._set_status(f"Done: {terminal[1]}")
            elif kind == "cancelled":
                self._set_status("Cancelled")
            else:
                self._set_status(terminal[1], error=True)

            self._cancel = None
            self._queue = None
            self._worker = None
            if self._closing:
                self.destroy()
            return

        self.after(50, self._poll)

    def _on_close(self):
        if not self._rendering:
            self.destroy()
            return
        self._closing = True
        self._cancel.set()
        self.cancel_button.configure(state="disabled")
        self._close_timeout = self.after(2000, self.destroy)


if __name__ == "__main__":
    app = App()
    app.mainloop()
