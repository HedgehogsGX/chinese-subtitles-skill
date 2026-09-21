# -*- coding: utf-8 -*-
"""Turn an SRT (+ optional chapter lines) into a timed transparent overlay track.

Emits one PNG per distinct on-screen state plus a concat-demuxer list that ffmpeg
overlays onto the video. This is how captions get burned in without libass -
Homebrew's ffmpeg ships without it, and PIL gives finer control anyway.

Run:
  python build_overlay.py sub.srt outdir --font <ttf> \
      [--chapters chapters.json] [--avoid avoid.json] [--duration 1354.351]

chapters.json: [{"start":42,"end":46,"zh":"第 1 章：..."}]
   Rendered higher up (default y=742) so it sits under the video's own burned-in
   chapter card rather than on top of the dialogue line.

avoid.json:   [{"from":1334.0,"to":1e9,"bottom":820}]
   Time ranges where dialogue must move to a different vertical position because
   the video has its own text there. The outro card is the usual case: captions at
   the normal y=975 land straight on "Find me on Tiktok and Twitch".

The micro-gap rule matters more than it looks. Cue boundaries produce intervals a
few milliseconds long. Dropping them looks harmless but silently shortens the
overlay track, so every later caption drifts EARLIER by the accumulated total -
0.55s by the end of a 22-minute video in one real case. Folding each micro-gap
into the previous segment keeps the track exactly as long as the video.
"""
import argparse, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from render import render_sub
from PIL import Image

W, H = 1920, 1080


def sec(x):
    h, m, s = x.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s.replace(",", "."))


def read_srt(path):
    out = []
    for b in open(path, encoding="utf-8").read().strip().split("\n\n"):
        L = b.split("\n")
        if len(L) < 3:
            continue
        a, e = L[1].split(" --> ")
        out.append((sec(a), sec(e), "\n".join(L[2:])))
    return out


def active(t, items):
    for s, e, payload in items:
        if s - 1e-6 <= t < e - 1e-6:
            return payload
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("srt"); ap.add_argument("outdir")
    ap.add_argument("--font", required=True)
    ap.add_argument("--size", type=int, default=54)
    ap.add_argument("--chapter-size", type=int, default=48)
    ap.add_argument("--variation", default=None)
    ap.add_argument("--bottom", type=int, default=975)
    ap.add_argument("--chapter-bottom", type=int, default=742)
    ap.add_argument("--chapters", default=None)
    ap.add_argument("--avoid", default=None)
    ap.add_argument("--duration", type=float, required=True)
    ap.add_argument("--start", type=float, default=0.0,
                    help="build only from this time (for spliced re-encodes)")
    ap.add_argument("--end", type=float, default=None)
    a = ap.parse_args()

    os.makedirs(a.outdir, exist_ok=True)
    lo = a.start
    hi = a.end if a.end is not None else a.duration

    dlg = [(s, e, t) for s, e, t in read_srt(a.srt) if e > lo and s < hi]
    dlg = [(max(s, lo), min(e, hi), t) for s, e, t in dlg]

    chapters = []
    if a.chapters:
        for c in json.load(open(a.chapters, encoding="utf-8")):
            s, e = float(c["start"]), float(c["end"])
            if e > lo and s < hi:
                chapters.append((max(s, lo), min(e, hi), c["zh"]))

    avoid = json.load(open(a.avoid, encoding="utf-8")) if a.avoid else []

    def bottom_at(t):
        for r in avoid:
            if float(r["from"]) - 1e-6 <= t < float(r["to"]):
                return int(r["bottom"])
        return a.bottom

    bounds = {lo, hi}
    for s, e, _ in dlg:      bounds.update([s, e])
    for s, e, _ in chapters: bounds.update([s, e])
    for r in avoid:
        for v in (float(r["from"]), float(r["to"])):
            if lo < v < hi:
                bounds.add(v)
    bounds = sorted(bounds)

    blank = os.path.join(a.outdir, "blank.png")
    Image.new("RGBA", (W, H), (0, 0, 0, 0)).save(blank)

    segs, cache, n = [], {}, 0
    for i in range(len(bounds) - 1):
        t0, t1 = bounds[i], bounds[i + 1]
        dur = t1 - t0
        if dur < 0.02:
            if segs:                       # never drop time - see module docstring
                segs[-1] = (segs[-1][0], segs[-1][1] + dur)
            continue
        mid = (t0 + t1) / 2
        d = active(mid, dlg)
        c = active(mid, chapters)
        b = bottom_at(t0)
        if d is None and c is None:
            segs.append((blank, dur)); continue
        key = (d, c, b)
        if key not in cache:
            img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            if c:
                img = Image.alpha_composite(img, render_sub(
                    [c], a.font, a.chapter_size, 0,
                    box_bottom=a.chapter_bottom, variation=a.variation))
            if d:
                img = Image.alpha_composite(img, render_sub(
                    d.split("\n"), a.font, a.size, 0,
                    box_bottom=b, variation=a.variation))
            n += 1
            p = os.path.join(a.outdir, f"s{n:05d}.png")
            img.save(p); cache[key] = p
        segs.append((cache[key], dur))

    listfile = os.path.join(a.outdir, "concat.txt")
    with open(listfile, "w", encoding="utf-8") as f:
        for p, d in segs:
            f.write(f"file '{p}'\nduration {d:.6f}\n")
        f.write(f"file '{segs[-1][0]}'\n")

    total = sum(d for _, d in segs)
    print(f"  states {n}  segments {len(segs)}")
    print(f"  overlay spans {total:.3f}s, window is {hi - lo:.3f}s "
          f"(drift {abs(total - (hi - lo)) * 1000:.0f} ms)")
    print(f"  {listfile}")


if __name__ == "__main__":
    main()
