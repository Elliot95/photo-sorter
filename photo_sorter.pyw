"""
Photo Sorter - flick through a folder of photos and sort each one with a click or a key.

Round 1: Keep / Delete
Round 2: open the Keep folder and sort into your own folders (Friends, Holiday, Cats...)

Photos are COPIED, never moved or deleted, so the originals are always safe.
Progress is saved after every photo: close it any time and carry on later.
"""

import json
import os
import shutil
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


def find_photos(folder, include_subfolders, skip_folder):
    skip = norm(skip_folder)
    found = []
    if include_subfolders:
        for dirpath, dirnames, filenames in os.walk(folder):
            # never scan the output folder if it sits inside the source folder
            dirnames[:] = [
                d for d in dirnames
                if norm(os.path.join(dirpath, d)) != skip and not d.startswith(".")
            ]
            for name in filenames:
                if os.path.splitext(name)[1].lower() in IMAGE_EXTS:
                    found.append(os.path.join(dirpath, name))
    else:
        for name in os.listdir(folder):
            full = os.path.join(folder, name)
            if os.path.isfile(full) and os.path.splitext(name)[1].lower() in IMAGE_EXTS:
                found.append(full)
    found.sort(key=lambda p: p.lower())
    return found


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


def unique_dest(folder, filename):
    base, ext = os.path.splitext(filename)
    dest = os.path.join(folder, filename)
    n = 1
    while os.path.exists(dest):
        dest = os.path.join(folder, f"{base} ({n}){ext}")
        n += 1
    return dest


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
    lat = deg(gps[2], _clean(gps.get(1, "N")))
    lon = deg(gps[4], _clean(gps.get(3, "E")))
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


def load_preview(path, max_w, max_h):
    """Open an image, read its details, fix its rotation, shrink it to fit the screen.
    Runs in a background thread."""
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
        self.label(self.frame, "Finding photos…", 16).place(relx=0.5, rely=0.5, anchor="center")
        self.root.update()

        try:
            os.makedirs(out, exist_ok=True)
            photos = find_photos(src, self.sub_var.get(), out)
        except Exception as e:
            messagebox.showerror("Photo Sorter", f"Couldn't read the folders:\n{e}")
            self.show_setup()
            return

        self.src, self.out, self.mode, self.cats = src, out, mode, cats
        self.log_path = os.path.join(out, LOG_NAME)
        done = read_log(self.log_path)
        self.total = len(photos)
        self.already = sum(1 for p in photos if norm(p) in done)
        self.queue = [p for p in photos if norm(p) not in done]
        self.pos = 0
        self.history = []  # for undo: (pos, src, dest)
        self.counts = {c: 0 for c in cats}
        for c, _ in done.values():
            self.counts[c] = self.counts.get(c, 0) + 1

        if not photos:
            messagebox.showinfo("Photo Sorter", "No photos found in that folder.")
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
        keep = os.path.join(self.out, "Keep")
        try:
            return sorted((d for d in os.listdir(keep)
                           if os.path.isdir(os.path.join(keep, d)) and not d.startswith(".")), key=str.lower)
        except FileNotFoundError:
            return []

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
        elif key == "space":
            self.skip()
        elif key in ("BackSpace", "z") :
            self.undo()
        elif key == "Escape":
            self.back_to_menu()

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
        t.insert("end", "Photo details\n", "head")
        folder = os.path.dirname(os.path.relpath(self.current_path, self.src))
        rows = list(meta)
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
        else:
            c.create_text(w // 2, h // 2, text="⚠  " + self.current_info + "\nYou can still sort it.",
                          fill=FG, font=("Segoe UI", 16), justify="center")
            return
        c.create_text(w // 2, h - 14, text=self.current_info, fill=MUTED, font=("Segoe UI", 10))

    def flash(self, cat):
        b = self.cat_buttons.get(cat)
        if b:
            b.config(relief="sunken")
            self.root.after(120, lambda: b.winfo_exists() and b.config(relief="flat"))

    def choose(self, cat):
        if self.pos >= len(self.queue):
            return
        src = self.queue[self.pos]
        folder = os.path.join(self.out, cat)
        try:
            os.makedirs(folder, exist_ok=True)
            dest = unique_dest(folder, os.path.basename(src))
            shutil.copy2(src, dest)
            append_log(self.log_path, {"src": src, "cat": cat, "dest": dest})
        except Exception as e:
            messagebox.showerror("Photo Sorter", f"Couldn't copy this photo:\n{e}")
            return
        self.counts[cat] = self.counts.get(cat, 0) + 1
        self.history.append((self.pos, src, dest, cat))
        self.flash(cat)
        self.pos += 1
        if getattr(self, "picking", False) or (self.mode == "keep" and cat.startswith("Keep" + os.sep)):
            self.show_main_buttons()  # back to Yes/No (and pick up any new folder)
        self.show_current()

    def skip(self):
        if getattr(self, "picking", False):
            self.show_main_buttons()
        if self.pos < len(self.queue):
            self.history.append((self.pos, None, None, None))
            self.pos += 1
            self.show_current()

    def undo(self):
        if not self.history:
            return
        pos, src, dest, cat = self.history.pop()
        if src is not None:
            try:
                if dest and os.path.exists(dest):
                    os.remove(dest)  # only ever removes the COPY we just made
                append_log(self.log_path, {"undo": src})
                self.counts[cat] -= 1
            except Exception as e:
                messagebox.showerror("Photo Sorter", f"Couldn't undo:\n{e}")
                self.history.append((pos, src, dest, cat))
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

    def show_done(self):
        self.clear()
        box = tk.Frame(self.frame, bg=PANEL, padx=40, pady=30)
        box.place(relx=0.5, rely=0.5, anchor="center")
        self.label(box, "All done! 🎉", 22, True).pack(anchor="w")
        lines = "\n".join(f"{c}:  {n:,}" for c, n in self.counts.items())
        self.label(box, lines, 12, justify="left").pack(anchor="w", pady=12)
        skipped = sum(1 for h in self.history if h[1] is None)
        if skipped:
            self.label(box, f"{skipped} skipped - they'll come up again next time you open this folder.",
                       10, color=MUTED).pack(anchor="w")
        row = tk.Frame(box, bg=PANEL)
        row.pack(anchor="w", pady=(16, 0))
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
