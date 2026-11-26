# Photo Sorter

Quickly sort thousands of photos and videos one at a time with a click or a key. No Bridge, no faff.

- **No** sends it to `Delete`.
- **Yes** asks which folder inside `Keep` it belongs in (Friends, Holiday, Cats…). You can make a new folder on the spot.

A side panel shows each photo's details: date taken, camera, lens, settings, size and location.

Photos are **moved** into the sorted folders by default, so whatever is left in your folder is what you haven't sorted yet. Prefer to leave your folder untouched? Choose **Copy** instead.
**Nothing is ever deleted.** Even `Delete` is just a folder, and Undo puts a photo back where it came from. When you're done, one click tidies away the empty folders that moving leaves behind.
Close it whenever you like. Next time, click **Continue** under **Pick up where you left off** on the first screen, or **Open a progress file…** to pick the `.photo_sorter_log.jsonl` from any sorted folder.

---

## ⬇️ Download (Windows)

### **[Download PhotoSorter.exe](https://github.com/Elliot95/photo-sorter/releases/latest/download/PhotoSorter.exe)**

That's it: no installing. Put the file wherever you like (Desktop, Documents…) and double-click it.
It takes a few seconds to open.

> **"Windows protected your PC"?** This shows up for any app that isn't from a big company.
> Click **More info**, then **Run anyway**. You only have to do this the first time.

## Using it

Double-click **`PhotoSorter.exe`**. The window has four tabs along the top: **Sort**, **Shortcuts**, **How to use** and **Notes** (the small print). Press **F1** to jump to the shortcuts at any time, and **Esc** to get back to sorting. On the **Sort** tab:

1. **Browse** to the top folder of your photos. Every folder inside it is searched, however deeply nested.
2. Choose where the sorted folders should go. It suggests `<your folder> - Sorted`.
3. **Move** (the default) or **Copy**.
4. Pick how to sort, then click **Start**.

### Keep / Delete

