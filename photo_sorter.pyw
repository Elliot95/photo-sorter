"""
Photo Sorter - flick through a folder of photos and sort each one with a click or a key.

Round 1: Keep / Delete
Round 2: open the Keep folder and sort into your own folders (Friends, Holiday, Cats...)

Photos are COPIED, never moved or deleted, so the originals are always safe.
Progress is saved after every photo: close it any time and carry on later.
"""

import io
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from tkinter import filedialog, messagebox, simpledialog

try:
    from PIL import Image, ImageOps, ImageTk
except ImportError:
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror(
        "Photo Sorter",
        "Pillow isn't installed.\n\nDouble-click Install.bat first, then try again.",
    )
    sys.exit(1)

try:  # iPhone photos (.heic) - optional
    import pillow_heif

    pillow_heif.register_heif_opener()
    HEIC_OK = True
except ImportError:
    HEIC_OK = False

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff", ".webp"}
if HEIC_OK:
    IMAGE_EXTS |= {".heic", ".heif"}

# Videos: shown as a still frame, played in the normal Windows player (needs imageio-ffmpeg)
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".wmv", ".3gp", ".mts", ".m2ts", ".webm", ".mpg", ".mpeg"}
LIVE_EXTS = {".mov", ".mp4"}  # iPhone Live Photo clips share a name with their photo

SETTINGS_FILE = os.path.join(os.path.expanduser("~"), ".photo_sorter_settings.json")
LOG_NAME = ".photo_sorter_log.jsonl"
DEFAULT_CATEGORIES = "Friends\nHoliday\nCats\nFamily\nOther"

BG = "#1e1e1e"
PANEL = "#2b2b2b"
FG = "#eeeeee"
MUTED = "#9a9a9a"
GREEN = "#2e8b57"
RED = "#b23b3b"
BLUE = "#3a6ea5"


# ---------------------------------------------------------------- helpers

def load_settings():
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_settings(data):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def norm(path):
    return os.path.normcase(os.path.abspath(path))


def is_video(path):
    return os.path.splitext(path)[1].lower() in VIDEO_EXTS


def _collect(dirpath, names, found, companions):
    photos, videos = {}, []
    for name in names:
        stem, ext = os.path.splitext(name)
        if ext.lower() in IMAGE_EXTS:
            photos.setdefault(stem.lower(), name)
            found.append(os.path.join(dirpath, name))
        elif ext.lower() in VIDEO_EXTS:
            videos.append(name)
    for name in videos:
        stem, ext = os.path.splitext(name)
        if ext.lower() in LIVE_EXTS and stem.lower() in photos:
            # Live Photo: the clip travels with its photo instead of being sorted on its own
            companions[norm(os.path.join(dirpath, photos[stem.lower()]))] = os.path.join(dirpath, name)
        else:
            found.append(os.path.join(dirpath, name))


def find_photos(folder, include_subfolders, skip_folder):
    """-> (photos and videos to sort, {photo: its Live Photo clip})"""
    skip = norm(skip_folder)
    found, companions = [], {}
    if include_subfolders:
        for dirpath, dirnames, filenames in os.walk(folder):
            # never scan the output folder if it sits inside the source folder
            dirnames[:] = [
                d for d in dirnames
                if norm(os.path.join(dirpath, d)) != skip and not d.startswith(".")
            ]
            _collect(dirpath, filenames, found, companions)
    else:
        names = [n for n in os.listdir(folder) if os.path.isfile(os.path.join(folder, n))]
        _collect(folder, names, found, companions)
    found.sort(key=lambda p: p.lower())
    return found, companions


def read_log(log_path):
    """Replay the log -> {source path: (category, copied-to path)}."""
    done = {}
    if not os.path.exists(log_path):
        return done
    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if "undo" in rec:
                done.pop(norm(rec["undo"]), None)
            else:
                done[norm(rec["src"])] = (rec["cat"], rec["dest"])
    return done


def append_log(log_path, rec):
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")


def unhide_file(path):
    """v1.4 hid the progress record; keep it visible so people can see what happened."""
    try:
        import ctypes
        attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
        if attrs != -1 and attrs & 0x02:
            ctypes.windll.kernel32.SetFileAttributesW(str(path), attrs & ~0x02)
    except Exception:
        pass


TOP_SPACES = ("Photos", "Videos")


def space_of(cat):
    """Log entries from before v1.4 had photo folders at the top level - they now live in Photos."""
    first = cat.split(os.sep)[0].split("/")[0]
    return cat if first in TOP_SPACES else os.path.join("Photos", cat)


def move_into_photos(out, done):
    """One-off tidy-up of a folder sorted with an older version: Keep, Delete, Holiday... -> Photos\\..."""
    legacy = {c.split(os.sep)[0] for c, _ in done.values() if c.split(os.sep)[0] not in TOP_SPACES}
    for name in legacy:
        old = os.path.join(out, name)
        if not os.path.isdir(old):
            continue
        new = os.path.join(out, "Photos", name)
        if not os.path.exists(new):
            os.makedirs(os.path.dirname(new), exist_ok=True)
            shutil.move(old, new)
            continue
        for dirpath, _, files in os.walk(old):  # merge into an existing Photos\\name
            target = os.path.join(new, os.path.relpath(dirpath, old))
            os.makedirs(target, exist_ok=True)
            for f in files:
                shutil.move(os.path.join(dirpath, f), unique_dest(target, f))
        shutil.rmtree(old, ignore_errors=True)


def unique_dest(folder, filename, also_exts=()):
    """A free name in folder (also free for a Live Photo clip with the same name)."""
    base, ext = os.path.splitext(filename)
    n = 0
    while True:
        stem = base if n == 0 else f"{base} ({n})"
        if not os.path.exists(os.path.join(folder, stem + ext)) and not any(
                os.path.exists(os.path.join(folder, stem + e)) for e in also_exts):
            return os.path.join(folder, stem + ext)
        n += 1


def _num(v):
    try:
        return float(v)
    except Exception:
        try:
            return v[0] / v[1]
        except Exception:
            return None


