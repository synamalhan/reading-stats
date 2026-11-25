# Reading Stats

A per-book reading dashboard for an Xteink running CrossInk-Bookorbit.
The iPhone pulls the stats files off the reader over Wi-Fi and uploads them here.
A GitHub Action decodes them, extends the day-by-day history and publishes the site.

```
reader (File Transfer on) ──Wi-Fi──▶ iPhone Shortcut ──zip──▶ inbox/ ──Action──▶ data/ + GitHub Pages
```

## Layout

| Path | What it is |
|---|---|
| `stats/decode.py` | Decoders for `global_stats.bin`, `daily_minutes.bin`, `stats_v5.bin`, `book.bin` |
| `stats/pipeline.py` | `ingest` uploads into snapshots + history, `build` writes `site/data.json` |
| `site/index.html` | The dashboard (overview + a page per book), no build step |
| `data/` | Kept history: `history.json` (book → day → seconds), `days.json`, `snapshots/`, `book_names.json` |
| `inbox/` | Where uploads land; the Action deletes them after ingesting |
| `tests/` | `python3 -m unittest discover tests` |

The reader stores only running totals per book. Per-book daily time comes from comparing each
upload with the last one; when several days pass between uploads, the difference is spread across
those days in proportion to the reader's daily totals. Upload daily for exact days.

## One-time setup

1. **Create the repo.** On GitHub, make a new repository named `reading-stats` and upload these files
   (or `git init`, commit and push).
2. **Turn on Pages.** Repo → **Settings → Pages → Source: GitHub Actions**.
3. **Make a token for the Shortcut.** GitHub → **Settings → Developer settings → Fine-grained tokens →
   Generate new token**. Repository access: *Only select repositories* → `reading-stats`.
   Permissions: **Contents: Read and write**. Copy the token (starts with `github_pat_`).
4. **Reader.** Settings → System → **Show Hidden Files: On** (lets the web server send `.crosspoint` files).
5. **Build the Shortcut** below, then run it once. The site appears at
   `https://<your-username>.github.io/reading-stats/`.

Privacy: a GitHub Pages site is public to anyone with the link, even from a private repo.
For a login in front of it, host `site/` on Cloudflare Pages with Cloudflare Access instead.

## The iPhone Shortcut

Shortcuts app → **+** → name it **Sync Reader**. Add these actions in order
(search for each by the bold name):

1. **Text**: `http://crosspoint.local` → then **Set Variable** `Reader` to it.
2. **Get Contents of URL**: `Reader` + `/api/files?path=/.crosspoint` (method GET).
3. **Repeat with Each** item in *Contents of URL*:
   1. **Get Dictionary Value** `name` from *Repeat Item* → **Set Variable** `Folder`.
   2. **If** `Folder` **begins with** `epub_`:
      1. **Get Contents of URL**: `Reader` + `/download?path=/.crosspoint/` + `Folder` + `/stats_v5.bin`
      2. **Set Name** of *Contents of URL* to `Folder` + `.stats` → **Add to Variable** `Files`.
      3. **Get Contents of URL**: `Reader` + `/download?path=/.crosspoint/` + `Folder` + `/book.bin`
      4. **Set Name** of *Contents of URL* to `Folder` + `.book` → **Add to Variable** `Files`.
   3. **End If**
4. **End Repeat**
5. **Get Contents of URL**: `Reader` + `/download?path=/.crosspoint/global_stats.bin`
   → **Set Name** `global_stats.bin` → **Add to Variable** `Files`.
6. **Get Contents of URL**: `Reader` + `/download?path=/.crosspoint/daily_minutes.bin`
   → **Set Name** `daily_minutes.bin` → **Add to Variable** `Files`.
7. **Format Date**: *Current Date*, Date Format **Custom**: `yyyy-MM-dd'T'HH-mm` → **Set Variable** `Stamp`.
8. **Make Archive**: ZIP from `Files`, name `Stamp`.
9. **Base64 Encode** *Archive* (Line Breaks: **None**).
10. **Get Contents of URL**:
    `https://api.github.com/repos/<your-username>/reading-stats/contents/inbox/` + `Stamp` + `.zip`
    - Method: **PUT**
    - Headers: `Authorization` = `Bearer <your token>`, `Accept` = `application/vnd.github+json`
    - Request Body: **JSON** — `message` (Text) = `Reader upload`, `content` (Text) = *Base64 Encoded*
11. **Show Notification**: `Stats uploaded`.

**To sync:** open **File Transfer → Join Network** on the reader, then run *Sync Reader*
(from the Shortcuts app, a Home Screen icon, or "Hey Siri, Sync Reader"). The site updates about
a minute later; progress is under the repo's **Actions** tab.

If `crosspoint.local` doesn't resolve, use the IP address the reader shows on the File Transfer screen.

## From a Mac instead

Copy the card's `.crosspoint` folder, zip it as `YYYY-MM-DDTHH-MM.zip`, and drop it into `inbox/`
(GitHub web upload works). The pipeline reads both the Shortcut's flat files and a folder copy.

## Moving

Day boundaries use Arizona time (UTC−7). Change `TZ` in `stats/pipeline.py` if that changes.