| Key | Does |
|---|---|
| `N` or `←` | **No**: send to `Delete` |
| `Y` or `→` | **Yes**: choose a folder for it (see below) |
| `1`–`9` | Skip the question and send it straight to that `Keep` folder |
| `P` | Play a video (or a Live Photo's clip) |
| `Space` | Skip for now (it comes back next time) |
| `Backspace` | Undo the last one |
| `R` | Rename it: type a name, then `Enter` (`Esc` undoes) |
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

### Renaming as you sort

The **Save as** box at the top of the details panel shows the name each sorted file will get. Press **R** (or click it), type a new name, and press **Enter**. Then sort as normal. Any RAW, `.xmp` or Live Photo clip that goes with the photo gets the same new name. (With **Copy**, your original keeps its name.)

On the first screen you can also choose to name every sorted file **by date taken**, e.g. `2017-01-26 14.30.12.jpg`. Photos with no date keep their own name, and two taken in the same second become `… (1).jpg`.

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

- **Photos:** JPG, PNG, HEIC (iPhone), WEBP, AVIF, GIF, BMP, TIFF, PSD.
  **Camera RAW:** CR2, CR3, NEF, ARW, DNG, ORF, RAF, RW2, PEF, SRW and more. A **RAW+JPEG pair** (same name) counts as one photo, and both files go together.
  **Edits files:** `.xmp` (Bridge / Lightroom) and `.aae` (iPhone) go along with their photo.
  **Videos:** MP4, MOV, M4V, AVI, MKV, WMV, 3GP, MTS/M2TS, WEBM, MPG.
- **Nothing is skipped without telling you.** Before sorting starts, a *Here's what I found* screen shows how many photos, RAW files and videos there are, plus every file type that **isn't** included (PDFs, music…). The full list is saved as `Skipped files.csv` in the sorted folder.
- **The `Delete` folder is for you to delete yourself.** The app never deletes anything. `Delete` just holds everything you said No to, so you can check it before throwing it away.
- **Move vs Copy:** Move (the default) needs no extra disk space when the sorted folder is on the same drive. Copy leaves your folder untouched but needs free space roughly equal to what you're sorting. With Copy, once you're happy you can delete the original folder yourself.
- Files with the same name from different folders don't overwrite each other: the second becomes `IMG_0001 (1).jpg`.
- **How it remembers where you got to:** the sorted folder has a file called `.photo_sorter_log.jsonl` (don't delete it). It's a running record with one line per decision: which original file, which folder it went to, and where it was saved (plus a line when you press Undo). When you reopen a folder, anything already in that record is skipped. With Move, sorted photos have already left your folder, so only the unsorted ones come up.
- Sorted a folder with an older version? Opening it again tidies your earlier folders into `Photos\` automatically, and adds any Live Photo clips that were missed.
- Folders whose names start with a dot (like `.thumbnails`) are skipped.

---

## 📝 Notes & caveats

The small print. It's also on the **Notes** tab in the app.

**Space and safety**
- **Move** (the default) takes each photo out of your folder and into the sorted folder, so what's left behind is what you haven't sorted yet, plus anything skipped. Folders it empties stay until you click **Remove empty folders** (on the summary screen, or when you open the folder again).
- **Remove empty folders** only takes folders with nothing in them (at most a `Thumbs.db`, `.DS_Store` or `desktop.ini` thumbnail file). It always asks first, checks each folder again just before removing it, and never touches your top folder, the sorted folder or hidden folders. Undo puts a folder back if it needs to.
- The app never deletes anything. The `Delete` folder is just a folder: emptying it is up to you. Undo moves the photo back where it came from.
- Moving to the same drive is instant and needs no extra space. Moving to another drive copies the photo, checks the copy, then removes the original, so it's slower.
- If a photo can't be moved (for example, it's open in another program), you get an error and the photo and its RAW / clip all stay where they were. Nothing is left half-moved.
- **Copy** leaves your folder untouched, but needs free space roughly equal to what you're sorting. There's no space check up front. If the disk fills up you get an error, and that photo stays where it was.
- **OneDrive / cloud folders:** "online only" files are downloaded as you view them, so a big sort can be slow and use a lot of data. Moving photos out of OneDrive also takes them out of OneDrive on your other devices.
- Want a backup before sorting? Copy the whole folder somewhere first, or choose **Copy**.
- Don't run two copies of the app on the same folder at the same time.

**Progress and undo**
- Progress lives in `.photo_sorter_log.jsonl` in the sorted folder. Delete it and the app forgets what you've done.
- With **Copy**, originals are recognised by where they are. Move or rename the original folder (or a file in it) and those photos come up again.
- **Undo** only goes back through what you've done since opening the folder this time. To fix something from an earlier sitting, move the file yourself.
- Sorts started before version 2.2 were copies, so **Continue** keeps them on Copy unless you change it.
- **Skip** (Space) only skips for now. Skipped photos come back next time.
- Moved the sorted folder? **Pick up where you left off** still points at the old place. Use **Open a progress file…** and pick the one in its new place instead.

**Pairs, Live Photos and edits**
- RAW+JPEG pairs and Live Photos are only matched when both files are **in the same folder with the same name** (`IMG_0042.JPG` + `IMG_0042.CR2`). If your camera saved them to separate folders, they come up as two items.
- Android motion photos keep their clip inside the photo. The photo is kept whole, but **P** can't play the clip.
- Previews show the photo as shot. Edits saved in `.xmp` (Lightroom / Bridge) or `.aae` (iPhone) go along with it but don't show in the preview.
- RAW previews use the JPEG the camera stores inside the RAW, so they look like the camera's screen, not a full edit.
- Duplicate photos (the same picture in two folders) aren't detected. Each one comes up.

**Videos**
- Videos show one still frame. **P** plays them in your normal video player. If Windows can't play that type, you'll need a player like VLC.
- A few unusual video types may show no preview. They can still be sorted.

**Folders and names**
- Keys `1`–`9` only reach your first 9 `Keep` folders (A–Z). Any more are click-only.
- **Straight into my own folders** mode allows up to 9 folders.
- Photos and videos share folder names, so making `Holiday` for a video also offers it for photos.
- Renaming only changes the sorted file's name. The date, camera details and other info inside the file are untouched.
- Typed names lose characters Windows doesn't allow (`\ / : * ? " < > |`) and are cut to 180 characters. The same name twice becomes `(1)`.
- **By date taken** uses the camera's clock with no time-zone change. If the camera's clock was wrong, the names will be too. Photos with no date keep their original name.
- Folders starting with a dot and system files (`Thumbs.db`, `desktop.ini`) are skipped. Every other skipped file is listed in `Skipped files.csv`.

**The .exe**
- Windows only. There's no Mac version yet.
- It takes a few seconds to open because everything it needs is packed inside the one file.
- Windows SmartScreen, or sometimes an antivirus, may warn about it because it isn't from a big company. Click **More info**, then **Run anyway**.
- Settings and recent sorts are saved in `.photo_sorter_settings.json` in your user folder.

---

<details>
<summary>For tinkerers: run from the source code or build the .exe yourself</summary>

1. Install Python from [python.org/downloads](https://www.python.org/downloads/), ticking **"Add python.exe to PATH"**.
2. Download this repo (**Code → Download ZIP**) and unzip it.
3. Run `Install.bat` once, then `Photo Sorter.bat` to start it.
4. To build `PhotoSorter.exe` yourself, run `Build exe.bat`. The file appears in the `dist` folder.

</details>