def _clean(v):
    if isinstance(v, bytes):
        v = v.decode("utf-8", "ignore")
    return str(v).strip("\x00 ").strip()


def _gps(gps):
    def deg(vals, ref):
        d, m, s = (_num(x) for x in vals)
        val = d + m / 60 + s / 3600
        return -val if ref in ("S", "W") else val
    return fmt_latlon(deg(gps[2], _clean(gps.get(1, "N"))), deg(gps[4], _clean(gps.get(3, "E"))))


def fmt_latlon(lat, lon):
    return f"{abs(lat):.5f}° {'S' if lat < 0 else 'N'}, {abs(lon):.5f}° {'W' if lon < 0 else 'E'}"


def read_metadata(path, img):
    """Everything worth knowing about a photo, as (label, value) pairs for the side panel."""
    meta = []
    st = os.stat(path)
    size = st.st_size
    meta.append(("File", os.path.basename(path)))
    meta.append(("Type", (img.format if img else os.path.splitext(path)[1][1:]).upper()))
    meta.append(("Size", f"{size / 1048576:.1f} MB" if size >= 1048576 else f"{size / 1024:.0f} KB"))
    if img is None:
        meta.append(("Modified", datetime.fromtimestamp(st.st_mtime).strftime("%d %b %Y, %H:%M")))
        return meta, ""
    w, h = img.size
    meta.append(("Dimensions", f"{w:,} × {h:,}  ({w * h / 1e6:.1f} MP)"))

    exif, ex = {}, {}
    try:
        exif = img.getexif()
        ex = exif.get_ifd(0x8769)
    except Exception:
        pass

    taken = ex.get(36867) or exif.get(306)
    if taken:
        try:
            caption = datetime.strptime(_clean(taken)[:19], "%Y:%m:%d %H:%M:%S").strftime("%d %b %Y, %H:%M")
        except Exception:
            caption = _clean(taken)
        meta.insert(0, ("Date taken", caption))
    else:
        caption = datetime.fromtimestamp(st.st_mtime).strftime("%d %b %Y (file date)")
        meta.insert(0, ("Date taken", "Unknown - file date " + caption.split(" (")[0]))

    make, model = _clean(exif.get(271, "")), _clean(exif.get(272, ""))
    if model and make and not model.lower().startswith(make.lower().split()[0]):
        model = f"{make} {model}"
    if model or make:
        meta.append(("Camera", model or make))
    if ex.get(0xA434):
        meta.append(("Lens", _clean(ex[0xA434])))

    settings = []
    f = _num(ex.get(0x829D))
    if f:
        settings.append(f"f/{f:.1f}".replace(".0", ""))
    t = _num(ex.get(0x829A))
    if t:
        settings.append(f"1/{round(1 / t)}s" if t < 1 else f"{t:g}s")
    iso = ex.get(0x8827)
    if iso:
        settings.append(f"ISO {iso[0] if isinstance(iso, tuple) else iso}")
    fl = _num(ex.get(0x920A))
    if fl:
        settings.append(f"{fl:g} mm")
    if settings:
        meta.append(("Settings", "  ·  ".join(settings)))
    if ex.get(0x9209) is not None:
        meta.append(("Flash", "Fired" if int(ex[0x9209]) & 1 else "Off"))

    try:
        gps = exif.get_ifd(0x8825)
        if 2 in gps and 4 in gps:
            meta.append(("Location", _gps(gps)))
    except Exception:
        pass
    if exif.get(305):
        meta.append(("Software", _clean(exif[305])))
    orient = exif.get(274)
    if orient and orient != 1:
        meta.append(("Orientation", {3: "Upside down", 6: "Rotated 90° (fixed)", 8: "Rotated 270° (fixed)"}.get(orient, str(orient))))
    return meta, caption


# ---------------------------------------------------------------- videos

_FFMPEG = None


def ffmpeg_exe():
    global _FFMPEG
    if _FFMPEG is None:
        try:
            import imageio_ffmpeg
            _FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            _FFMPEG = ""
    return _FFMPEG


def _run(args):
    flags = 0x08000000 if os.name == "nt" else 0  # no black console window popping up
    return subprocess.run(args, capture_output=True, timeout=60, creationflags=flags)


def video_info(path):
    """Read a video's details from ffmpeg's description of it (iPhone, Android, cameras)."""
    info = {}
    exe = ffmpeg_exe()
    if not exe:
        return info
    try:
        text = _run([exe, "-hide_banner", "-i", path]).stderr.decode("utf-8", "ignore")
    except Exception:
        return info
    m = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", text)
    if m:
        info["duration"] = int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])
    m = re.search(r"Video: (\w+).*?, (\d{2,5})x(\d{2,5})", text)
    if m:
        info["codec"], info["w"], info["h"] = m[1], int(m[2]), int(m[3])
        r = re.search(r"rotation of (-?\d+)", text) or re.search(r"rotate\s*:\s*(-?\d+)", text)
        if r and abs(int(float(r[1]))) % 180 == 90:
            info["w"], info["h"] = info["h"], info["w"]
    m = re.search(r"(\d+(?:\.\d+)?) fps", text)
    if m:
        info["fps"] = float(m[1])
    for key, pattern in [("date", r"com\.apple\.quicktime\.creationdate\s*:\s*(\S+)"),
                         ("date", r"creation_time\s*:\s*(\S+)"),
                         ("make", r"com\.apple\.quicktime\.make\s*:\s*(.+)"),
                         ("make", r"com\.android\.manufacturer\s*:\s*(.+)"),
                         ("make", r"^\s*make\s*:\s*(.+)"),
                         ("model", r"com\.apple\.quicktime\.model\s*:\s*(.+)"),
                         ("model", r"com\.android\.model\s*:\s*(.+)"),
                         ("model", r"^\s*model\s*:\s*(.+)"),
                         ("software", r"com\.apple\.quicktime\.software\s*:\s*(.+)"),
                         ("software", r"com\.android\.version\s*:\s*(.+)")]:
        m = re.search(pattern, text, re.I | re.M)
        if m and key not in info:
            info[key] = m[1].strip()
    if info.get("software", "").replace(".", "").isdigit():  # bare version number
        android = re.search(r"com\.android\.version", text, re.I)
        info["software"] = ("Android " if android else "iOS " if "apple" in info.get("make", "").lower() else "") + info["software"]
    m = re.search(r"location(?:\.ISO6709)?(?:-eng)?\s*:\s*([+-]\d+(?:\.\d+)?)([+-]\d+(?:\.\d+)?)", text, re.I)
    if m:
        info["location"] = fmt_latlon(float(m[1]), float(m[2]))
    return info


