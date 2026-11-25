"""Turn uploaded reader files into the dashboard's data.

  python3 -m stats.pipeline ingest inbox/*.zip   read uploads, save a snapshot, extend per-book daily history
  python3 -m stats.pipeline build                write site/data.json

An upload is a zip holding global_stats.bin, daily_minutes.bin and, per book, either
  epub_<id>.stats + epub_<id>.book          (flat, as the iPhone Shortcut saves them) or
  .../epub_<id>/stats_v5.bin + book.bin     (a copy of the card's .crosspoint folder).
The reader keeps only running totals per book, so time per book per day comes from comparing
each upload with the previous one.
"""
import json, os, re, sys, urllib.parse, urllib.request, zipfile
from datetime import date, datetime, timedelta, timezone

from stats import decode

TZ = timezone(timedelta(hours=-7))  # Arizona, no DST; change if you move
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.environ.get("STATS_DATA", os.path.join(ROOT, "data"))
SITE = os.environ.get("STATS_SITE", os.path.join(ROOT, "site"))


def path(*p):
    return os.path.join(DATA, *p)


def load(name, default):
    try:
        with open(path(name)) as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def save(name, obj):
    os.makedirs(os.path.dirname(path(name)), exist_ok=True)
    with open(path(name), "w") as f:
        json.dump(obj, f, indent=1, sort_keys=True, ensure_ascii=False)


def key(title):
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def taken_at(zip_path):
    m = re.search(r"(\d{4}-\d{2}-\d{2})[T _](\d{2})[-:.](\d{2})", os.path.basename(zip_path))
    if m:
        return datetime.fromisoformat(f"{m[1]}T{m[2]}:{m[3]}").replace(tzinfo=TZ)
    return datetime.fromtimestamp(os.path.getmtime(zip_path), TZ)


def read_zip(zip_path):
    """-> (global dict, {day: seconds}, {book id: (stats bytes, book.bin bytes or None)})"""
    g = daily = None
    stats, meta = {}, {}
    with zipfile.ZipFile(zip_path) as z:
        for name in z.namelist():
            base = os.path.basename(name)
            if not base or base.startswith("._") or "__MACOSX" in name:
                continue
            data = z.read(name)
            folder = os.path.basename(os.path.dirname(name))
            m = re.fullmatch(r"(epub_\d+)\.(stats|book)(\.bin)?", base)  # iOS may append .bin
            bid, kind = (m[1], m[2]) if m else (folder, {"stats_v5.bin": "stats", "book.bin": "book"}.get(base))
            try:
                if re.fullmatch(r"global_stats(\.bin)+", base):
                    g = decode.global_stats(data)
                elif re.fullmatch(r"daily_minutes(\.bin)+", base):
                    daily = decode.daily_minutes(data)
                elif kind == "stats" and bid.startswith("epub_"):
                    stats[bid] = decode.book_stats(data)
                elif kind == "book" and bid.startswith("epub_"):
                    meta[bid] = decode.book_meta(data)
            except ValueError:
                pass  # a 404 page or an older cache format; the name list covers missing titles
    if g is None or daily is None:
        raise SystemExit(f"{zip_path}: missing global_stats.bin or daily_minutes.bin")
    return g, daily, {bid: (s, meta.get(bid)) for bid, s in stats.items()}


