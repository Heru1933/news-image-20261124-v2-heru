#!/usr/bin/env python3
"""THE TUESDAY EDITION - a broadsheet of Tuesday 24 November 2026.

news-image-20261124, first account, v2 rebuild. Pure Python standard
library: a bitmap-font text renderer (MFNT files rasterized at build time
from DejaVu), a raw-RGB still blitter with area-average downscale, a small
canvas and a PNG encoder. No network, no clock, no randomness: two runs
write byte-identical entry.png.

Layout (1024x1024, cream paper, forest-green masthead, ink text):
  green masthead naming the day, dateline strip, one full-width hero
  (Nvidia, story #1) with its toon illustration, 7 illustrated features
  in a 4 + 3 grid (stories #3, #6, #28, #36, #37, #38, #39), the other
  32 stories as a numbered two-column list (headline + source), and a
  stats strip. All 40 stories are verified and dated/reported
  24 November 2026; every story prints its source beside it.
"""
import os
import struct
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
W, H = 1024, 1024
MARGIN = 20
CW = W - 2 * MARGIN

PAPER = (246, 241, 227)
CREAM = (250, 246, 236)
INK = (28, 38, 30)
GREEN = (29, 77, 43)
DGREEN = (18, 52, 29)
GOLD = (176, 138, 32)
RED = (160, 32, 46)
GREY = (96, 96, 84)
FAINT = (228, 221, 203)
WHITE = (255, 255, 255)


# ------------------------------------------------------------------ canvas
class Canvas:
    def __init__(self, w, h, bg):
        self.w = w
        self.h = h
        self.px = bytearray(bg * (w * h))

    def _off(self, x, y):
        return (y * self.w + x) * 3

    def box(self, x, y, w, h, color):
        x0 = max(0, x)
        y0 = max(0, y)
        x1 = min(self.w, x + w)
        y1 = min(self.h, y + h)
        if x1 <= x0 or y1 <= y0:
            return
        r, g, b = color
        row = bytes((r, g, b)) * (x1 - x0)
        for yy in range(y0, y1):
            o = self._off(x0, yy)
            self.px[o:o + len(row)] = row

    def rule(self, x, y, w, color, th=1):
        self.box(x, y, w, th, color)

    def border(self, x, y, w, h, color, th=2):
        self.box(x, y, w, th, color)
        self.box(x, y + h - th, w, th, color)
        self.box(x, y, th, h, color)
        self.box(x + w - th, y, th, h, color)

    def blit_cover(self, raw, sw, sh, x, y, w, h):
        """Draw raw RGB (sw x sh) into rect, scaling to cover + centre crop,
        with a small area average so downscales stay smooth."""
        scale = max(w / sw, h / sh)
        vw = w / scale
        vh = h / scale
        sx0 = (sw - vw) / 2.0
        sy0 = (sh - vh) / 2.0
        for dy in range(h):
            sy_a = sy0 + dy / scale
            sy_b = sy0 + (dy + 1) / scale
            ya = int(sy_a)
            yb = min(sh, int(sy_b) + (1 if sy_b > int(sy_b) else 0))
            if yb <= ya:
                yb = ya + 1
            for dx in range(w):
                sx_a = sx0 + dx / scale
                sx_b = sx0 + (dx + 1) / scale
                xa = int(sx_a)
                xb = min(sw, int(sx_b) + (1 if sx_b > int(sx_b) else 0))
                if xb <= xa:
                    xb = xa + 1
                r = g = b = n = 0
                for yy in range(ya, yb):
                    base = yy * sw * 3
                    for xx in range(xa, xb):
                        o = base + xx * 3
                        r += raw[o]
                        g += raw[o + 1]
                        b += raw[o + 2]
                        n += 1
                o = self._off(x + dx, y + dy)
                self.px[o] = r // n
                self.px[o + 1] = g // n
                self.px[o + 2] = b // n


