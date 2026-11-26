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
import time
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

IMAGE_EXTS = {".jpg", ".jpeg", ".jpe", ".jfif", ".png", ".gif", ".bmp", ".tif", ".tiff", ".webp", ".psd"}
if HEIC_OK:
    IMAGE_EXTS |= {".heic", ".heif", ".hif"}
try:
    from PIL import features as _features
    if _features.check("avif"):
        IMAGE_EXTS.add(".avif")
except Exception:
    pass

# Camera RAW files: previewed from the JPEG the camera tucks inside them (needs rawpy)
RAW_EXTS = {".cr2", ".cr3", ".crw", ".nef", ".nrw", ".arw", ".srf", ".sr2", ".dng", ".orf", ".rw2", ".raf",
            ".pef", ".srw", ".3fr", ".iiq", ".erf", ".kdc", ".mrw", ".x3f", ".rwl", ".raw", ".mef", ".mos"}
try:
    import rawpy
    RAW_OK = True
except ImportError:
    RAW_OK = False
# Small "edits" files that belong to a photo: Bridge / Lightroom (.xmp), iPhone edits (.aae)
SIDECAR_EXTS = {".xmp", ".aae"}
# Windows / Mac housekeeping files - never photos, not worth reporting one by one
JUNK_NAMES = {"thumbs.db", "desktop.ini", ".ds_store", "ehthumbs.db", "ehthumbs_vista.db", "icon\r"}

# Videos: shown as a still frame, played in the normal Windows player (needs imageio-ffmpeg)
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".wmv", ".3gp", ".mts", ".m2ts", ".webm", ".mpg", ".mpeg"}
LIVE_EXTS = {".mov", ".mp4"}  # iPhone Live Photo clips share a name with their photo

VERSION = "2.0"

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


def default_output(src):
    """'<folder> - Sorted' right next to the folder being sorted."""
    src = os.path.abspath(os.path.normpath(src.strip().strip('"')))
    parent, name = os.path.split(src.rstrip("\\/"))
    if not name:  # a whole drive, e.g. D:\\ - nothing sits "next to" it, so put it inside
        return os.path.join(src, "Sorted")
    return os.path.join(parent, name + " - Sorted")


def is_video(path):
    return os.path.splitext(path)[1].lower() in VIDEO_EXTS


def is_raw(path):
    return os.path.splitext(path)[1].lower() in RAW_EXTS


def _collect(dirpath, names, found, companions, report):
    """Sort one folder's files into: things to show, things that travel with them, and things skipped."""
    groups = {}  # lower-case name stem -> {"photo": [...], "raw": [...], "video": [...], "side": [...]}

    def group(stem):
        return groups.setdefault(stem.lower(), {"photo": [], "raw": [], "video": [], "side": []})

    for name in sorted(names, key=str.lower):
        stem, ext = os.path.splitext(name)
        e = ext.lower()
        if name.lower() in JUNK_NAMES or name.startswith(".") or name.startswith("~$"):
            report["junk"] += 1
        elif e in IMAGE_EXTS:
            group(stem)["photo"].append(name)
        elif e in RAW_EXTS:
            group(stem)["raw"].append(name)
        elif e in VIDEO_EXTS:
            group(stem)["video"].append(name)
        elif e in SIDECAR_EXTS:
            inner, inner_ext = os.path.splitext(stem)  # IMG_1.CR2.xmp belongs to IMG_1
            group(inner if inner_ext.lower() in IMAGE_EXTS | RAW_EXTS else stem)["side"].append(name)
        else:
            skip(report, dirpath, name, e or "(no extension)")

    for g in groups.values():
        full = lambda n: os.path.join(dirpath, n)
        if g["photo"]:
            main = g["photo"][0]
            found.extend(full(n) for n in g["photo"])
            extra = list(g["raw"])                                        # RAW+JPEG pair
            extra += [v for v in g["video"] if os.path.splitext(v)[1].lower() in LIVE_EXTS]  # Live Photo
            found.extend(full(v) for v in g["video"] if v not in extra)
            report["pairs"] += len(g["raw"])
            report["live"] += len(extra) - len(g["raw"])
        elif g["raw"]:
            main = g["raw"][0]
            found.extend(full(n) for n in g["raw"])
            found.extend(full(v) for v in g["video"])
            extra = []
        else:
            main = None
            found.extend(full(v) for v in g["video"])
            extra = []
        if main:
            extra += g["side"]
            report["sidecars"] += len(g["side"])
            if extra:
                companions[norm(full(main))] = [full(n) for n in extra]
        else:
            for n in g["side"]:  # an edits file whose photo isn't here
                skip(report, dirpath, n, os.path.splitext(n)[1].lower() + " (no matching photo)")


def skip(report, dirpath, name, kind):
    full = os.path.join(dirpath, name)
    entry = report["skipped"].setdefault(kind, {"count": 0, "bytes": 0, "paths": []})
    entry["count"] += 1
    try:
        entry["bytes"] += os.path.getsize(full)
    except OSError:
        pass
    entry["paths"].append(full)


def find_photos(folder, include_subfolders, skip_folder):
    """-> (photos and videos to sort, {item: files that travel with it}, report of what was found/skipped)"""
    skip_dir = norm(skip_folder)
    found, companions = [], {}
    report = {"skipped": {}, "junk": 0, "pairs": 0, "live": 0, "sidecars": 0, "hidden_dirs": 0}
    if include_subfolders:
        for dirpath, dirnames, filenames in os.walk(folder):
            # never scan the output folder if it sits inside the source folder
            keep = []
            for d in dirnames:
                if norm(os.path.join(dirpath, d)) == skip_dir:
                    continue
                if d.startswith("."):
                    report["hidden_dirs"] += 1
                    continue
                keep.append(d)
            dirnames[:] = keep
            _collect(dirpath, filenames, found, companions, report)
    else:
        names = [n for n in os.listdir(folder) if os.path.isfile(os.path.join(folder, n))]
        _collect(folder, names, found, companions, report)
    found.sort(key=lambda p: p.lower())
    return found, companions, report


def human_size(n):
    for unit in ("bytes", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:,.0f} {unit}" if unit == "bytes" else f"{n:,.1f} {unit}"
        n /= 1024