def ingest(zip_paths):
    names = load("book_names.json", {})  # epub_<id> -> [title, author], for caches without a readable book.bin
    history = load("history.json", {})  # book key -> {day: seconds}
    days = load("days.json", {})  # day -> seconds, kept beyond the reader's 371-day window
    for zp in sorted(zip_paths, key=taken_at):
        when = taken_at(zp)
        g, daily, raw = read_zip(zp)
        books = {}
        for bid, (s, meta) in raw.items():
            if not s["seconds"]:
                continue
            known = meta or names.get(bid)
            if not known and s["seconds"] < 600:
                continue  # opened for a moment: the reader saved no title, and it isn't worth a row
            title, author = known or (f"Unknown book ({bid})", "")
            title = re.sub(r"\s*(\([^)]*\)|:\s.*)$", "", title)  # drop subtitles: "The Hunger Games: The First Book…"
            names.setdefault(bid, [title, author])
            k = key(title)
            if k in books:  # same book under two cache folders (it was moved): keep the bigger record
                if books[k]["seconds"] >= s["seconds"]:
                    continue
            books[k] = dict(s, title=title, author=author, id=bid)

        prev = load("latest.json", None)
        prev_books = prev["books"] if prev else {}
        deltas = {}
        for k, b in books.items():
            p = prev_books.get(k)
            if not p:
                deltas[k] = b["seconds"] if prev else 0
                continue
            base = p.get("base", {})  # totals carried over from stats files the reader has since replaced
            p_raw = p["seconds"] - base.get("seconds", 0)
            if b["seconds"] < p_raw:  # the reader started a fresh stats file (book moved or re-added)
                base = {f: p[f] for f in ("seconds", "sessions", "pages")}
                deltas[k] = b["seconds"]
            else:
                deltas[k] = b["seconds"] - p_raw
            if base:
                for f in base:
                    b[f] += base[f]
                b["base"] = base
                b["started"] = min(filter(None, (b["started"], p.get("started"))), default=None)
                b["finished"] = b["finished"] or p["finished"]
                b["finished_on"] = b["finished_on"] or p.get("finished_on")
        for k, p in prev_books.items():
            books.setdefault(k, p)  # its stats file is gone from the reader; keep the last known totals
        if prev:
            prev_day = date.fromisoformat(prev["taken_at"][:10])
            span = [(prev_day + timedelta(n)).isoformat() for n in range(1, (when.date() - prev_day).days + 1)]
            span = span or [when.date().isoformat()]  # two uploads on the same day
            weights = [daily.get(d, 0) for d in span]
            for k, delta in deltas.items():
                if delta <= 0:
                    continue
                # Spread across the days since the last upload, in proportion to total reading on each day.
                total = sum(weights) or 1
                share = weights if sum(weights) else [0] * (len(span) - 1) + [1]
                h = history.setdefault(k, {})
                for d, w in zip(span, share):
                    if w:
                        h[d] = h.get(d, 0) + round(delta * w / total)
        days.update(daily)
        snap = dict(taken_at=when.isoformat(), global_stats=g, books=books)
        save(f"snapshots/{when.strftime('%Y-%m-%dT%H-%M')}.json", snap)
        save("latest.json", snap)
        print(f"{os.path.basename(zp)}: {len(books)} books, {g['seconds'] / 3600:.1f} h total")
    save("history.json", history)
    save("days.json", dict(sorted(days.items())))
    save("book_names.json", names)


def open_library(params):
    url = "https://openlibrary.org/search.json?" + urllib.parse.urlencode({**params, "fields": "cover_i", "limit": 5})
    req = urllib.request.Request(url, headers={"User-Agent": "reading-stats (github.com/synamalhan/reading-stats)"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r).get("docs", [])


def cover_id(title, author, search=open_library):
    """Open Library cover id: title + author first, then title alone (the EPUB's author can be misspelled)."""
    if "," in author:  # "Jewell, Lisa" -> "Lisa Jewell"
        author = " ".join(p.strip() for p in reversed(author.split(",", 1)))
    for params in ([{"title": title, "author": author}] if author else []) + [{"title": title}]:
        for doc in search(params):
            if doc.get("cover_i"):
                return doc["cover_i"]
    return None


def build():
    snap = load("latest.json", None)
    if not snap:
        raise SystemExit("nothing ingested yet")
    history = load("history.json", {})
    covers = load("covers.json", {})  # book key -> Open Library cover id, or null when it has none
    for k, b in snap["books"].items():
        if k not in covers:
            try:
                covers[k] = cover_id(b["title"], b["author"])
            except (OSError, ValueError) as e:  # offline or a bad reply: leave uncached, try next build
                print(f"cover lookup failed for {b['title']}: {e}")
    save("covers.json", covers)
    dnf = {key(t) for t in load("dnf.json", [])}  # titles you gave up on, edited by hand
    out = dict(taken_at=snap["taken_at"], global_stats=snap["global_stats"], days=load("days.json", {}),
               books=sorted(({**b, "key": k, "history": history.get(k, {}), "cover": covers.get(k), "dnf": k in dnf}
                             for k, b in snap["books"].items()), key=lambda b: -b["seconds"]))
    os.makedirs(SITE, exist_ok=True)
    with open(os.path.join(SITE, "data.json"), "w") as f:
        json.dump(out, f, ensure_ascii=False)
    print(f"site/data.json: {len(out['books'])} books, {len(out['days'])} days")


if __name__ == "__main__":
    cmd, *args = sys.argv[1:] or ["build"]
    ingest(args) if cmd == "ingest" else build()