# ------------------------------------------------------------------ fonts
# MFNT: magic, size u8, ascent u16, descent u16, count u16, then per
# glyph: codepoint u16, advance u16, top i16 (bbox top rel. to baseline),
# width u8, height u8, packed bits MSB-first row-major.
class Font:
    def __init__(self, path):
        with open(path, "rb") as fh:
            data = fh.read()
        assert data[:4] == b"MFNT"
        self.size = data[4]
        self.ascent, self.descent, count = struct.unpack(">HHH", data[5:11])
        self.line = self.ascent + self.descent
        self.glyphs = {}
        off = 11
        for _ in range(count):
            cp, adv, top, gw, gh = struct.unpack(">HHhBB", data[off:off + 8])
            off += 8
            nbytes = (gw * gh + 7) // 8
            self.glyphs[cp] = (adv, top, gw, gh, data[off:off + nbytes])
            off += nbytes
        self.fallback = self.glyphs[ord("?")]

    def glyph(self, ch):
        return self.glyphs.get(ord(ch), self.fallback)

    def width(self, s):
        return sum(self.glyph(c)[0] for c in s)

    def draw(self, img, x, baseline, s, color):
        cx = x
        for ch in s:
            adv, top, gw, gh, bits = self.glyph(ch)
            for yy in range(gh):
                base = yy * gw
                for xx in range(gw):
                    if (bits[(base + xx) // 8] >> (7 - (base + xx) % 8)) & 1:
                        px = cx + xx
                        py = baseline + top + yy
                        if 0 <= px < img.w and 0 <= py < img.h:
                            o = img._off(px, py)
                            img.px[o] = color[0]
                            img.px[o + 1] = color[1]
                            img.px[o + 2] = color[2]
            cx += adv
        return cx - x

    def centred(self, img, cx, baseline, s, color):
        self.draw(img, cx - self.width(s) // 2, baseline, s, color)

    def wrap(self, s, maxw):
        """Greedy word wrap; returns a list of lines."""
        out = []
        for chunk in s.split("\n"):
            words = chunk.split(" ")
            cur = ""
            for wd in words:
                trial = wd if not cur else cur + " " + wd
                if self.width(trial) <= maxw or not cur:
                    cur = trial
                else:
                    out.append(cur)
                    cur = wd
            if cur:
                out.append(cur)
        return out

    def shorten(self, s, maxw):
        if self.width(s) <= maxw:
            return s
        while s and self.width(s + "..") > maxw:
            s = s[:-1]
        return s + ".."


def load_fonts():
    d = os.path.join(HERE, "fonts")
    return {
        "mast": Font(os.path.join(d, "mast.bin")),
        "head": Font(os.path.join(d, "head.bin")),
        "head2": Font(os.path.join(d, "head2.bin")),
        "body": Font(os.path.join(d, "body.bin")),
        "list": Font(os.path.join(d, "list.bin")),
        "small": Font(os.path.join(d, "small.bin")),
        "smallb": Font(os.path.join(d, "smallb.bin")),
    }


def load_still(name):
    with open(os.path.join(HERE, "stills", name + ".rgb"), "rb") as fh:
        raw = fh.read()
    assert len(raw) == 600 * 450 * 3, name
    return raw


# ------------------------------------------------------------------ stories
# (number, kicker, headline, summary, source) for illustrated stories.
HERO = (1, "BUSINESS | MARKETS",
        "Nvidia reinstates chief Jensen Huang after affair with alleged spy",
        "The board brings Huang back; Trump claims "
        "'I made the deal' as Nvidia's value climbs almost $1tn and tech "
        "stocks rally.",
        "BBC / AP", "nvidia")

FEATURES = [
    (3, "WORLD", "COP31 ends with no deal as world splits",
     "BBC", "cop31"),
    (6, "WORLD", "India pledges $1.6bn to Nepal in reset of ties",
     "BBC", "nepal"),
    (28, "SPORT", "Alcaraz wins maiden ATP Finals title",
     "Times of India", "alcaraz"),
    (36, "SCIENCE", "Supermoon meets the 'Seven Sisters'",
     "CNET", "supermoon"),
    (37, "SCIENCE", "NHS launches world's largest AI breast-cancer trial",
     "BBC", "nhs"),
    (38, "CULTURE", "Melania Trump welcomes the White House Christmas tree",
     "BBC", "tree"),
    (39, "CULTURE", "Miley Cyrus marries Maxx Morando in California ceremony",
     "BBC", "miley"),
]

# (number, headline, source) for the other 32 stories.
REST = [
    (2, "Russian warship hit by Ukrainian drones in Libya", "BBC / AP"),
    (4, "Israeli attacks turn Gaza into 'toxic wasteland', Oxfam says", "BBC"),
    (5, "Iran flogs singer who performed without hijab, lawyers say", "BBC"),
    (7, "Zimbabwean preacher arrested on sexual assault allegations", "BBC"),
    (8, "UK to host 2035 Women's World Cup, FIFA confirms", "BBC"),
    (9, "Trump orders military not to detonate toxic explosives in Iowa", "BBC"),
    (10, "Democrats win largest House majority since 1992", "BBC / AP"),
    (11, "Search teams race to find survivors after Nigeria boat tragedy", "BBC"),
    (12, "Mexican soldiers attacked after drug lord's arrest", "BBC"),
    (13, "Flights cancelled in Belgium due to cost-of-living strike", "BBC"),
    (14, "Comedian mocks Trump's dance moves at Canada dinner", "BBC"),
    (15, "UN counts 25 seafarers killed around Strait of Hormuz", "Starlit Daily"),
    (16, "Russia warns Estonia of 'open war' over border closure", "Starlit Daily"),
    (17, "Tajikistan moves to leave the ICC", "Starlit Daily"),
    (18, "Danish top court upholds 'ghetto law' evictions", "Starlit Daily / BBC"),
    (19, "Indonesia factory fire kills 24, many missing", "Reuters / AP"),
    (20, "Russia launches 153 drones at Ukraine; 134 shot down", "AP"),
    (21, "Nvidia value climbs almost $1tn as tech stocks rally", "BBC"),
    (22, "US futures bounce while Asia braces for AI wipeout", "Reuters"),
    (23, "Congress leaves ahead of Dec. 11 deadline", "whileyouwereoutnews"),
    (24, "Sensex falls 1,484 points to 82,435; Nifty drops 451", "Reuters"),
    (25, "Indian firms plan ~$2.7bn bonds ahead of RBI policy", "Reuters"),
    (26, "Modi opens AI centre at IIT Patna, new research park", "Times of India"),
    (27, "Trump vows to cap credit card interest at 10%", "AP"),
    (29, "India vs New Zealand first Test ends in draw", "Reuters"),
    (30, "Gukesh-Sindarov World Chess Championship begins", "Times of India"),
    (31, "49ers rout Vikings 35-10 in Mexico City; Purdy throws 3 TDs", "AP"),
    (32, "Broncos beat Raiders 38-24 in Denver", "AP"),
    (33, "Tyson Fury reveals schizophrenia diagnosis", "BBC Sport"),
    (34, "USA, Australia clinch Billie Jean King Cup ties", "Tennis TourTalk"),
    (35, "Commanders vs Bengals on Monday Night Football", "Sportradar"),
    (40, "California Democrat quits Congress over misconduct", "BBC"),
]

STATS = "+$1tn Nvidia value  |  0 COP31 deal  |  $1.6bn to Nepal  |  258 Democrat seats  |  24 dead in Java fire  |  153 drones"


# ------------------------------------------------------------------ png
def write_png(img, path):
    raw = bytearray()
    stride = img.w * 3
    for y in range(img.h):
        raw.append(0)
        raw += img.px[y * stride:(y + 1) * stride]

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", img.w, img.h, 8, 2, 0, 0, 0)
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
           + chunk(b"IDAT", zlib.compress(bytes(raw), 6))
           + chunk(b"IEND", b""))
    with open(path, "wb") as fh:
        fh.write(png)
    return png


# ------------------------------------------------------------------ layout
def section_head(img, f, y, text):
    f["smallb"].draw(img, MARGIN, y + 11, text, GREEN)
    img.rule(MARGIN, y + 16, CW, INK, 2)


def feature_cell(img, f, x, y, cellw, imgh, num, kicker, headline, source, still):
    img.blit_cover(still, 600, 450, x, y, cellw, imgh)
    img.border(x, y, cellw, imgh, INK, 2)
    ty = y + imgh + 4
    f["smallb"].draw(img, x, ty + 10, "%d  %s" % (num, kicker), RED)
    ty += 13
    for ln in f["head2"].wrap(headline, cellw)[:2]:
        f["head2"].draw(img, x, ty + f["head2"].ascent, ln, INK)
        ty += f["head2"].line
    f["small"].draw(img, x, ty + 10, "Source: " + source, GREEN)


def main():
    f = load_fonts()
    img = Canvas(W, H, PAPER)

    # ---- masthead: forest-green band, cream serif title ----
    img.box(0, 0, W, 70, GREEN)
    f["mast"].centred(img, W // 2, 55, "THE TUESDAY EDITION", CREAM)
    img.rule(0, 70, W, GOLD, 4)

    # ---- dateline strip ----
    f["smallb"].draw(img, MARGIN, 90, "Tuesday, 24 November 2026", DGREEN)
    right = "40 STORIES  |  EVERY STORY SOURCED  |  TUESDAY 24 NOVEMBER 2026"
    f["smallb"].draw(img, W - MARGIN - f["smallb"].width(right), 90, right, DGREEN)
    img.rule(MARGIN, 96, CW, INK, 1)

    # ---- hero: story #1, full width ----
    _, kicker, headline, summary, source, still_name = HERO
    hy = 104
    imgh = 190
    img.blit_cover(load_still(still_name), 600, 450, MARGIN, hy, 350, imgh)
    img.border(MARGIN, hy, 350, imgh, INK, 2)
    tx = MARGIN + 350 + 16
    tw = W - MARGIN - tx
    ty = hy + 4
    f["smallb"].draw(img, tx, ty + 10, "1  " + kicker, RED)
    ty += 18
    for ln in f["head"].wrap(headline, tw)[:2]:
        f["head"].draw(img, tx, ty + f["head"].ascent, ln, INK)
        ty += f["head"].line + 3
    ty += 4
    for ln in f["body"].wrap(summary, tw)[:3]:
        f["body"].draw(img, tx, ty + f["body"].ascent, ln, INK)
        ty += f["body"].line + 2
    ty += 6
    f["smallb"].draw(img, tx, ty + 10, "Source: " + source, GREEN)
    f["smallb"].draw(img, tx, ty + 28, "Nvidia value up almost $1tn", GREEN)

    # ---- features row 1: 4 cells ----
    section_head(img, f, 302, "THE DAY IN PICTURES")
    row1 = FEATURES[:4]
    cellw = 236
    gap = 13
    for i, (num, kick, hl, src, st) in enumerate(row1):
        x = MARGIN + i * (cellw + gap)
        feature_cell(img, f, x, 326, cellw, 106, num, kick, hl, src,
                     load_still(st))

    # ---- features row 2: 3 cells ----
    row2 = FEATURES[4:]
    cellw2 = 318
    gap2 = 15
    for i, (num, kick, hl, src, st) in enumerate(row2):
        x = MARGIN + i * (cellw2 + gap2)
        feature_cell(img, f, x, 507, cellw2, 130, num, kick, hl, src,
                     load_still(st))

    # ---- the rest of the day: numbered list, 2 columns x 16 rows ----
    section_head(img, f, 714, "THE REST OF THE DAY  —  32 MORE STORIES")
    colw = 482
    rowh = 16
    ly = 736
    for col in range(2):
        x = MARGIN + col * (colw + 20)
        for r in range(16):
            num, hl, src = REST[col * 16 + r]
            by = ly + r * rowh + 12
            numtxt = "%d." % num
            f["smallb"].draw(img, x, by, numtxt, GREEN)
            nx = x + f["smallb"].width(numtxt) + 6
            srctxt = " — " + src
            srcw = f["small"].width(srctxt)
            avail = x + colw - nx - srcw - 2
            shown = f["list"].shorten(hl, avail)
            f["list"].draw(img, nx, by, shown, INK)
            f["small"].draw(img, nx + f["list"].width(shown), by, srctxt, GREEN)

    # ---- stats strip ----
    img.box(0, 999, W, 25, GREEN)
    f["smallb"].centred(img, W // 2, 1017, STATS, CREAM)

    outdir = os.environ.get("MAKEFUN_OUTPUT_DIR")
    if outdir:
        path = os.path.join(outdir, "entry.png")
    else:
        path = os.path.join(os.getcwd(), "output", "entry.png")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    write_png(img, path)
    print("wrote", path)


if __name__ == "__main__":
    main()
