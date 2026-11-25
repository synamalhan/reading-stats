"""Decoders for CrossInk-Bookorbit's reading-stats files (all little-endian).

global_stats.bin  v3, 159 bytes   overall totals, weekday/time-of-day split, 730-day read bitmap, longest streak
daily_minutes.bin 'BODM' v1       per-day reading time for the last 371 days, in 10-second units
stats_v5.bin      v5, 73 bytes    one book's totals (in .crosspoint/epub_<fnv1a64(path)>/)
book.bin          'CXB' v10       one book's metadata; only title and author are read here
"""
import struct
from datetime import date, timedelta

EPOCH = date(2000, 1, 1)  # Bookorbit counts days from here
TIME_OF_DAY = ("Morning", "Afternoon", "Evening", "Night")
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def fnv1a64(path):
    """Name of a book's cache folder: epub_<this>, from its SD-card path like '/Books/Circe.epub'."""
    h = 0xCBF29CE484222325
    for b in path.encode():
        h = ((h ^ b) * 0x100000001B3) & (2**64 - 1)
    return h


def _day(n):
    return (EPOCH + timedelta(days=n)).isoformat()


def global_stats(b):
    if len(b) != 159 or b[0] != 3:
        raise ValueError("not a v3 global_stats.bin")
    sessions, seconds, pages, finished = struct.unpack_from("<4I", b, 1)
    tod = struct.unpack_from("<4I", b, 17)
    dow = struct.unpack_from("<7I", b, 33)
    last, = struct.unpack_from("<I", b, 61)
    bits = b[65:157]
    streak, = struct.unpack_from("<H", b, 157)
    read_days = [_day(last - i) for i in range(730) if bits[i // 8] >> (i % 8) & 1] if last else []
    return dict(sessions=sessions, seconds=seconds, pages=pages, finished=finished,
                time_of_day=dict(zip(TIME_OF_DAY, tod)), weekday=dict(zip(WEEKDAYS, dow)),
                last_day=_day(last) if last else None, read_days=sorted(read_days), longest_streak=streak)


def daily_minutes(b):
    """{iso date: seconds} for days with reading."""
    days = 371
    if len(b) != 28 + 4 * days or b[:4] != b"BODM" or b[4] != 1:
        raise ValueError("not a v1 daily_minutes.bin")
    last, = struct.unpack_from("<I", b, 8)
    slots = struct.unpack_from(f"<{days}H", b, 28)
    out = {}
    for d in range(last - days + 1, last + 1):
        if d >= 0 and slots[d % days]:
            out[_day(d)] = slots[d % days] * 10
    return out


def book_stats(b):
    if len(b) != 73 or b[0] != 5:
        raise ValueError("not a v5 stats_v5.bin")
    sessions, seconds, pages, done = struct.unpack_from("<HIIB", b, 1)

    def ymd(off):
        y, m, d = struct.unpack_from("<HBB", b, off)
        return date(y, m, d).isoformat() if y else None

    tod = struct.unpack_from("<4I", b, 25)
    dow = struct.unpack_from("<7I", b, 41)
    left, = struct.unpack_from("<I", b, 69)
    return dict(sessions=sessions, seconds=seconds, pages=pages, finished=bool(done), started=ymd(17),
                finished_on=ymd(21) if done else None, time_of_day=dict(zip(TIME_OF_DAY, tod)),
                weekday=dict(zip(WEEKDAYS, dow)), seconds_left=left)


def book_meta(b):
    """(title, author) from book.bin: u32 magic, u8 version, u32 lut offset, u16 spine, u16 toc, then u32-length strings."""
    if len(b) < 21 or struct.unpack_from("<I", b, 0)[0] != 0x425843FF:
        raise ValueError("not a book.bin")
    off, out = 13, []
    for _ in range(2):
        n, = struct.unpack_from("<I", b, off)
        out.append(b[off + 4:off + 4 + n].decode("utf-8", "replace").strip())
        off += 4 + n
    return tuple(out)