def video_frame(path, duration):
    """Grab one still frame (about 1 second in) as a PIL image."""
    exe = ffmpeg_exe()
    if not exe:
        return None
    for at in ([min(1.0, duration / 3)] if duration else [1.0]) + [0]:
        try:
            data = _run([exe, "-v", "error", "-ss", f"{at:.2f}", "-i", path, "-frames:v", "1",
                         "-vf", "scale='min(1920,iw)':-2", "-f", "image2pipe", "-vcodec", "png", "-"]).stdout
            if data:
                return Image.open(io.BytesIO(data)).convert("RGB")
        except Exception:
            pass
    return None


def load_video_preview(path, max_w, max_h):
    info = video_info(path)
    st = os.stat(path)
    caption = ""
    if info.get("date"):
        try:
            caption = datetime.strptime(info["date"][:19], "%Y-%m-%dT%H:%M:%S").strftime("%d %b %Y, %H:%M")
        except Exception:
            caption = info["date"]
    meta = [("Date taken", caption or "Unknown - file date " +
             datetime.fromtimestamp(st.st_mtime).strftime("%d %b %Y"))]
    if not caption:
        caption = datetime.fromtimestamp(st.st_mtime).strftime("%d %b %Y (file date)")
    size = st.st_size
    meta += [("File", os.path.basename(path)),
             ("Type", f"Video ({os.path.splitext(path)[1][1:].upper()})"),
             ("Size", f"{size / 1048576:.1f} MB" if size >= 1048576 else f"{size / 1024:.0f} KB")]
    if "duration" in info:
        d = round(info["duration"])
        meta.append(("Length", f"{d // 3600}:{d // 60 % 60:02d}:{d % 60:02d}" if d >= 3600 else f"{d // 60}:{d % 60:02d}"))
    if "w" in info:
        w, h = info["w"], info["h"]
        tag = "4K" if max(w, h) >= 3800 else "1080p" if min(w, h) >= 1080 else "720p" if min(w, h) >= 720 else ""
        fps = f" · {info['fps']:g} fps" if info.get("fps") else ""
        meta.append(("Dimensions", f"{w:,} × {h:,}" + (f"  ({tag})" if tag else "") + fps))
    make, model = info.get("make", ""), info.get("model", "")
    if make or model:
        meta.append(("Camera", model if make and model.lower().startswith(make.lower()) else f"{make} {model}".strip()))
    if info.get("location"):
        meta.append(("Location", info["location"]))
    if info.get("software"):
        meta.append(("Software", info["software"]))
    if not ffmpeg_exe():
        meta.append(("Preview", "Not available - press P to play it"))
    img = video_frame(path, info.get("duration"))
    if img is not None:
        img.thumbnail((max_w, max_h), Image.LANCZOS)
    return img, caption, meta


def load_preview(path, max_w, max_h):
    """Open an image, read its details, fix its rotation, shrink it to fit the screen.
    Runs in a background thread."""
    if is_video(path):
        try:
            return load_video_preview(path, max_w, max_h)
        except Exception as e:
            return None, f"Can't preview this video ({type(e).__name__})", [("File", os.path.basename(path))]
    try:
        img = Image.open(path)
        meta, info = read_metadata(path, img)
        try:
            img.draft("RGB", (max_w, max_h))  # fast JPEG decode at reduced size
        except Exception:
            pass
        img = ImageOps.exif_transpose(img)
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA" if "A" in img.getbands() else "RGB")
        img.thumbnail((max_w, max_h), Image.LANCZOS)
        return img, info, meta
    except Exception as e:
        try:
            meta, _ = read_metadata(path, None)
        except Exception:
            meta = [("File", os.path.basename(path))]
        return None, f"Can't preview this file ({type(e).__name__})", meta


# ---------------------------------------------------------------- app

