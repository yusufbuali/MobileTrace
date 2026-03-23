# Test Evidence Guide

Public forensic images you can use to test MobileTrace end-to-end, plus tips to avoid duplicating large files on your machine.

---

## Avoid Copying Files — Use Path Import

Forensic images are large (2 GB – 40 GB). MobileTrace has three evidence import modes and only one of them copies the file:

| Mode | How to access | Copies the archive? |
|---|---|---|
| **File upload** (drag-and-drop / browse) | Evidence tab → File Upload panel | ✅ Yes — uploads to the Docker volume |
| **Path import** | Evidence tab → Path Import panel | ❌ No — reads in-place |
| **Folder scan** | Evidence tab → Folder Scan panel | ❌ No — reads in-place |

**Recommended workflow for large files:**

1. Download the evidence archive to the `evidence/` folder in the project root.
2. The `docker-compose.yml` already mounts this folder read-only into the container:
   ```yaml
   - ./evidence:/opt/mobiletrace/evidence:ro
   ```
3. In the app, open a case → Evidence tab → **Path Import**.
4. Enter the container path: `/opt/mobiletrace/evidence/<filename>`.
5. Click **Import** — MobileTrace reads the archive from disk and extracts only the SQLite databases (a few MB) into the case directory. The original archive is never duplicated.

> **Note:** If you store evidence on an external drive or a different folder on your machine, add it as an additional read-only volume in `docker-compose.yml`:
> ```yaml
> - /path/to/your/evidence:/opt/mobiletrace/evidence:ro
> ```
> Then restart the container: `docker-compose up -d`.

---

## Recommended Test Images

### Quick start — smallest files first

#### BelkaCTF Day US 2023 (Android 9) — 618 MB
The smallest useful image. Good for a first run.

| Field | Value |
|---|---|
| OS | Android 9 |
| Size | 618 MB |
| Format | `.7z` |
| Password | `CwMglC7pLRHSkIlwoSqA` |
| MD5 | `FB77E0BCC993EB11D125213D81E63616` |
| Download | https://dl.spbctf.com/BelkaDayUS_CTF_IMAGE.7z |

```bash
# Download to evidence/
curl -L -o evidence/BelkaDayUS_CTF_IMAGE.7z https://dl.spbctf.com/BelkaDayUS_CTF_IMAGE.7z

# Verify MD5
md5sum evidence/BelkaDayUS_CTF_IMAGE.7z
# Expected: fb77e0bcc993eb11d125213d81e63616

# Extract with password (7zip required)
7z x evidence/BelkaDayUS_CTF_IMAGE.7z -p"CwMglC7pLRHSkIlwoSqA" -o"evidence/"
```

Then in MobileTrace: Evidence tab → Path Import → `/opt/mobiletrace/evidence/<extracted-filename>`

---

#### BelkaCTF 6 — iPhone (iOS 16.3) — 2.03 GB
A realistic iOS image with iMessage, contacts, and call history.

| Field | Value |
|---|---|
| OS | iOS 16.3 |
| Size | 2.03 GB |
| Format | `.zip` |
| Password | `0zj6EV6NYq0LVkyiU8s8` |
| MD5 | `874C9A9D0D274B9BA5245116AA6F2A67` |
| Download | https://dl.ctf.do/BelkaCTF_6_CASE240405_D201AP.zip |

```bash
curl -L -o evidence/BelkaCTF_6_CASE240405_D201AP.zip https://dl.ctf.do/BelkaCTF_6_CASE240405_D201AP.zip
md5sum evidence/BelkaCTF_6_CASE240405_D201AP.zip
# Expected: 874c9a9d0d274b9ba5245116aa6f2a67
```

---

### Full reference images — Josh Hickman (no password, free)

Josh Hickman publishes clean, well-documented Android and iOS images for the forensics community. Hosted at [digitalcorpora.org](https://digitalcorpora.org). No password, no registration required.

These are larger but contain a realistic breadth of apps and data.

| Image | OS | Size | MD5 | Download |
|---|---|---|---|---|
| Android 9 | Android 9 | 4.2 GB | `B5D663829FD61A4B05690C50130F3EB2` | https://downloads.digitalcorpora.org/corpora/mobile/android_9.tar.gz |
| Android 8 | Android 8 | 5.4 GB | `711C38792980FB8ADB3646BB8132BF29` | https://downloads.digitalcorpora.org/corpora/mobile/android_8.tar.gz |
| Android 11 | Android 11 | 10.2 GB | `9553729D10BC6CAE84916A506CB74D98` | https://downloads.digitalcorpora.org/corpora/mobile/android_11.zip |
| Android 13 | Android 13 | 18.5 GB | `74B97F0AFE6CC0A79E81C39F3D01F4EF` | https://digitalcorpora.org/corpora/cell-phones/android-13-image/ |
| Android 14 | Android 14 | 17.1 GB | `2F9578715A315C0897E51EF9C1007F2D` | https://digitalcorpora.s3.amazonaws.com/s3_browser.html#corpora/mobile/android_14/ |
| iOS 15 | iOS 15.3.1 | 15.5 GB | `B1EC40D5CD835621326B821D6FA12FF5` | https://downloads.digitalcorpora.org/corpora/mobile/iOS_15_Public_Image.tar.gz |
| iOS 16 | iOS 16.1.2 | 18.7 GB | `2DE01264A2D25C132FFC51BAC06B8BCF` | https://digitalcorpora.s3.amazonaws.com/s3_browser.html#corpora/mobile/iOS16/ |
| iOS 17 | iOS 17.3 | 20.6 GB | `E115F051D15178FA1334489E24C9F0FD` | https://digitalcorpora.s3.amazonaws.com/s3_browser.html#corpora/mobile/iOS17/ |

Download tip for large files:
```bash
# Resume-safe download with progress
curl -L -C - --progress-bar -o evidence/android_9.tar.gz \
  https://downloads.digitalcorpora.org/corpora/mobile/android_9.tar.gz
```

---

## More images

Browse the full catalogue of 140+ forensic images (mobile, desktop, memory, network) at **[The Evidence Locker](https://theevidencelocker.github.io/)**.

Filter by OS → **Android** or **iOS**, then sort by size to find images that fit your storage.

---

## Step-by-step: import a test image end-to-end

1. **Download** the evidence file (and extract if it's `.7z` or `.zip` with a password).
2. **Place** the extracted archive inside the `evidence/` folder in the project root — or in any folder you've added as a Docker volume mount.
3. **Create a case** in MobileTrace — click `+ New Case`, enter a title.
4. **Import evidence** — open the case, go to the Evidence tab, choose **Path Import**.
5. **Enter the container path**: `/opt/mobiletrace/evidence/<your-filename>` and click Import.
6. **Wait for parsing** — a progress indicator appears; parsing a 2–4 GB image typically takes 30–90 seconds.
7. **Run analysis** — once parsing completes, go to the Analysis tab, select the artifacts to analyse, and click Run.
8. **View results** — check the Overview, Conversations, and Timeline tabs. Generate a report from the case header.

### Common issues

| Problem | Fix |
|---|---|
| "path not in allowed evidence directories" | The file is not inside an allowed mount path. Add the folder as a volume in `docker-compose.yml` and restart. |
| Parsing stuck at "pending" | The archive format may not be supported directly. Extract to a `.tar` first, then import that. |
| 7z extraction fails | Confirm you have `7zip` installed (`brew install p7zip` / `apt install p7zip-full`) and the password is correct. |
| Very slow parsing | Large archives on a slow disk. Use Path Import (not file upload) so Docker's volume layer isn't involved in reading the source. |