def write_skipped_list(out, report):
    """A list of every file that wasn't included, for checking. Returns the file's path (or None)."""
    path = os.path.join(out, "Skipped files.csv")
    if not report["skipped"]:
        if os.path.exists(path):
            try:
                os.remove(path)  # nothing skipped any more - don't leave an old list lying around
            except OSError:
                pass
        return None
    import csv
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["Type", "File", "Size"])
        for kind, entry in sorted(report["skipped"].items(), key=lambda kv: -kv[1]["count"]):
            for fp in entry["paths"]:
                try:
                    size = human_size(os.path.getsize(fp))
                except OSError:
                    size = ""
                w.writerow([kind, fp, size])
    return path


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
            elif "src" in rec:
                done[norm(rec["src"])] = (rec["cat"], rec["dest"])
    return done


def read_session(log_path):
    """What a progress file says about its sort: the settings it was started with
    (newer files) or a best guess from the files it lists (older files)."""
    session, srcs, cats = None, [], set()
    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if "session" in rec:
                session = rec["session"]
            elif "src" in rec:
                srcs.append(rec["src"])
                cats.add(rec["cat"])
    if session:
        return dict(session), True
    guess = {"output": os.path.dirname(os.path.abspath(log_path)), "subfolders": True}
    if srcs:
        try:
            guess["source"] = os.path.commonpath([os.path.dirname(x) for x in srcs])
        except ValueError:
            guess["source"] = os.path.dirname(srcs[0])
    plain = {c.split(os.sep)[1] if c.split(os.sep)[0] in ("Photos", "Videos") and len(c.split(os.sep)) > 1
             else c.split(os.sep)[0] for c in cats}
    if not plain or plain & {"Keep", "Delete"}:
        guess["mode"] = "keep"
    else:
        guess["mode"] = "cats"
        guess["categories"] = "\n".join(sorted(plain, key=str.lower))
    return guess, False


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


def clean_filename(name):
    """Make typed text safe as a Windows file name (no \\ / : * ? " < > |, no trailing dots/spaces)."""
    name = "".join(c for c in name if c not in '<>:"/\\|?*' and ord(c) >= 32).strip().rstrip(". ")
    if name.upper().split(".")[0] in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                                     *(f"LPT{i}" for i in range(1, 10))}:
        name = "_" + name
    return name[:180]


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
            when = datetime.strptime(_clean(taken)[:19], "%Y:%m:%d %H:%M:%S")
            caption = when.strftime("%d %b %Y, %H:%M")
            meta.append(("_taken", when.isoformat()))
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
            when = datetime.strptime(info["date"][:19], "%Y-%m-%dT%H:%M:%S")
            caption = when.strftime("%d %b %Y, %H:%M")
        except Exception:
            when, caption = None, info["date"]
    else:
        when = None
    meta = [("Date taken", caption or "Unknown - file date " +
             datetime.fromtimestamp(st.st_mtime).strftime("%d %b %Y"))]
    if when:
        meta.append(("_taken", when.isoformat()))
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


# ---------------------------------------------------------------- RAW files

def _tagval(tags, *names):
    for n in names:
        if n in tags:
            return tags[n]
    return None


def _ratio(v):
    try:
        x = v.values[0]
        return float(x.num) / float(x.den) if hasattr(x, "num") else float(x)
    except Exception:
        return None


def _raw_tags_exifread(path):
    """Most RAW types are TIFF-based (CR2, NEF, ARW, DNG, ORF, RW2...): exifread reads them."""
    import logging
    import exifread
    logging.getLogger("exifread").setLevel(logging.CRITICAL)  # no "File format not recognized" noise
    with open(path, "rb") as f:
        tags = exifread.process_file(f, details=False)
    if not tags:
        return {}
    d = {"date": _tagval(tags, "EXIF DateTimeOriginal", "Image DateTime"),
         "make": _tagval(tags, "Image Make"), "model": _tagval(tags, "Image Model"),
         "lens": _tagval(tags, "EXIF LensModel", "MakerNote LensModel"),
         "iso": _tagval(tags, "EXIF ISOSpeedRatings", "EXIF PhotographicSensitivity")}
    for key, tag in (("f", "EXIF FNumber"), ("t", "EXIF ExposureTime"), ("fl", "EXIF FocalLength")):
        if tag in tags:
            d[key] = _ratio(tags[tag])
    try:
        dms_ = lambda v: sum(float(x.num) / float(x.den) / 60 ** i for i, x in enumerate(v.values))
        la = dms_(tags["GPS GPSLatitude"]) * (-1 if str(tags.get("GPS GPSLatitudeRef", "N")) == "S" else 1)
        lo = dms_(tags["GPS GPSLongitude"]) * (-1 if str(tags.get("GPS GPSLongitudeRef", "E")) == "W" else 1)
        d["gps"] = (la, lo)
    except Exception:
        pass
    return d


def _raw_tags_cr3(path):
    """Canon CR3 keeps its details in CMT1 (camera), CMT2 (exposure) and CMT4 (GPS) boxes."""
    with open(path, "rb") as f:
        data = f.read(4_000_000)
    boxes = {}
    for name in (b"CMT1", b"CMT2", b"CMT4"):
        i = data.find(name)
        if i < 4:
            continue
        size = int.from_bytes(data[i - 4:i], "big")
        ex = Image.Exif()
        ex.load(b"Exif\x00\x00" + data[i + 4:i - 4 + size])
        boxes[name] = ex
    c1, c2, c4 = (boxes.get(b"CMT1", {}), boxes.get(b"CMT2", {}), boxes.get(b"CMT4", {}))
    d = {"make": c1.get(271), "model": c1.get(272), "date": c2.get(36867) or c1.get(306),
         "lens": c2.get(0xA434), "iso": c2.get(0x8827),
         "f": _num(c2.get(0x829D)), "t": _num(c2.get(0x829A)), "fl": _num(c2.get(0x920A))}
    try:
        g = dict(c4)
        if 2 in g and 4 in g:
            lat = sum(_num(x) / 60 ** i for i, x in enumerate(g[2])) * (-1 if _clean(g.get(1, "N")) == "S" else 1)
            lon = sum(_num(x) / 60 ** i for i, x in enumerate(g[4])) * (-1 if _clean(g.get(3, "E")) == "W" else 1)
            d["gps"] = (lat, lon)
    except Exception:
        pass
    return d


