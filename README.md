# Photo Sorter

Quickly sort thousands of photos and videos one at a time with a click or a key. No Bridge, no faff.

- **No** sends it to `Delete`.
- **Yes** asks which folder inside `Keep` it belongs in (Friends, Holiday, Cats…). You can make a new folder on the spot.

A side panel shows each photo's details: date taken, camera, lens, settings, size and location.

Photos are **copied**, never moved or deleted, so your originals are always safe.
Close it whenever you like. Next time you open the same folder, it picks up where you left off.

---

## ⬇️ Download (Windows)

### **[Download PhotoSorter.exe](https://github.com/Elliot95/photo-sorter/releases/latest/download/PhotoSorter.exe)**

That's it: no installing. Put the file wherever you like (Desktop, Documents…) and double-click it.
It takes a few seconds to open.

> **"Windows protected your PC"?** This shows up for any app that isn't from a big company.
> Click **More info**, then **Run anyway**. You only have to do this the first time.

## Using it

Double-click **`PhotoSorter.exe`**. The window has three tabs along the top: **Sort**, **Shortcuts** and **How to use**. Press **F1** to jump to the shortcuts at any time, and **Esc** to get back to sorting. On the **Sort** tab:

1. **Browse** to the top folder of your photos. Every folder inside it is searched, however deeply nested.
2. Choose where the sorted folders should go. It suggests `<your folder> - Sorted`.
3. Pick how to sort, then click **Start**.

### Keep / Delete

| Key | Does |
|---|---|
| `N` or `←` | **No**: copy to `Delete` |
| `Y` or `→` | **Yes**: choose a folder for it (see below) |
| `1`–`9` | Skip the question and send it straight to that `Keep` folder |
| `P` | Play a video (or a Live Photo's clip) |
| `Space` | Skip for now (it comes back next time) |
| `Backspace` | Undo the last one |
| `I` | Show or hide the details panel |
| `Esc` | Back to the menu |

**After Yes**, a row of folder buttons appears:

| Key | Does |
|---|---|
| `Enter` | Just `Keep` (no subfolder) |
| `1`–`9` | That folder, e.g. `Photos\Keep\Holiday` |
| `F` | **New folder**: type a name, and the photo goes straight in it |
| `Esc` | Cancel, back to Yes / No |

The folders you make stay there, so they're ready for the next photo and the next time you open the app.

### Straight into your own folders

Want to skip Keep / Delete? Choose **Straight into my own folders** on the menu and type up to 9 names, one per line.
Press `1`–`9` (or click the buttons) to send each photo to that folder.

---

## Videos 🎬

Videos from any phone or camera (iPhone, Android, GoPro, Canon…) come up in the same queue as photos.

- You see a still from the video with a ▶ button. Press **P** or click ▶ to watch it in your normal video player, then close the player and press Yes / No.
- The details panel shows the length, resolution, date, camera and location.
- Photos and videos each get their **own space**, but the **folder names are shared**:

```
My Photos - Sorted\
├── Photos\
│   ├── Keep\
│   │   ├── Holiday\    ← holiday photos
│   │   └── Cats\
│   └── Delete\
└── Videos\
    ├── Keep\
    │   ├── Holiday\    ← holiday videos
    │   └── Cats\
    └── Delete\
```

**iPhone Live Photos** (a photo plus a short clip with the same name) count as **one** item. You see the photo with a **◉ LIVE** badge, **P** plays the clip, and wherever the photo goes, its clip goes too.
Android motion photos keep their clip inside the photo file, so they already count as one.

No videos in your folder? Nothing changes. It works just like before.

---

## Good to know

- **Photos:** JPG, PNG, HEIC (iPhone), WEBP, GIF, BMP, TIFF.
  **Videos:** MP4, MOV, M4V, AVI, MKV, WMV, 3GP, MTS/M2TS, WEBM, MPG.
- **The `Delete` folder is for you to delete yourself.** The app never deletes anything. `Delete` just holds copies of everything you said No to, so you can check them before throwing them away. Once you're happy with the sort, you can delete the `Delete` folder (and the original folder, since everything you wanted is now copied into `Keep`).
- Because files are copied, you need free disk space roughly equal to what you're sorting.
- Files with the same name from different folders don't overwrite each other: the second becomes `IMG_0001 (1).jpg`.
- **How it remembers where you got to:** the sorted folder has a file called `.photo_sorter_log.jsonl` (don't delete it). It's a running record with one line per decision: which original file, which folder it went to, and where the copy was saved (plus a line when you press Undo). When you reopen a folder, any file whose original location is in that record is skipped. If you move or rename the originals, they'll come up again.
- Sorted a folder with an older version? Opening it again tidies your earlier folders into `Photos\` automatically, and adds any Live Photo clips that were missed.
- Folders whose names start with a dot (like `.thumbnails`) are skipped.

---

<details>
<summary>For tinkerers: run from the source code or build the .exe yourself</summary>

1. Install Python from [python.org/downloads](https://www.python.org/downloads/), ticking **"Add python.exe to PATH"**.
2. Download this repo (**Code → Download ZIP**) and unzip it.
3. Run `Install.bat` once, then `Photo Sorter.bat` to start it.
4. To build `PhotoSorter.exe` yourself, run `Build exe.bat`. The file appears in the `dist` folder.

</details>
