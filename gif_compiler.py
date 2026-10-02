import os, re
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

def target_size(first_path, max_width=None):
    w, h = load_rgb(first_path).size
    if max_width and w > max_width:
        h = max(1, round(h * max_width / w)); w = max_width
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

def render(paths, out_path, fps, slider, max_width=None, progress=None, cancel=None):
    size = target_size(paths[0], max_width)
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

if __name__ == "__main__":
    pass