def raw_metadata(path, w=None, h=None):
    """Camera details from a RAW file, in the same shape as read_metadata."""
    st = os.stat(path)
    d = {}
    for reader in ((_raw_tags_cr3,) if path.lower().endswith(".cr3") else (_raw_tags_exifread,)):
        try:
            d = reader(path)
        except Exception:
            d = {}
    meta = []
    taken = d.get("date")
    if taken:
        try:
            when = datetime.strptime(_clean(taken)[:19], "%Y:%m:%d %H:%M:%S")
            caption = when.strftime("%d %b %Y, %H:%M")
            meta.append(("_taken", when.isoformat()))
        except Exception:
            caption = _clean(taken)
        meta.append(("Date taken", caption))
    else:
        meta.append(("Date taken", "Unknown - file date " + datetime.fromtimestamp(st.st_mtime).strftime("%d %b %Y")))
        caption = datetime.fromtimestamp(st.st_mtime).strftime("%d %b %Y (file date)")
    size = st.st_size
    meta += [("File", os.path.basename(path)),
             ("Type", f"RAW ({os.path.splitext(path)[1][1:].upper()})"),
             ("Size", f"{size / 1048576:.1f} MB" if size >= 1048576 else f"{size / 1024:.0f} KB")]
    if w and h:
        meta.append(("Dimensions", f"{w:,} × {h:,}  ({w * h / 1e6:.1f} MP)"))
    make = _clean(d.get("make") or "")
    model = _clean(d.get("model") or "")
    if model and make and not model.lower().startswith(make.lower().split()[0]):
        model = f"{make} {model}"
    if model or make:
        meta.append(("Camera", model or make))
    lens = _clean(d.get("lens") or "")
    if lens:
        meta.append(("Lens", lens))
    settings = []
    if d.get("f"):
        settings.append(f"f/{d['f']:.1f}".replace(".0", ""))
    if d.get("t"):
        t = d["t"]
        settings.append(f"1/{round(1 / t)}s" if t < 1 else f"{t:g}s")
    iso = d.get("iso")
    if iso:
        settings.append(f"ISO {iso[0] if isinstance(iso, tuple) else iso}")
    if d.get("fl"):
        settings.append(f"{d['fl']:g} mm")
    if settings:
        meta.append(("Settings", "  ·  ".join(settings)))
    if d.get("gps"):
        meta.append(("Location", fmt_latlon(*d["gps"])))
    return meta, caption


def load_raw_preview(path, max_w, max_h):
    if not RAW_OK:
        meta, caption = raw_metadata(path)
        return None, "RAW preview not available", meta
    img, w, h = None, None, None
    with rawpy.imread(path) as raw:
        w, h = raw.sizes.width, raw.sizes.height
        flip = raw.sizes.flip
        if flip in (5, 6):
            w, h = h, w
        try:
            th = raw.extract_thumb()  # the JPEG preview the camera saved inside the RAW - fast
            if th.format == rawpy.ThumbFormat.JPEG:
                img = Image.open(io.BytesIO(th.data))
                img.draft("RGB", (max_w, max_h))
                img = img.convert("RGB")
            else:
                img = Image.fromarray(th.data)
            if flip == 3:
                img = img.rotate(180)
            elif flip == 5:
                img = img.rotate(90, expand=True)
            elif flip == 6:
                img = img.rotate(-90, expand=True)
        except Exception:
            # no usable preview inside: develop the RAW at half size (slower, but always works)
            rgb = raw.postprocess(half_size=True, use_camera_wb=True, output_bps=8)
            img = Image.fromarray(rgb)
    img.thumbnail((max_w, max_h), Image.LANCZOS)
    meta, caption = raw_metadata(path, w, h)
    return img, caption, meta


