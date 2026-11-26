# Photo Sorter

Quickly sort thousands of photos one at a time with a click or a key. No Bridge, no faff.

- **No** sends a photo to `Delete`.
- **Yes** asks which folder inside `Keep` it belongs in (Friends, Holiday, Cats…). You can make a new folder on the spot.

A side panel shows each photo's details: date taken, camera, lens, settings, size and location.

Photos are **copied**, never moved or deleted, so your originals are always safe.
Close it whenever you like. Next time you open the same folder, it picks up where you left off.

---

## ⬇️ Download (Windows)

### **[Download PhotoSorter.exe](https://github.com/Elliot95/photo-sorter/releases/latest/download/PhotoSorter.exe)**

That's it: no installing. Put the file wherever you like (Desktop, Documents…) and double-click it.

> **"Windows protected your PC"?** This shows up for any app that isn't from a big company.
> Click **More info**, then **Run anyway**. You only have to do this the first time.

## Using it

Double-click **`PhotoSorter.exe`**. In the window that opens:

1. **Browse** to the folder of photos you want to sort. Subfolders are included.
2. Choose where the sorted folders should go. It suggests `<your folder> - Sorted`.
3. Pick how to sort, then click **Start**.

### Keep / Delete

| Key | Does |
|---|---|
| `N` or `←` | **No**: copy to `Delete` |
| `Y` or `→` | **Yes**: choose a folder for it (see below) |
| `1`–`9` | Skip the question and send it straight to that `Keep` folder |
| `Space` | Skip for now (it comes back next time) |
| `Backspace` | Undo the last one |
| `I` | Show or hide the photo details panel |
| `Esc` | Back to the menu |

**After Yes**, a row of folder buttons appears:

| Key | Does |
|---|---|
| `Enter` | Just `Keep` (no subfolder) |
| `1`–`9` | That folder, e.g. `Keep\Holiday` |
| `F` | **New folder**: type a name, and the photo goes straight in it |
| `Esc` | Cancel, back to Yes / No |

The folders you make stay there, so they're ready for the next photo and the next time you open the app.

### Straight into your own folders

Want to skip Keep / Delete? Choose **Straight into my own folders** on the menu and type up to 9 names, one per line.
Press `1`–`9` (or click the buttons) to send each photo to that folder.

---|---|
| `Y` or `→` | **Yes**: copy to `Keep` |
| `N` or `←` | **No**: copy to `Delete` |
| `Space` | Skip for now (it comes back next time) |
| `Backspace` | Undo the last one |
| `I` | Show or hide the photo details panel |
| `Esc` | Back to the menu |

### Round 2: your own folders

Back at the menu, **Browse** to the `Keep` folder. Choose **Into my own folders** and type up to 9 names, one per line.
Press `1`–`9` (or click the buttons) to send each photo to that folder.

---

## Good to know

- Works with JPG, PNG, HEIC (iPhone), WEBP, GIF, BMP and TIFF. Videos are not shown.
- Because photos are copied, you need free disk space roughly equal to the photos you're sorting.
- When you're happy with the result, you can delete the `Delete` folder (and the originals) yourself.

---

<details>
<summary>For tinkerers: run from the source code or build the .exe yourself</summary>

1. Install Python from [python.org/downloads](https://www.python.org/downloads/), ticking **"Add python.exe to PATH"**.
2. Download this repo (**Code → Download ZIP**) and unzip it.
3. Run `Install.bat` once, then `Photo Sorter.bat` to start it.
4. To build `PhotoSorter.exe` yourself, run `Build exe.bat`. The file appears in the `dist` folder.

</details>
