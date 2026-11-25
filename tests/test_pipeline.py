"""Two uploads two days apart: the second adds 40 min to one book; check it lands on the right days.
run: python3 -m unittest discover tests"""
import json, os, struct, tempfile, unittest, zipfile
from datetime import date


def global_bin():
    return struct.pack("<B4I4I7II", 3, 10, 3600, 50, 1, *[0] * 11, 9000) + bytes(92) + struct.pack("<H", 3)


def daily_bin(last, per_day):  # per_day: {day index since 2000: seconds}
    slots = [0] * 371
    for d, s in per_day.items():
        slots[d % 371] = s // 10
    return b"BODM\x01\x00\x00\x00" + struct.pack("<I4I", last, 0, 0, 0, 0) + struct.pack("<371H", *slots) + bytes(742)


def stats_bin(seconds):
    return struct.pack("<BHIIBHHB", 5, 2, seconds, 10, 0, 0, 0, 0) + bytes(8) + struct.pack("<4I7II", *[0] * 12)


def book_bin(title, author):
    s = lambda t: struct.pack("<I", len(t.encode())) + t.encode()
    return struct.pack("<IBIHH", 0x425843FF, 10, 0, 0, 0) + s(title) + s(author) + s("en") + s("") + s("")


def day(iso):
    return (date.fromisoformat(iso) - date(2000, 1, 1)).days


class TwoUploads(unittest.TestCase):
    def test_delta_spread_by_daily_reading(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["STATS_DATA"] = os.path.join(tmp, "data")
            os.environ["STATS_SITE"] = os.path.join(tmp, "site")
            import importlib, stats.pipeline as p
            importlib.reload(p)

            def upload(name, seconds, daily):
                zp = os.path.join(tmp, name)
                with zipfile.ZipFile(zp, "w") as z:
                    z.writestr("global_stats.bin", global_bin())
                    z.writestr("daily_minutes.bin", daily_bin(max(daily), daily))
                    z.writestr("epub_1.stats.bin", stats_bin(seconds))  # as iOS may rename it
                    z.writestr("epub_1.book", book_bin("Circe", "Madeline Miller"))
                    z.writestr("epub_2.stats", b"404 Not Found")  # must be skipped, not crash
                return zp

            first = upload("2026-11-24T21-00.zip", 600, {day("2026-11-24"): 600})
            # 40 more minutes: 10 on Nov 25, 30 on Nov 26 (from the reader's daily totals).
            second = upload("2026-11-26T22-00.zip", 3000, {day("2026-11-24"): 600, day("2026-11-25"): 600,
                                                           day("2026-11-26"): 1800})
            p.ingest([second, first])  # order on disk must not matter
            p.build()
            h = json.load(open(os.path.join(tmp, "data", "history.json")))["circe"]
            self.assertEqual(h, {"2026-11-25": 600, "2026-11-26": 1800})
            self.assertTrue(os.path.exists(os.path.join(tmp, "site", "data.json")))



class Covers(unittest.TestCase):
    def test_reorders_author_and_falls_back_to_title(self):
        from stats.pipeline import cover_id
        seen = []

        def search(params):
            seen.append(params)
            return [{"cover_i": 42}] if "author" not in params else [{"title": "no cover here"}]

        self.assertEqual(cover_id("None of This is True", "Jewell, Lisa", search), 42)
        self.assertEqual(seen, [{"title": "None of This is True", "author": "Lisa Jewell"}, {"title": "None of This is True"}])
        self.assertIsNone(cover_id("Nothing", "", lambda p: []))

class MovedBooks(unittest.TestCase):
    def test_moved_book_keeps_old_time_and_missing_book_stays(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["STATS_DATA"] = os.path.join(tmp, "data")
            os.environ["STATS_SITE"] = os.path.join(tmp, "site")
            import importlib, stats.pipeline as p
            importlib.reload(p)

            def upload(name, books, daily):
                zp = os.path.join(tmp, name)
                with zipfile.ZipFile(zp, "w") as z:
                    z.writestr("global_stats.bin", global_bin())
                    z.writestr("daily_minutes.bin", daily_bin(max(daily), daily))
                    for bid, (title, seconds) in books.items():
                        z.writestr(f"{bid}.stats", stats_bin(seconds))
                        z.writestr(f"{bid}.book", book_bin(title, "A"))
                return zp

            p.ingest([upload("2026-11-24T21-00.zip", {"epub_1": ("Circe", 3000), "epub_2": ("Delilah", 600)},
                             {day("2026-11-24"): 3600})])
            # Circe moved folders: a new stats file with 5 min; Delilah's stats file is gone.
            p.ingest([upload("2026-11-25T21-00.zip", {"epub_9": ("Circe", 300)}, {day("2026-11-25"): 300})])
            books = json.load(open(os.path.join(tmp, "data", "latest.json")))["books"]
            self.assertEqual(books["circe"]["seconds"], 3300)
            self.assertEqual(books["delilah"]["seconds"], 600)
            self.assertEqual(json.load(open(os.path.join(tmp, "data", "history.json")))["circe"], {"2026-11-25": 300})

if __name__ == "__main__":
    unittest.main()