def load_preview(path, max_w, max_h):
    """Open an image, read its details, fix its rotation, shrink it to fit the screen.
    Runs in a background thread."""
    if is_raw(path):
        try:
            return load_raw_preview(path, max_w, max_h)
        except Exception as e:
            try:
                meta, _ = raw_metadata(path)
            except Exception:
                meta = [("File", os.path.basename(path))]
            return None, f"Can't preview this RAW file ({type(e).__name__})", meta
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
        self.companions = {}  # item -> files that travel with it (Live clip, RAW, .xmp, .aae)
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
        self.key_handler = None  # what the keyboard does on the Sort tab right now

        # tab bar along the top: Sort / Shortcuts / How to use
        bar = tk.Frame(root, bg="#161616")
        bar.pack(fill="x", side="top")
        self.tab_buttons = {}
        for key, text in [("sort", "Sort"), ("keys", "Shortcuts"), ("help", "How to use")]:
            b = tk.Label(bar, text=text, bg="#161616", fg=MUTED, font=("Segoe UI", 11, "bold"),
                         padx=18, pady=9, cursor="hand2")
            b.pack(side="left")
            b.bind("<Button-1>", lambda e, k=key: self.show_tab(k))
            self.tab_buttons[key] = b
        tk.Label(bar, text=f"Photo Sorter {VERSION}   ·   F1 for shortcuts", bg="#161616", fg="#6a6a6a",
                 font=("Segoe UI", 9)).pack(side="right", padx=14)
        self.content = tk.Frame(root, bg=BG)
        self.content.pack(fill="both", expand=True)
        self.pages = {"sort": tk.Frame(self.content, bg=BG)}
        self.tab = None
        root.bind("<Key>", self._dispatch_key)
        self.show_tab("sort")
        self.show_setup()

    # ---------------- tabs

    def show_tab(self, key):
        if key == self.tab:
            return
        if key not in self.pages:
            self.pages[key] = self.build_shortcuts_page() if key == "keys" else self.build_help_page()
        if self.tab:
            self.pages[self.tab].pack_forget()
        self.pages[key].pack(fill="both", expand=True)
        self.tab = key
        for k, b in self.tab_buttons.items():
            on = k == key
            b.config(fg=FG if on else MUTED, bg=BG if on else "#161616")
        self.root.focus_set()

    def _dispatch_key(self, e):
        if e.keysym == "F1":
            self.show_tab("help" if self.tab == "keys" else "keys")
            return
        if self.tab != "sort":
            if e.keysym == "Escape":
                self.show_tab("sort")
            return  # never sort anything while reading the other tabs
        if self.key_handler:
            self.key_handler(e)

    def _page(self):
        """A scrollable, centred column for the info tabs."""
        outer = tk.Frame(self.content, bg=BG)
        canvas = tk.Canvas(outer, bg=BG, highlightthickness=0)
        sb = tk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        inner = tk.Frame(canvas, bg=BG, padx=40, pady=28)
        win = canvas.create_window(0, 0, window=inner, anchor="n")

        def layout(e=None):
            canvas.coords(win, canvas.winfo_width() // 2, 0)
            canvas.configure(scrollregion=(0, 0, canvas.winfo_width(), inner.winfo_reqheight()))
        inner.bind("<Configure>", layout)
        canvas.bind("<Configure>", layout)

        def wheel(e):
            if self.tab != "sort" and self.pages.get(self.tab) is outer:
                canvas.yview_scroll(-e.delta // 120, "units")
        canvas.bind_all("<MouseWheel>", wheel, add="+")
        return outer, inner

    def _chip(self, parent, key):
        return tk.Label(parent, text=key, bg="#3d3d3d", fg="white", font=("Consolas", 11, "bold"),
                        padx=8, pady=2)

    def build_shortcuts_page(self):
        outer, inner = self._page()
        self.label(inner, "Keyboard shortcuts", 20, True).pack(anchor="w")
        self.label(inner, "You can do everything with the mouse too. The keys are just faster.",
                   10, color=MUTED).pack(anchor="w", pady=(2, 16))
        sections = [
            ("While sorting  (Keep / Delete)", [
                (["N", "←"], "No: copy to Delete"),
                (["Y", "→"], "Yes: then choose which Keep folder"),
                (["1", "–", "9"], "Straight into that Keep folder (skips the question)"),
                (["P"], "Play a video, or a Live Photo's clip"),
                (["Space"], "Skip for now (it comes back next time)"),
                (["Backspace"], "Undo the last one (Z works too)"),
                (["R"], "Rename the copy (type, then Enter). Its RAW / .xmp / clip get the same name"),
                (["I"], "Show or hide the details panel"),
                (["Esc"], "Back to the menu"),
            ]),
            ("After pressing Yes  (choosing a folder)", [
                (["Enter"], "Just Keep (no subfolder)"),
                (["1", "–", "9"], "That folder"),
                (["F"], "New folder: type a name and the photo goes straight in"),
                (["Esc"], "Cancel, back to Yes / No"),
            ]),
            ("Straight into my own folders  (the other mode)", [
                (["1", "–", "9"], "Into that folder"),
                (["Space"], "Skip"),
                (["Backspace"], "Undo"),
            ]),
            ("Anywhere", [
                (["Enter"], "On the “Here's what I found” screen: start sorting"),
                (["F1"], "Switch between these help tabs"),
                (["Esc"], "From a help tab, back to sorting"),
            ]),
        ]
        for title, rows in sections:
            sec = tk.Frame(inner, bg=PANEL, padx=20, pady=14)
            sec.pack(anchor="w", fill="x", pady=(0, 12))
            self.label(sec, title, 12, True).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
            for i, (keys, what) in enumerate(rows, 1):
                kf = tk.Frame(sec, bg=PANEL)
                kf.grid(row=i, column=0, sticky="w", pady=3, padx=(0, 18))
                for k in keys:
                    if k in ("–", "/"):
                        self.label(kf, k, 10, color=MUTED).pack(side="left", padx=2)
                    else:
                        self._chip(kf, k).pack(side="left", padx=(0, 4))
                self.label(sec, what, 11).grid(row=i, column=1, sticky="w")
            sec.grid_columnconfigure(0, minsize=170)
            sec.grid_columnconfigure(1, weight=1)  # keep everything left-aligned in every box
        return outer

    def build_help_page(self):
        outer, inner = self._page()
        self.label(inner, "How to use Photo Sorter", 20, True).pack(anchor="w")
        self.label(inner, "Flick through your photos one by one and sort each with a key press.",
                   10, color=MUTED).pack(anchor="w", pady=(2, 16))

        def card(title, lines, numbered=False):
            c = tk.Frame(inner, bg=PANEL, padx=20, pady=14)
            c.pack(anchor="w", fill="x", pady=(0, 12))
            self.label(c, title, 12, True).pack(anchor="w", pady=(0, 6))
            for i, line in enumerate(lines, 1):
                row = tk.Frame(c, bg=PANEL)
                row.pack(anchor="w", fill="x", pady=2)
                self.label(row, f"{i}." if numbered else "•", 11, True, color="#4cc38a", width=3,
                           anchor="nw").pack(side="left", anchor="n")
                self.label(row, line, 11, justify="left", wraplength=720, anchor="w").pack(side="left", anchor="w")

        card("Getting started", [
            "On the Sort tab, click Browse and pick the top folder of your photos. Every folder inside it is "
            "searched, however deeply nested.",
            "The sorted folder fills itself in as “<your folder> - Sorted”, right next to it. Change it if you like.",
            "Pick Keep / Delete and click Start sorting.",
            "For each photo press N (no) or Y (yes). After Yes, pick a folder, or press F to make a new one.",
            "Close the window whenever you like. Next time, click Continue under “Pick up where you left off” "
            "(or Open a progress file… to pick one yourself) and it carries on from the same photo.",
        ], numbered=True)
        card("What ends up where", [
            "Photos go in  Photos\\Keep\\…  and  Photos\\Delete.  Videos get their own  Videos\\Keep\\…  "
            "and  Videos\\Delete,  using the same folder names.",
            "iPhone Live Photos count as one item. The short clip goes wherever its photo goes.",
            "When you finish, the summary shows how everything was sorted. Click a folder there to open it.",
        ])
        card("Your originals are safe", [
            "Everything is COPIED. Nothing is ever moved or deleted, so your original folder stays exactly as it was.",
            "The Delete folder is for you to check and then delete yourself, once you're happy.",
            "Because things are copied, you need free space roughly equal to what you're sorting.",
            "Undo (Backspace) removes the copy it just made, so mistakes are easy to fix.",
        ])
        card("Good to know", [
            "The file  .photo_sorter_log.jsonl  in the sorted folder is the app's record of every decision. "
            "Don't delete it, or the app forgets your progress.",
            "It recognises photos by where they are. If you move or rename the originals, they'll come up again.",
            "Works with JPG, PNG, HEIC, WEBP, GIF, BMP, TIFF, PSD, camera RAW (CR2, CR3, NEF, ARW, DNG, ORF, RAF, RW2…) "
            "and most video types (MP4, MOV, AVI, MKV…). RAW+JPEG pairs count as one photo, and .xmp / .aae edits files go with their photo.",
            "Before sorting starts you see what was found, and anything left out. The full list is saved as Skipped files.csv in the sorted folder.",
            "Press I to hide the details panel if you want a bigger picture.",
            "Rename as you go: press R (or click the Save as box), type a name, Enter. Only the copy is renamed, never "
            "the original. Or choose \u201cBy date taken\u201d on the first screen to name every copy like 2017-01-26 14.30.12.jpg.",
        ])
        return outer

    # ---------------- setup screen

    def clear(self):
        self.root.unbind("<Configure>")
        self.key_handler = None
        if self.frame is not None:
            self.frame.destroy()
        self.frame = tk.Frame(self.pages["sort"], bg=BG)
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
        holder = tk.Frame(self.frame, bg=BG)
        holder.place(relx=0.5, rely=0.5, anchor="center")
        box = tk.Frame(holder, bg=PANEL, padx=30, pady=24)
        box.pack(side="left", anchor="n")
        self.build_resume_panel(holder)

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
        self.label(box, "2. Where to put the sorted folders   (filled in for you: a  \"- Sorted\"  folder next to it)",
                   ).grid(row=5, column=0, columnspan=3, sticky="w", pady=(12, 0))
        tk.Entry(box, textvariable=self.out_var, width=60, font=("Segoe UI", 10)).grid(
            row=6, column=0, columnspan=2, sticky="we", pady=4)
        self.button(box, "Browse…", self.pick_output, size=9).grid(row=6, column=2, padx=(8, 0))

        self._auto_out = default_output(self.src_var.get()) if self.src_var.get().strip() else ""
        if not self.out_var.get().strip() and self._auto_out:
            self.out_var.set(self._auto_out)
        self.src_var.trace_add("write", lambda *a: self.follow_source())

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

        self.label(box, "4. Name the copies   (you can still rename any photo as you go: press R)").grid(
            row=11, column=0, columnspan=3, sticky="w", pady=(12, 4))
        self.naming_var = tk.StringVar(value=s.get("naming", "original"))
        rb2 = dict(rb, command=None)
        tk.Radiobutton(box, text="Keep their original names   (IMG_0042.jpg)", value="original",
                       variable=self.naming_var, **rb2).grid(row=12, column=0, columnspan=3, sticky="w")
        tk.Radiobutton(box, text="By date taken   (2017-01-26 14.30.12.jpg)", value="date",
                       variable=self.naming_var, **rb2).grid(row=13, column=0, columnspan=3, sticky="w")

        self.button(box, "Start sorting  ▶", self.start, color=GREEN, size=13).grid(
            row=14, column=0, columnspan=3, pady=(18, 0), sticky="we")

        heic = "" if HEIC_OK else "\n(iPhone .heic photos need Install.bat to be run.)"
        self.label(box, "Tip: close the window whenever you like - it remembers where you got to." + heic,
                   9, color=MUTED, justify="left").grid(row=15, column=0, columnspan=3, sticky="w", pady=(10, 0))

    # ---------------- pick up where you left off

    def recent_sorts(self):
        """Recent sorts whose progress file still exists, newest first."""
        out = []
        for r in self.settings.get("recent", []):
            if os.path.exists(os.path.join(r.get("output", ""), LOG_NAME)):
                out.append(r)
        return out[:5]

    def remember_sort(self, total):
        entry = {"source": self.src, "output": self.out, "mode": self.mode, "naming": self.naming,
                 "subfolders": self.sub_var.get(), "categories": self.settings.get("categories", ""),
                 "total": total, "used": datetime.now().isoformat(timespec="minutes")}
        rest = [r for r in self.settings.get("recent", [])
                if norm(r.get("output", "")) != norm(self.out)]
        self.settings["recent"] = [entry] + rest[:9]
        save_settings(self.settings)

    def forget_sort(self, output):
        self.settings["recent"] = [r for r in self.settings.get("recent", []) if norm(r.get("output", "")) != norm(output)]
        save_settings(self.settings)
        self.show_setup()

    def build_resume_panel(self, holder):
        panel = tk.Frame(holder, bg=PANEL, padx=24, pady=24, width=420)
        panel.pack(side="left", anchor="n", padx=(16, 0), fill="y")
        self.label(panel, "Pick up where you left off", 15, True).pack(anchor="w")
        self.label(panel, "Your progress is saved after every photo.", 9, color=MUTED).pack(anchor="w", pady=(0, 12))
        recent = self.recent_sorts()
        if not recent:
            self.label(panel, "Nothing to carry on with yet. Sorts you start will show up here.",
                       10, color=MUTED, wraplength=360, justify="left").pack(anchor="w", pady=(0, 8))
        for r in recent:
            done = len(read_log(os.path.join(r["output"], LOG_NAME)))
            total = max(r.get("total") or 0, done)
            row = tk.Frame(panel, bg="#363636", padx=14, pady=10)
            row.pack(fill="x", pady=(0, 8))
            top = tk.Frame(row, bg="#363636")
            top.pack(fill="x")
            tk.Label(top, text=os.path.basename(r["source"].rstrip("\\/")) or r["source"], bg="#363636", fg=FG,
                     font=("Segoe UI", 12, "bold")).pack(side="left")
            x = tk.Label(top, text="✕", bg="#363636", fg=MUTED, font=("Segoe UI", 10), cursor="hand2")
            x.pack(side="right")
            x.bind("<Button-1>", lambda e, o=r["output"]: self.forget_sort(o))
            pct = 100 * done / total if total else 0
            when = ""
            try:
                when = "  ·  last used " + datetime.fromisoformat(r["used"]).strftime("%d %b %Y")
            except Exception:
                pass
            tk.Label(row, text=f"{done:,} of {total:,} sorted  ({pct:.0f}%)" + when, bg="#363636",
                     fg=MUTED, font=("Segoe UI", 9)).pack(anchor="w", pady=(2, 4))
            bar = tk.Canvas(row, height=6, width=340, bg="#2a2a2a", highlightthickness=0)
            bar.pack(anchor="w", fill="x")
            if pct:
                bar.create_rectangle(0, 0, max(2, round(340 * pct / 100)), 6, fill="#4cc38a", width=0)
            tk.Label(row, text="→ " + r["output"], bg="#363636", fg="#7a7a7a", font=("Segoe UI", 8),
                     wraplength=340, justify="left").pack(anchor="w", pady=(4, 6))
            if os.path.isdir(r["source"]):
                self.button(row, "Continue  ▶", lambda r=r: self.continue_sort(r), color=GREEN, size=10).pack(anchor="w")
            else:
                tk.Label(row, text="Photo folder not found - is the drive plugged in?", bg="#363636",
                         fg="#e06c6c", font=("Segoe UI", 9)).pack(anchor="w")
        self.button(panel, "Open a progress file…", self.open_progress_file, color="#555555", size=10).pack(
            anchor="w", pady=(8, 0))
        self.label(panel, "Pick the  .photo_sorter_log.jsonl  inside any sorted folder.", 8,
                   color=MUTED).pack(anchor="w", pady=(4, 0))

    def fill_form(self, info):
        if info.get("source"):
            self.src_var.set(info["source"])
        if info.get("output"):
            self.out_var.set(info["output"])
        self.mode_var.set(info.get("mode", "keep"))
        self.sub_var.set(info.get("subfolders", True))
        self.naming_var.set(info.get("naming", "original"))
        if info.get("categories"):
            self.cat_text.configure(state="normal")
            self.cat_text.delete("1.0", "end")
            self.cat_text.insert("1.0", info["categories"])
        self.update_mode()

    def continue_sort(self, entry):
        self.fill_form(entry)
        self.start()

    def open_progress_file(self):
        path = filedialog.askopenfilename(title="Open a Photo Sorter progress file",
                                          filetypes=[("Photo Sorter progress", "*.jsonl"), ("All files", "*.*")])
        if not path:
            return
        try:
            info, exact = read_session(path)
        except Exception as e:
            messagebox.showerror("Photo Sorter", f"Couldn't read that file:\n{e}")
            return
        info["output"] = os.path.dirname(os.path.abspath(path))
        self.fill_form(info)
        src = info.get("source", "")
        if not src or not os.path.isdir(src):
            messagebox.showwarning("Photo Sorter", "Found your progress, but not the photo folder it came from"
                                   + (f":\n{src}" if src else ".") + "\n\nBrowse to the photo folder, then click Start sorting.")
            return
        note = "" if exact else "\n\n(This file is from an older version, so the settings are a best guess. Check them first if you like.)"
        if messagebox.askyesno("Photo Sorter", f"Carry on sorting\n{src}\n\ninto\n{info['output']}?" + note):
            self.start()

    def update_mode(self):
        self.cat_text.configure(state="normal" if self.mode_var.get() == "cats" else "disabled",
                                bg="white" if self.mode_var.get() == "cats" else "#777777")

    def follow_source(self):
        """Typed or pasted a new photo folder? Move the automatic destination with it -
        but never overwrite a destination the person chose themselves."""
        src = self.src_var.get().strip()
        new = default_output(src) if src else ""
        cur = self.out_var.get().strip()
        if not cur or norm(cur) == norm(self._auto_out or cur + "x"):
            self.out_var.set(new)
        self._auto_out = new

    def pick_source(self):
        folder = filedialog.askdirectory(title="Choose the folder of photos to sort")
        if folder:
            self.src_var.set(os.path.normpath(folder))
            self._auto_out = default_output(folder)
            self.out_var.set(self._auto_out)

    def pick_output(self):
        folder = filedialog.askdirectory(title="Choose where the sorted folders should go")
        if folder:
            self.out_var.set(os.path.normpath(folder))

    def start(self):
        src = self.src_var.get().strip().strip('"')
        out = self.out_var.get().strip().strip('"') or (default_output(src) if src else "")
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

        self.naming = self.naming_var.get()
        self.settings.update(source=src, output=out, mode=mode, subfolders=self.sub_var.get(), naming=self.naming,
                             categories=self.cat_text.get("1.0", "end").strip())
        save_settings(self.settings)

        self.clear()
        self.label(self.frame, "Finding photos and videos…", 16).place(relx=0.5, rely=0.5, anchor="center")
        self.root.update()

        try:
            os.makedirs(out, exist_ok=True)
            photos, self.companions, self.report = find_photos(src, self.sub_var.get(), out)
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
        # sorted with an older version? bring along any Live clips / RAW / edits files that were missed
        originals = {}
        for p in photos:
            originals[norm(p)] = p
        for key, (c, dest) in done.items():
            extras = self.companions.get(key)
            if extras and dest and key in originals:
                copy = os.path.join(out, space_of(c), os.path.basename(dest))
                stem = os.path.splitext(os.path.basename(originals[key]))[0]
                for extra in extras:
                    target = os.path.splitext(copy)[0] + os.path.basename(extra)[len(stem):]
                    if os.path.exists(copy) and not os.path.exists(target):
                        try:
                            shutil.copy2(extra, target)
                        except Exception:
                            pass
        self.total = len(photos)
        if photos:
            try:
                append_log(self.log_path, {"session": {
                    "source": src, "mode": mode, "subfolders": self.sub_var.get(), "naming": self.naming,
                    "categories": self.settings.get("categories", ""), "total": len(photos),
                    "started": datetime.now().isoformat(timespec="seconds"), "version": VERSION}})
            except Exception:
                pass
            self.remember_sort(len(photos))
        self.already = sum(1 for p in photos if norm(p) in done)
        self.queue = [p for p in photos if norm(p) not in done]
        self.pos = 0
        self.history = []  # for undo: (pos, src, dest)
        self.decision_times = []  # when each decision was made, for the time-left estimate
        self.counts = {}
        for c, _ in done.values():
            self.counts[space_of(c)] = self.counts.get(space_of(c), 0) + 1

        try:
            self.skipped_file = write_skipped_list(out, self.report)
        except Exception:
            self.skipped_file = None
        self.show_found(photos)

    def show_found(self, photos):
        """What the scan found - and anything it's leaving out - before sorting starts."""
        self.clear()
        r = self.report
        n_raw = sum(1 for p in photos if is_raw(p))
        n_vid = sum(1 for p in photos if is_video(p))
        n_photo = len(photos) - n_raw - n_vid
        box = tk.Frame(self.frame, bg=PANEL, padx=36, pady=28)
        box.place(relx=0.5, rely=0.5, anchor="center")
        self.label(box, "Here's what I found", 20, True).pack(anchor="w")
        self.label(box, self.src, 9, color=MUTED).pack(anchor="w", pady=(2, 14))

        tiles = tk.Frame(box, bg=PANEL)
        tiles.pack(anchor="w")
        spec = [("Photos", n_photo, FG), ("RAW", n_raw, "#f0b35a"), ("Videos", n_vid, "#a78bfa")]
        for title, n, color in spec:
            if not n and title != "Photos":
                continue
            t = tk.Frame(tiles, bg="#363636", padx=18, pady=10)
            t.pack(side="left", padx=(0, 10))
            tk.Label(t, text=f"{n:,}", bg="#363636", fg=color, font=("Segoe UI", 22, "bold")).pack(anchor="w")
            tk.Label(t, text=title.upper(), bg="#363636", fg=MUTED, font=("Segoe UI", 9)).pack(anchor="w")

        notes = []
        if r["pairs"]:
            notes.append(f"{r['pairs']:,} RAW file{'s are' if r['pairs'] != 1 else ' is'} paired with a JPEG of the same name, "
                         "so each pair counts as one photo")
        if r["live"]:
            notes.append(f"{r['live']:,} iPhone Live Photo clip{'s go' if r['live'] != 1 else ' goes'} along with {'their photos' if r['live'] != 1 else 'its photo'}")
        if r["sidecars"]:
            notes.append(f"{r['sidecars']:,} edits file{'s' if r['sidecars'] != 1 else ''} (.xmp / .aae) "
                         f"{'go' if r['sidecars'] != 1 else 'goes'} along with {'their photos' if r['sidecars'] != 1 else 'its photo'}")
        if self.already:
            notes.append(f"{self.already:,} already sorted, so {len(self.queue):,} to go")
        for n in notes:
            self.label(box, "•  " + n, 10, color=FG).pack(anchor="w", pady=1)

        # anything not included
        skipped = r["skipped"]
        n_skip = sum(e["count"] for e in skipped.values())
        sec = tk.Frame(box, bg="#363636", padx=16, pady=12)
        sec.pack(anchor="w", fill="x", pady=(16, 0))
        if not n_skip:
            tk.Label(sec, text="✓  Every file was included. Nothing skipped.", bg="#363636", fg="#4cc38a",
                     font=("Segoe UI", 11, "bold")).pack(anchor="w")
        else:
            tk.Label(sec, text=f"Not included:  {n_skip:,} file{'s' if n_skip != 1 else ''}"
                     + f"  ({human_size(sum(e['bytes'] for e in skipped.values()))})",
                     bg="#363636", fg="#f0b35a", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 6))
            grid = tk.Frame(sec, bg="#363636")
            grid.pack(anchor="w")
            rows = sorted(skipped.items(), key=lambda kv: -kv[1]["count"])
            for i, (kind, e) in enumerate(rows[:10]):
                example = os.path.relpath(e["paths"][0], self.src)
                for col, (txt, fg, w) in enumerate([(f"{e['count']:,}", FG, 6), (kind, FG, 26),
                                                    (human_size(e["bytes"]), MUTED, 10), ("e.g.  " + example, MUTED, 0)]):
                    tk.Label(grid, text=txt, bg="#363636", fg=fg, font=("Segoe UI", 10), anchor="w",
                             width=w or None).grid(row=i, column=col, sticky="w", padx=(0, 8))
            if len(rows) > 10:
                tk.Label(sec, text=f"…and {len(rows) - 10} more types", bg="#363636", fg=MUTED,
                         font=("Segoe UI", 9)).pack(anchor="w")
            tk.Label(sec, text="These stay exactly where they are. The full list is saved as  Skipped files.csv  "
                     "in the sorted folder.", bg="#363636", fg=MUTED, font=("Segoe UI", 9),
                     wraplength=640, justify="left").pack(anchor="w", pady=(8, 0))
        extra = []
        if r["junk"]:
            extra.append(f"{r['junk']:,} system file{'s' if r['junk'] != 1 else ''} (Thumbs.db, desktop.ini…)")
        if r["hidden_dirs"]:
            extra.append(f"{r['hidden_dirs']:,} hidden folder{'s' if r['hidden_dirs'] != 1 else ''}")
        if extra:
            self.label(box, "Also ignored: " + ", ".join(extra), 9, color=MUTED).pack(anchor="w", pady=(6, 0))

        row = tk.Frame(box, bg=PANEL)
        row.pack(anchor="w", pady=(18, 0))
        if photos:
            go = "Start sorting  ▶   (Enter)" if not self.already else "Carry on sorting  ▶   (Enter)"
            self.button(row, go, self.show_sorter, color=GREEN, size=12).pack(side="left")
        if self.skipped_file:
            self.button(row, "Open skipped list", lambda: os.startfile(self.skipped_file),
                        color="#555555").pack(side="left", padx=8)
        self.button(row, "Back", self.show_setup, color="#555555").pack(side="left", padx=(0 if self.skipped_file else 8, 0))
        if not photos:
            self.label(box, "No photos or videos found in that folder.", 11, True, color="#e06c6c").pack(anchor="w", pady=(12, 0))

        def keys(e):
            if e.keysym in ("Return", "KP_Enter", "space") and photos:
                self.show_sorter()
            elif e.keysym == "Escape":
                self.show_setup()
        self.key_handler = keys

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

        # progress bar right under the top bar
        self.pbar = tk.Canvas(self.frame, height=8, bg="#3a3a3a", highlightthickness=0)
        self.pbar.pack(fill="x")
        self.pbar.bind("<Configure>", lambda e: self.draw_progress())

        bottom = tk.Frame(self.frame, bg=PANEL, padx=12, pady=12)
        bottom.pack(side="bottom", fill="x")

        # photo details panel on the right (press I to hide/show)
        self.side = tk.Frame(self.frame, bg=PANEL, width=330)
        self.side.pack_propagate(False)

        nb = tk.Frame(self.side, bg=PANEL, padx=16, pady=12)
        nb.pack(fill="x")
        self.label(nb, "SAVE AS", 9, color=MUTED).pack(anchor="w")
        row = tk.Frame(nb, bg=PANEL)
        row.pack(fill="x", pady=(2, 0))
        self.name_var = tk.StringVar()
        self.name_entry = tk.Entry(row, textvariable=self.name_var, font=("Segoe UI", 11), bg="#3a3a3a", fg=FG,
                                   insertbackground=FG, relief="flat", highlightthickness=1,
                                   highlightbackground="#3a3a3a", highlightcolor="#4cc38a")
        self.name_entry.pack(side="left", fill="x", expand=True, ipady=4)
        self.ext_lbl = self.label(row, "", 11, color=MUTED)
        self.ext_lbl.pack(side="left", padx=(4, 0))
        self.name_hint = self.label(nb, "R to rename  ·  Enter to keep it  ·  Esc to undo", 8, color=MUTED)
        self.name_hint.pack(anchor="w", pady=(3, 0))
        self.name_entry.bind("<Return>", lambda e: self.root.focus_set())
        self.name_entry.bind("<KP_Enter>", lambda e: self.root.focus_set())
        self.name_entry.bind("<Escape>", lambda e: self.reset_name(focus_back=True))
        self.name_entry.bind("<KeyRelease>", lambda e: self._name_typed(e))
        self.name_edited = False
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

        self.key_handler = self.on_key
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
        elif key == "r":
            self.rename_now()
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
        if is_video(path):
            return path
        return next((c for c in self.companions.get(norm(path), []) if is_video(c)), None)

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

    # ---------------- renaming

    def suggested_stem(self, path, meta=None):
        """The name a copy gets unless you type your own."""
        stem = os.path.splitext(os.path.basename(path))[0]
        if getattr(self, "naming", "original") == "date" and meta:
            taken = dict(meta).get("_taken")
            if taken:
                try:
                    return datetime.fromisoformat(taken).strftime("%Y-%m-%d %H.%M.%S")
                except Exception:
                    pass
        return stem

    def reset_name(self, focus_back=False, meta=None):
        path = getattr(self, "current_path", None)
        if not path or not hasattr(self, "name_var"):
            return
        if meta is None:
            fut = self.cache.get(path)
            meta = fut.result()[2] if fut and fut.done() else None
        self.name_var.set(self.suggested_stem(path, meta))
        self.ext_lbl.config(text=os.path.splitext(path)[1])
        self.name_edited = False
        if focus_back:
            self.root.focus_set()

    def _name_typed(self, e):
        if e.keysym not in ("Return", "KP_Enter", "Escape", "Tab", "Shift_L", "Shift_R", "Control_L",
                            "Control_R", "Left", "Right", "Home", "End"):
            self.name_edited = True

    def rename_now(self):
        if not self.side.winfo_ismapped():
            self.toggle_info()
        self.name_entry.focus_set()
        self.name_entry.select_range(0, "end")
        self.name_entry.icursor("end")

    def chosen_stem(self, src):
        """Typed name if you changed it, otherwise the automatic one."""
        if src == getattr(self, "current_path", None) and self.name_edited:
            typed = clean_filename(self.name_var.get())
            if typed:
                return typed
        meta = None
        try:
            meta = self.prefetch(src).result(timeout=15)[2]  # date-taken naming needs the details
        except Exception:
            pass
        return clean_filename(self.suggested_stem(src, meta)) or os.path.splitext(os.path.basename(src))[0]

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
        for extra in self.companions.get(norm(self.current_path), []):
            name = os.path.basename(extra)
            if is_video(extra):
                rows.append(("Live Photo", "Yes - its video clip is kept with it. Press P to play."))
            elif is_raw(extra):
                rows.append(("RAW file", f"{name} goes with it"))
            else:
                rows.append(("Edits file", f"{name} goes with it"))
        rows.insert(1 if rows and rows[0][0] == "Date taken" else 0, ("Folder", folder or "(top folder)"))
        for label, value in rows:
            if label.startswith("_"):
                continue  # hidden values used behind the scenes (e.g. the exact date for naming)
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
        left = self.time_left()
        self.progress_lbl.config(text=f"{done_now + 1:,} of {self.total:,}   ({pct:.0f}% done)"
                                      + (f"   ·   {left}" if left else ""))
        self.draw_progress()
        rel = os.path.relpath(path, self.src)
        self.name_lbl.config(text=rel)
        self.current_path = path
        self.name_edited = False
        self.reset_name(meta=None)
        if self.root.focus_get() is self.name_entry:
            self.root.focus_set()
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
        if not self.name_edited:
            self.reset_name(meta=meta)
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

    def draw_progress(self):
        bar = getattr(self, "pbar", None)
        if not bar or not bar.winfo_exists():
            return
        w = bar.winfo_width()
        frac = (self.already + self.pos) / self.total if self.total else 1
        bar.delete("all")
        if frac > 0:
            bar.create_rectangle(0, 0, max(2, round(w * frac)), 8, fill="#4cc38a", width=0)

    def time_left(self):
        """Rough estimate from your own recent pace (breaks longer than a minute don't count)."""
        t = self.decision_times[-40:]
        if len(t) < 5:
            return ""
        gaps = [min(b - a, 60) for a, b in zip(t, t[1:])]
        per_item = sum(gaps) / len(gaps)
        remaining = (len(self.queue) - self.pos) * per_item
        if remaining < 60:
            return "under a minute left"
        mins = round(remaining / 60)
        if mins < 60:
            return f"about {mins} min left"
        h, m = divmod(mins, 60)
        return f"about {h} h {m:02d} min left" if h < 10 else f"about {h} hours left"

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
        stem = os.path.splitext(os.path.basename(src))[0]
        travel = self.companions.get(norm(src), [])
        # IMG_1.JPG + IMG_1.CR2 + IMG_1.CR2.xmp -> keep the same endings on the copies
        endings = [os.path.basename(t)[len(stem):] for t in travel]
        extras = []
        try:
            os.makedirs(folder, exist_ok=True)
            dest = unique_dest(folder, self.chosen_stem(src) + os.path.splitext(src)[1], endings)
            shutil.copy2(src, dest)
            for t, ending in zip(travel, endings):
                extras.append(os.path.splitext(dest)[0] + ending)
                shutil.copy2(t, extras[-1])
            append_log(self.log_path, {"src": src, "cat": space, "dest": dest, "extra": extras})
        except Exception as e:
            messagebox.showerror("Photo Sorter", f"Couldn't copy this file:\n{e}")
            return
        self.counts[space] = self.counts.get(space, 0) + 1
        self.history.append((self.pos, src, dest, space, extras))
        self.decision_times.append(time.monotonic())
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
        self.key_handler = lambda e: self.undo() if e.keysym in ("BackSpace", "z") else None


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