class PhotoSorter:
    def __init__(self, root):
        self.root = root
        self.settings = load_settings()
        self.pool = ThreadPoolExecutor(max_workers=3)
        self.cache = {}  # path -> Future
        self.companions = {}  # photo -> its Live Photo clip
        self.tk_img = None

        root.title("Photo Sorter")
        root.configure(bg=BG)
        root.geometry("1200x850")
        root.minsize(700, 500)
        try:
            root.state("zoomed")
        except Exception:
            pass

        self.screen_w = root.winfo_screenwidth()
        self.screen_h = root.winfo_screenheight()
        self.frame = None
        self.show_setup()

    # ---------------- setup screen

    def clear(self):
        for seq in ("<Key>", "<Configure>"):
            self.root.unbind(seq)
        if self.frame is not None:
            self.frame.destroy()
        self.frame = tk.Frame(self.root, bg=BG)
        self.frame.pack(fill="both", expand=True)

    def label(self, parent, text, size=11, bold=False, color=FG, **kw):
        return tk.Label(parent, text=text, bg=parent["bg"], fg=color,
                        font=("Segoe UI", size, "bold" if bold else "normal"), **kw)

    def button(self, parent, text, cmd, color=BLUE, size=11, **kw):
        return tk.Button(parent, text=text, command=cmd, bg=color, fg="white",
                         activebackground=color, activeforeground="white", relief="flat",
                         font=("Segoe UI", size, "bold"), cursor="hand2", padx=14, pady=6, **kw)

    def show_setup(self):
        self.clear()
        s = self.settings
        box = tk.Frame(self.frame, bg=PANEL, padx=30, pady=24)
        box.place(relx=0.5, rely=0.5, anchor="center")

        self.label(box, "Photo Sorter", 22, True).grid(row=0, column=0, columnspan=3, sticky="w")
        self.label(box, "Photos are copied, never moved or deleted. Your originals stay safe.",
                   10, color=MUTED).grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 16))

        # source
        self.src_var = tk.StringVar(value=s.get("source", ""))
        self.out_var = tk.StringVar(value=s.get("output", ""))
        self.label(box, "1. Folder of photos to sort").grid(row=2, column=0, columnspan=3, sticky="w")
        tk.Entry(box, textvariable=self.src_var, width=60, font=("Segoe UI", 10)).grid(
            row=3, column=0, columnspan=2, sticky="we", pady=4)
        self.button(box, "Browse…", self.pick_source, size=9).grid(row=3, column=2, padx=(8, 0))

        self.sub_var = tk.BooleanVar(value=s.get("subfolders", True))
        tk.Checkbutton(box, text="Include photos in subfolders", variable=self.sub_var,
                       bg=PANEL, fg=FG, selectcolor=PANEL, activebackground=PANEL,
                       activeforeground=FG, font=("Segoe UI", 10)).grid(row=4, column=0, columnspan=3, sticky="w")

        # output
        self.label(box, "2. Where to put the sorted folders").grid(row=5, column=0, columnspan=3, sticky="w", pady=(12, 0))
        tk.Entry(box, textvariable=self.out_var, width=60, font=("Segoe UI", 10)).grid(
            row=6, column=0, columnspan=2, sticky="we", pady=4)
        self.button(box, "Browse…", self.pick_output, size=9).grid(row=6, column=2, padx=(8, 0))

        # mode
        self.label(box, "3. How to sort").grid(row=7, column=0, columnspan=3, sticky="w", pady=(12, 4))
        self.mode_var = tk.StringVar(value=s.get("mode", "keep"))
        rb = dict(bg=PANEL, fg=FG, selectcolor=PANEL, activebackground=PANEL,
                  activeforeground=FG, font=("Segoe UI", 10), command=self.update_mode)
        tk.Radiobutton(box, text="Keep / Delete   (Yes lets you pick or make a folder inside Keep)", value="keep",
                       variable=self.mode_var, **rb).grid(row=8, column=0, columnspan=3, sticky="w")
        tk.Radiobutton(box, text="Straight into my own folders   (one folder name per line)",
                       value="cats", variable=self.mode_var, **rb).grid(row=9, column=0, columnspan=3, sticky="w")
        self.cat_text = tk.Text(box, width=40, height=6, font=("Segoe UI", 10))
        self.cat_text.insert("1.0", s.get("categories", DEFAULT_CATEGORIES))
        self.cat_text.grid(row=10, column=0, columnspan=3, sticky="we", pady=4)
        self.update_mode()

        self.button(box, "Start sorting  ▶", self.start, color=GREEN, size=13).grid(
            row=11, column=0, columnspan=3, pady=(18, 0), sticky="we")

        heic = "" if HEIC_OK else "\n(iPhone .heic photos need Install.bat to be run.)"
        self.label(box, "Tip: close the window whenever you like - it remembers where you got to." + heic,
                   9, color=MUTED, justify="left").grid(row=12, column=0, columnspan=3, sticky="w", pady=(10, 0))

    def update_mode(self):
        self.cat_text.configure(state="normal" if self.mode_var.get() == "cats" else "disabled",
                                bg="white" if self.mode_var.get() == "cats" else "#777777")

    def pick_source(self):
        folder = filedialog.askdirectory(title="Choose the folder of photos to sort")
        if folder:
            self.src_var.set(os.path.normpath(folder))
            self.out_var.set(os.path.normpath(folder) + " - Sorted")

    def pick_output(self):
        folder = filedialog.askdirectory(title="Choose where the sorted folders should go")
        if folder:
            self.out_var.set(os.path.normpath(folder))

    def start(self):
        src = self.src_var.get().strip().strip('"')
        out = self.out_var.get().strip().strip('"') or (src + " - Sorted")
        if not src or not os.path.isdir(src):
            messagebox.showwarning("Photo Sorter", "Please choose a folder of photos first.")
            return
        if norm(src) == norm(out):
            messagebox.showwarning("Photo Sorter", "The sorted folder must be different from the photo folder.")
            return

        mode = self.mode_var.get()
        if mode == "keep":
            cats = ["Delete", "Keep"]
        else:
            cats, seen = [], set()
            for line in self.cat_text.get("1.0", "end").replace(",", "\n").splitlines():
                name = "".join(c for c in line.strip() if c not in '<>:"/\\|?*').strip(" .")
                if name and name.lower() not in seen:
                    seen.add(name.lower())
                    cats.append(name)
            if not cats:
                messagebox.showwarning("Photo Sorter", "Type at least one folder name.")
                return
            if len(cats) > 9:
                messagebox.showwarning("Photo Sorter", "Up to 9 folders please (one for each number key).")
                return

        self.settings.update(source=src, output=out, mode=mode, subfolders=self.sub_var.get(),
                             categories=self.cat_text.get("1.0", "end").strip())
        save_settings(self.settings)

        self.clear()
        self.label(self.frame, "Finding photos and videos…", 16).place(relx=0.5, rely=0.5, anchor="center")
        self.root.update()

        try:
            os.makedirs(out, exist_ok=True)
            photos, self.companions = find_photos(src, self.sub_var.get(), out)
        except Exception as e:
            messagebox.showerror("Photo Sorter", f"Couldn't read the folders:\n{e}")
            self.show_setup()
            return

        self.src, self.out, self.mode, self.cats = src, out, mode, cats
        self.log_path = os.path.join(out, LOG_NAME)
        done = read_log(self.log_path)
        try:
            move_into_photos(out, done)
        except Exception as e:
            messagebox.showwarning("Photo Sorter", f"Couldn't move your earlier sorted photos into the Photos folder:\n{e}")
        if os.path.exists(self.log_path):
            unhide_file(self.log_path)
        # photos sorted before Live Photo support: bring their clips along now
        for key, (c, dest) in done.items():
            clip = self.companions.get(key)
            if clip and dest:
                copy = os.path.join(out, space_of(c), os.path.basename(dest))
                target = os.path.splitext(copy)[0] + os.path.splitext(clip)[1]
                if os.path.exists(copy) and not os.path.exists(target):
                    try:
                        shutil.copy2(clip, target)
                    except Exception:
                        pass
        self.total = len(photos)
        self.already = sum(1 for p in photos if norm(p) in done)
        self.queue = [p for p in photos if norm(p) not in done]
        self.pos = 0
        self.history = []  # for undo: (pos, src, dest)
        self.counts = {}
        for c, _ in done.values():
            self.counts[space_of(c)] = self.counts.get(space_of(c), 0) + 1

        if not photos:
            messagebox.showinfo("Photo Sorter", "No photos or videos found in that folder.")
            self.show_setup()
            return
        self.show_sorter()

    # ---------------- sorting screen

    def show_sorter(self):
        self.clear()
        top = tk.Frame(self.frame, bg=PANEL, padx=12, pady=8)
        top.pack(fill="x")
        self.button(top, "◀ Menu", self.back_to_menu, color="#555555", size=9).pack(side="left")
        self.progress_lbl = self.label(top, "", 12, True)
        self.progress_lbl.pack(side="left", padx=16)
        self.button(top, "Open sorted folder", lambda: os.startfile(self.out), color="#555555", size=9).pack(side="right")
        self.name_lbl = self.label(top, "", 10, color=MUTED)
        self.name_lbl.pack(side="right", padx=16)

        bottom = tk.Frame(self.frame, bg=PANEL, padx=12, pady=12)
        bottom.pack(side="bottom", fill="x")

        # photo details panel on the right (press I to hide/show)
        self.side = tk.Frame(self.frame, bg=PANEL, width=330)
        self.side.pack_propagate(False)
        self.meta_text = tk.Text(self.side, bg=PANEL, fg=FG, relief="flat", wrap="word",
                                 font=("Segoe UI", 10), padx=16, pady=14, cursor="arrow",
                                 takefocus=0, highlightthickness=0, borderwidth=0)
        self.meta_text.tag_configure("head", font=("Segoe UI", 13, "bold"), spacing3=8)
        self.meta_text.tag_configure("label", foreground=MUTED, font=("Segoe UI", 9), spacing1=8)
        self.meta_text.tag_configure("value", font=("Segoe UI", 11), spacing3=2)
        self.meta_text.tag_configure("hint", foreground=MUTED, font=("Segoe UI", 8), spacing1=18)
        self.meta_text.pack(fill="both", expand=True)
        if self.settings.get("show_info", True):
            self.side.pack(side="right", fill="y")

        self.canvas = tk.Canvas(self.frame, bg=BG, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.button(bottom, "↶ Undo  (Backspace)", self.undo, color="#555555", size=10).pack(side="left")
        self.button(bottom, "Skip  (Space)", self.skip, color="#555555", size=10).pack(side="right")
        self.mid = tk.Frame(bottom, bg=PANEL)
        self.mid.pack(side="top")
        self.show_main_buttons()

        self.root.bind("<Key>", self.on_key)
        self.canvas.bind("<Configure>", lambda e: self.render())
        self.show_current()

    # ---- the buttons along the bottom

    def _reset_mid(self):
        for w in self.mid.winfo_children():
            w.destroy()
        self.cat_buttons = {}
        self.keymap = {}  # key -> action

    def show_main_buttons(self):
        self.picking = False
        self._reset_mid()
        mid = self.mid
        if self.mode == "keep":
            no = self.button(mid, "✗  NO  (N / ←)", lambda: self.choose("Delete"), color=RED, size=16, width=16)
            yes = self.button(mid, "✓  YES  (Y / →)", self.show_folder_picker, color=GREEN, size=16, width=16)
            no.pack(side="left", padx=12)
            yes.pack(side="left", padx=12)
            self.cat_buttons["Delete"] = no
            for k in ("n", "Left"):
                self.keymap[k] = lambda: self.choose("Delete")
            for k in ("y", "Right"):
                self.keymap[k] = self.show_folder_picker
            # power-user shortcut: number keys file straight into a Keep folder
            for i, name in enumerate(self.keep_folders()[:9], 1):
                self.keymap[str(i)] = lambda n=name: self.choose(os.path.join("Keep", n))
        else:
            for i, cat in enumerate(self.cats, 1):
                b = self.button(mid, f"{i}  {cat}", lambda c=cat: self.choose(c), color=BLUE, size=13)
                b.pack(side="left", padx=5)
                self.cat_buttons[cat] = b
                self.keymap[str(i)] = lambda c=cat: self.choose(c)

    def keep_folders(self):
        """Folders inside Keep - shared by photos (Photos\\Keep\\x) and videos (Videos\\Keep\\x)."""
        names = {}
        for keep in (os.path.join(self.out, "Photos", "Keep"), os.path.join(self.out, "Videos", "Keep")):
            try:
                for d in os.listdir(keep):
                    if os.path.isdir(os.path.join(keep, d)) and not d.startswith("."):
                        names.setdefault(d.lower(), d)
            except FileNotFoundError:
                pass
        return sorted(names.values(), key=str.lower)

    def show_folder_picker(self):
        if self.pos >= len(self.queue):
            return
        self.picking = True
        self._reset_mid()
        top = tk.Frame(self.mid, bg=PANEL)
        top.pack()
        self.label(top, "Keep it in which folder?", 12, True).pack(side="left", padx=(0, 12))
        self.button(top, "Keep  (Enter)", lambda: self.choose("Keep"), color=GREEN, size=12).pack(side="left", padx=4)
        for k in ("Return", "y", "Right", "0", "KP_Enter"):
            self.keymap[k] = lambda: self.choose("Keep")
        self.button(top, "+  New folder  (F)", self.new_folder, color="#7a5cb8", size=12).pack(side="left", padx=4)
        self.keymap["f"] = self.keymap["plus"] = self.new_folder
        self.button(top, "Cancel  (Esc)", self.show_main_buttons, color="#555555", size=10).pack(side="left", padx=4)
        self.keymap["Escape"] = self.show_main_buttons

        row = None
        for i, name in enumerate(self.keep_folders(), 1):
            if (i - 1) % 8 == 0:  # wrap onto a new row every 8 folders
                row = tk.Frame(self.mid, bg=PANEL)
                row.pack(pady=(8, 0))
            text = f"{i}  {name}" if i <= 9 else name
            self.button(row, text, lambda n=name: self.choose(os.path.join("Keep", n)),
                        color=BLUE, size=12).pack(side="left", padx=4)
            if i <= 9:
                self.keymap[str(i)] = lambda n=name: self.choose(os.path.join("Keep", n))

    def new_folder(self):
        name = simpledialog.askstring("New folder", "Name for the new folder inside Keep:", parent=self.root)
        name = "".join(c for c in (name or "") if c not in '<>:"/\\|?*').strip(" .")
        if not name:
            self.root.focus_force()
            return
        self.root.focus_force()
        self.choose(os.path.join("Keep", name))

    def on_key(self, e):
        if isinstance(e.widget, (tk.Entry, tk.Text)) and e.widget is not getattr(self, "meta_text", None):
            return
        key = e.keysym if len(e.keysym) > 1 else e.keysym.lower()
        if key in self.keymap:
            self.keymap[key]()
        elif key == "i":
            self.toggle_info()
        elif key == "p":
            self.play()
        elif key == "space":
            self.skip()
        elif key in ("BackSpace", "z") :
            self.undo()
        elif key == "Escape":
            self.back_to_menu()

    def playable(self):
        path = getattr(self, "current_path", None)
        if not path or self.pos >= len(self.queue):
            return None
        return path if is_video(path) else self.companions.get(norm(path))

    def play(self):
        clip = self.playable()
        if clip:
            try:
                os.startfile(clip)  # opens in the normal Windows video player
            except Exception as e:
                messagebox.showerror("Photo Sorter", f"Couldn't play this video:\n{e}")

    def toggle_info(self):
        show = not self.side.winfo_ismapped()
        if show:
            self.side.pack(side="right", fill="y", before=self.canvas)
        else:
            self.side.pack_forget()
        self.settings["show_info"] = show
        save_settings(self.settings)

    def show_meta(self, meta):
        t = self.meta_text
        t.config(state="normal")
        t.delete("1.0", "end")
        video = is_video(self.current_path)
        t.insert("end", ("Video details" if video else "Photo details") + "\n", "head")
        folder = os.path.dirname(os.path.relpath(self.current_path, self.src))
        rows = list(meta)
        if video:
            rows.append(("Goes to", "The Videos folder (same folder names as Photos)"))
        elif norm(self.current_path) in self.companions:
            rows.append(("Live Photo", "Yes - its video clip is kept with it. Press P to play."))
        rows.insert(1 if rows and rows[0][0] == "Date taken" else 0, ("Folder", folder or "(top folder)"))
        for label, value in rows:
            t.insert("end", label.upper() + "\n", "label")
            t.insert("end", str(value) + "\n", "value")
        t.insert("end", "Press I to hide or show this panel", "hint")
        t.config(state="disabled")

    def prefetch(self, path):
        if path not in self.cache:
            self.cache[path] = self.pool.submit(load_preview, path, self.screen_w, self.screen_h)
        return self.cache[path]

    def show_current(self):
        if self.pos >= len(self.queue):
            self.show_done()
            return
        path = self.queue[self.pos]
        # keep the next few loading in the background so it feels instant
        for p in self.queue[self.pos:self.pos + 4]:
            self.prefetch(p)
        for p in list(self.cache):
            if p not in self.queue[max(0, self.pos - 2):self.pos + 4]:
                del self.cache[p]

        done_now = self.already + self.pos
        pct = 100 * done_now / self.total if self.total else 100
        self.progress_lbl.config(text=f"{done_now + 1:,} of {self.total:,}   ({pct:.0f}% done)")
        rel = os.path.relpath(path, self.src)
        self.name_lbl.config(text=rel)
        self.current_path = path
        self.wait_for_image(path)

    def wait_for_image(self, path):
        if path != getattr(self, "current_path", None):
            return
        fut = self.prefetch(path)
        if not fut.done():
            self.canvas.delete("all")
            self.canvas.create_text(self.canvas.winfo_width() // 2, self.canvas.winfo_height() // 2,
                                    text="Loading…", fill=MUTED, font=("Segoe UI", 14))
            self.root.after(30, lambda: self.wait_for_image(path))
            return
        self.current_img, self.current_info, meta = fut.result()
        self.show_meta(meta)
        self.render()

    def render(self):
        if not hasattr(self, "current_info"):
            return
        c = self.canvas
        w, h = max(c.winfo_width(), 50), max(c.winfo_height(), 50)
        c.delete("all")
        if self.current_img is not None:
            img = self.current_img
            scale = min((w - 20) / img.width, (h - 40) / img.height, 1.0)
            if scale < 1.0:
                img = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))), Image.BILINEAR)
            self.tk_img = ImageTk.PhotoImage(img)
            c.create_image(w // 2, (h - 20) // 2, image=self.tk_img)
        elif is_video(self.current_path):
            c.create_text(w // 2, h // 2 + 90, text="🎬  Video (no preview)", fill=FG, font=("Segoe UI", 16))
        else:
            c.create_text(w // 2, h // 2, text="⚠  " + self.current_info + "\nYou can still sort it.",
                          fill=FG, font=("Segoe UI", 16), justify="center")
            return
        caption = self.current_info
        if is_video(self.current_path):
            # big play button - click it or press P
            r, cx, cy = 52, w // 2, (h - 20) // 2
            c.create_oval(cx - r, cy - r, cx + r, cy + r, fill="#000000", outline="white", width=3,
                          stipple="gray50", tags="play")
            c.create_polygon(cx - 16, cy - 26, cx - 16, cy + 26, cx + 28, cy, fill="white", tags="play")
            c.tag_bind("play", "<Button-1>", lambda e: self.play())
            c.tag_bind("play", "<Enter>", lambda e: c.config(cursor="hand2"))
            c.tag_bind("play", "<Leave>", lambda e: c.config(cursor=""))
            caption = "VIDEO  ·  press P to play  ·  " + caption
        elif self.playable():
            c.create_text(30, 26, text="◉ LIVE", anchor="w", fill="white", font=("Segoe UI", 12, "bold"))
            caption = "LIVE PHOTO  ·  press P to play the clip  ·  " + caption
        c.create_text(w // 2, h - 14, text=caption, fill=MUTED, font=("Segoe UI", 10))

    def flash(self, cat):
        b = self.cat_buttons.get(cat)
        if b:
            b.config(relief="sunken")
            self.root.after(120, lambda: b.winfo_exists() and b.config(relief="flat"))

    def choose(self, cat):
        if self.pos >= len(self.queue):
            return
        src = self.queue[self.pos]
        space = os.path.join("Videos" if is_video(src) else "Photos", cat)
        folder = os.path.join(self.out, space)
        clip = self.companions.get(norm(src))
        extras = []
        try:
            os.makedirs(folder, exist_ok=True)
            dest = unique_dest(folder, os.path.basename(src), [os.path.splitext(clip)[1]] if clip else ())
            shutil.copy2(src, dest)
            if clip:  # Live Photo: copy the clip next to the photo with the matching name
                extras.append(os.path.splitext(dest)[0] + os.path.splitext(clip)[1])
                shutil.copy2(clip, extras[0])
            append_log(self.log_path, {"src": src, "cat": space, "dest": dest, "extra": extras})
        except Exception as e:
            messagebox.showerror("Photo Sorter", f"Couldn't copy this file:\n{e}")
            return
        self.counts[space] = self.counts.get(space, 0) + 1
        self.history.append((self.pos, src, dest, space, extras))
        self.flash(cat)
        self.pos += 1
        if getattr(self, "picking", False) or (self.mode == "keep" and cat.startswith("Keep" + os.sep)):
            self.show_main_buttons()  # back to Yes/No (and pick up any new folder)
        self.show_current()

    def skip(self):
        if getattr(self, "picking", False):
            self.show_main_buttons()
        if self.pos < len(self.queue):
            self.history.append((self.pos, None, None, None, []))
            self.pos += 1
            self.show_current()

    def undo(self):
        if not self.history:
            return
        pos, src, dest, cat, extras = self.history.pop()
        if src is not None:
            try:
                for f in [dest] + list(extras):
                    if f and os.path.exists(f):
                        os.remove(f)  # only ever removes the COPIES we just made
                append_log(self.log_path, {"undo": src})
                self.counts[cat] -= 1
            except Exception as e:
                messagebox.showerror("Photo Sorter", f"Couldn't undo:\n{e}")
                self.history.append((pos, src, dest, cat, extras))
                return
        self.pos = pos
        if not hasattr(self, "canvas") or not self.canvas.winfo_exists():
            self.show_sorter()
        else:
            self.show_main_buttons()
            self.show_current()

    def back_to_menu(self):
        self.cache.clear()
        self.show_setup()

    # ---------------- summary infographic

    @staticmethod
    def _tree_rows(counts):
        """counts {'Photos\\\\Keep\\\\cats': 3, ...} -> flat rows for drawing a folder tree."""
        root = {"name": "", "own": 0, "kids": {}}
        for key, n in counts.items():
            if not n:
                continue
            node = root
            for part in key.split(os.sep):
                node = node["kids"].setdefault(part.lower(), {"name": part, "own": 0, "kids": {}})
            node["own"] += n

        def total(node):
            return node["own"] + sum(total(k) for k in node["kids"].values())

        def order(node):
            name = node["name"].lower()
            return (0 if name in ("photos", "keep") else 2 if name == "delete" else 1, name)

        rows = []

        def walk(node, depth, path, lasts, kind):
            kids = sorted(node["kids"].values(), key=order)
            if node["own"] and kids:  # files directly in a folder that also has subfolders
                kids = [{"name": "(not in a subfolder)", "own": node["own"], "kids": {}, "loose": True}] + kids
            for i, kid in enumerate(kids):
                last = i == len(kids) - 1
                kpath = path if kid.get("loose") else os.path.join(path, kid["name"]) if path else kid["name"]
                low = kid["name"].lower()
                kkind = "delete" if low == "delete" else "keep" if low == "keep" else kind
                rows.append({"depth": depth, "name": kid["name"], "count": total(kid), "path": kpath,
                             "lasts": lasts + [last], "kind": kkind, "parent": bool(kid["kids"]),
                             "loose": kid.get("loose", False)})
                walk(kid, depth + 1, kpath, lasts + [last], kkind)

        walk(root, 0, "", [], "folder")
        return rows

    def show_done(self):
        self.clear()
        counts = {k: n for k, n in self.counts.items() if n}
        grand = sum(counts.values())
        deleted = sum(n for k, n in counts.items() if "delete" in [p.lower() for p in k.split(os.sep)])
        videos = sum(n for k, n in counts.items() if k.split(os.sep)[0] == "Videos")
        kept = grand - deleted
        this_session = sum(1 for h in self.history if h[1] is not None)
        skipped = sum(1 for h in self.history if h[1] is None)

        box = tk.Frame(self.frame, bg=PANEL, padx=36, pady=28)
        box.place(relx=0.5, rely=0.5, anchor="center")
        self.label(box, "All done! 🎉", 22, True).pack(anchor="w")
        self.label(box, f"Everything sorted into  “{os.path.basename(self.out)}”  so far"
                   + (f"   ·   {this_session:,} this session" if this_session else ""),
                   10, color=MUTED).pack(anchor="w", pady=(2, 14))

        # --- headline tiles
        tiles = tk.Frame(box, bg=PANEL)
        tiles.pack(anchor="w", fill="x")
        spec = [("Sorted", grand, FG), ("Kept", kept, "#4cc38a"), ("Delete", deleted, "#e06c6c")]
        if videos:
            spec.append(("Videos", videos, "#a78bfa"))
        for title, n, color in spec:
            t = tk.Frame(tiles, bg="#363636", padx=18, pady=10)
            t.pack(side="left", padx=(0, 10))
            tk.Label(t, text=f"{n:,}", bg="#363636", fg=color, font=("Segoe UI", 22, "bold")).pack(anchor="w")
            tk.Label(t, text=title.upper(), bg="#363636", fg=MUTED, font=("Segoe UI", 9)).pack(anchor="w")

        W = 680
        # --- kept vs delete bar
        if grand:
            bar = tk.Canvas(box, width=W, height=46, bg=PANEL, highlightthickness=0)
            bar.pack(anchor="w", pady=(16, 4))
            kw = round(W * kept / grand)
            if kw:
                bar.create_rectangle(0, 0, kw, 18, fill="#2e8b57", width=0)
            if kw < W:
                bar.create_rectangle(kw, 0, W, 18, fill="#b23b3b", width=0)
            bar.create_text(0, 32, anchor="w", fill="#4cc38a", font=("Segoe UI", 10, "bold"),
                            text=f"Kept {kept:,}  ({100 * kept / grand:.0f}%)")
            bar.create_text(W, 32, anchor="e", fill="#e06c6c", font=("Segoe UI", 10, "bold"),
                            text=f"Delete {deleted:,}  ({100 * deleted / grand:.0f}%)")

        # --- folder tree with a bar per folder (click a row to open that folder)
        self.label(box, "Folders  ·  click one to open it", 10, color=MUTED).pack(anchor="w", pady=(14, 6))
        rows = self._tree_rows(counts)
        ROW, IND, NAME_W, BAR_X = 30, 24, 300, 370
        BAR_W = W - BAR_X - 60
        height = max(ROW, len(rows) * ROW)
        holder = tk.Frame(box, bg=PANEL)
        holder.pack(anchor="w")
        view_h = min(height, int(self.screen_h * 0.42))
        tree = tk.Canvas(holder, width=W, height=view_h, bg=PANEL, highlightthickness=0,
                         scrollregion=(0, 0, W, height))
        tree.pack(side="left")
        if height > view_h:
            sb = tk.Scrollbar(holder, orient="vertical", command=tree.yview)
            sb.pack(side="left", fill="y")
            tree.config(yscrollcommand=sb.set)
            tree.bind_all("<MouseWheel>", lambda e: tree.winfo_exists() and tree.yview_scroll(-e.delta // 120, "units"))
        colors = {"delete": "#b23b3b", "keep": "#2e8b57", "folder": BLUE}
        line = "#555555"
        for i, r in enumerate(rows):
            y0, ym = i * ROW, i * ROW + ROW // 2
            d = r["depth"]
            tag = f"row{i}"
            tree.create_rectangle(0, y0, W, y0 + ROW, fill=PANEL, outline="", tags=(tag, "hit"))
            # connector lines
            for lvl in range(1, d):  # carry on the lines of ancestors that have more siblings below
                if not r["lasts"][lvl]:
                    x = lvl * IND - IND // 2 + 6
                    tree.create_line(x, y0, x, y0 + ROW, fill=line, tags=tag)
            if d:
                x = d * IND - IND // 2 + 6
                tree.create_line(x, y0, x, ym if r["lasts"][d] else y0 + ROW, fill=line, tags=tag)
                tree.create_line(x, ym, x + IND // 2, ym, fill=line, tags=tag)
            x = d * IND + 8
            icon = "▸" if r["loose"] else ("📂" if r["parent"] else "📁")
            bold = d == 0
            tree.create_text(x, ym, anchor="w", tags=tag, fill=MUTED if r["loose"] else FG,
                             font=("Segoe UI", 11 if bold else 10, "bold" if bold else "normal"),
                             text=f"{icon}  {r['name']}")
            tree.create_text(NAME_W + 50, ym, anchor="e", tags=tag, fill=FG,
                             font=("Segoe UI", 10, "bold" if bold else "normal"), text=f"{r['count']:,}")
            share = r["count"] / grand if grand else 0
            bw = max(2, round(BAR_W * share))
            color = "#7a5cb8" if d == 0 and r["name"] == "Videos" else colors[r["kind"]]
            tree.create_rectangle(BAR_X, ym - 6, BAR_X + bw, ym + 6, fill=color, width=0, tags=tag)
            tree.create_text(BAR_X + bw + 8, ym, anchor="w", fill=MUTED, font=("Segoe UI", 9),
                             text=f"{100 * share:.0f}%", tags=tag)
            folder = os.path.join(self.out, r["path"])

            def open_it(e, f=folder):
                if os.path.isdir(f):
                    os.startfile(f)

            def hover(e, t=tag, on=True):
                tree.itemconfig(f"{t}&&hit", fill="#383838" if on else PANEL)
                tree.config(cursor="hand2" if on else "")

            tree.tag_bind(tag, "<Button-1>", open_it)
            tree.tag_bind(tag, "<Enter>", hover)
            tree.tag_bind(tag, "<Leave>", lambda e, t=tag: hover(e, t, False))

        if skipped:
            self.label(box, f"{skipped} skipped - they'll come up again next time you open this folder.",
                       10, color=MUTED).pack(anchor="w", pady=(10, 0))
        row = tk.Frame(box, bg=PANEL)
        row.pack(anchor="w", pady=(18, 0))
        self.button(row, "Open sorted folder", lambda: os.startfile(self.out), color=GREEN).pack(side="left")
        self.button(row, "↶ Undo last", self.undo, color="#555555").pack(side="left", padx=8)
        self.button(row, "Back to menu", self.show_setup, color="#555555").pack(side="left")
        self.root.bind("<Key>", lambda e: self.undo() if e.keysym in ("BackSpace", "z") else None)


def main():
    try:  # sharp text on high-DPI Windows screens
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    root = tk.Tk()
    PhotoSorter(root)
    root.mainloop()


if __name__ == "__main__":
    main()
