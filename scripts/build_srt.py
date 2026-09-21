# -*- coding: utf-8 -*-
"""Turn per-segment translations into a clean, ONE-LINE-ONLY Chinese SRT.

Input: JSON list of segments, each {"i", "start", "end", "en", "zh"}.
       "en" is the source English for that segment - it is load-bearing, see below.
       Segments with no "zh" (or empty) are dropped, which is how you skip
       music stings and irreparably garbled ASR.

Output: an SRT where every cue is a single line, no overlaps, nothing too fast
        or too brief to read.

Run:  python build_srt.py segments.json out.srt --font <ttf> [--maxw 1100]

Why each pass exists - these are failure modes that actually happened, not theory:

1. MERGE. YouTube's ASR chops sentences mid-clause, sometimes leaving a fragment
   with a 0.24s window - unreadable at 35 chars/sec. Merging fixes it, but naive
   merging concatenates two *separate* utterances into a run-on ("算了好",
   "是，长官你好啊"). The English tells you which is which: if the previous
   segment's English did not end a sentence, the next one continues it and the
   join is safe. If it did, they are different utterances - leave them apart even
   though one is brief. A 1-3 character interjection at 0.3s reads fine anyway.

2. HYGIENE. Cap overlong cues, give short ones room where the gap allows, then
   remove overlaps. Order matters: capping before extending before de-overlapping
   avoids a later pass undoing an earlier one.

3. SPLIT. Split anything wider than --maxw at punctuation nearest the middle.
   Never split between two Latin letters - that is what once broke "Neo strafe"
   across two cues ("...怎么把 Neo" / "strafe 接成前向 bhop"). Splitting happens
   after merging, so merging is deliberately not width-capped: a merge that makes
   a line too long simply gets re-split at a better boundary.
"""
import argparse, json, re, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from render import text_width

PUNCT = "，。；：？！、—"
ENDS_SENTENCE = re.compile(r'[.!?]["\')\]]?\s*$')


def nch(t):
    return len(re.sub(r"\s", "", t))


def fmt(s):
    h = int(s // 3600); m = int(s % 3600 // 60); x = s % 60
    return f"{h:02d}:{m:02d}:{x:06.3f}".replace(".", ",")


def join_zh(a, b):
    """Concatenate, inserting a space only where CJK meets Latin."""
    if re.search(r"[A-Za-z0-9]$", a) and re.match(r"^[A-Za-z0-9一-鿿]", b):
        return a + " " + b
    if re.search(r"[一-鿿]$", a) and re.match(r"^[A-Za-z0-9]", b):
        return a + " " + b
    return a + b


def best_split(t):
    """Index to cut at: punctuation nearest the middle, else a safe space."""
    cands = [m.end() for m in re.finditer(f"[{PUNCT}]", t)]
    cands = [p for p in cands if 3 <= p <= len(t) - 2]
    if cands:
        return min(cands, key=lambda p: abs(p - len(t) / 2))
    # a space is only safe if it is not inside a multi-word Latin term
    sp = [m.start() for m in re.finditer(r" ", t)
          if 3 <= m.start() <= len(t) - 2
          and not (re.search(r"[A-Za-z]$", t[:m.start()])
                   and re.match(r"^[A-Za-z]", t[m.start() + 1:]))]
    return min(sp, key=lambda p: abs(p - len(t) / 2)) if sp else None


def build(segments, font, size=54, variation=None, maxw=1100,
          max_dur=6.0, gap=0.05, min_dur=0.55, max_cps=16.0, target_cps=13.0):
    W = lambda t: text_width(t, font, size, variation=variation)

    kept = [s for s in segments if (s.get("zh") or "").strip()]
    kept.sort(key=lambda s: s["start"])
    cues = [[s["start"], s["end"], s["zh"].replace("\n", ""), s["i"]] for s in kept]

    # which segments continue the previous sentence, per the English
    eng = {s["i"]: s.get("en", "") for s in segments}
    ids = [s["i"] for s in kept]
    cont = {}
    for k, sid in enumerate(ids):
        prev = ids[k - 1] if k > 0 else None
        cont[sid] = bool(prev and not ENDS_SENTENCE.search(eng.get(prev, "").strip()))

    # --- pass 1: merge only true sentence continuations -------------------
    changed = True
    while changed:
        changed = False
        for i in range(len(cues)):
            nxt = cues[i + 1][0] if i + 1 < len(cues) else cues[i][1] + 9
            if nxt - cues[i][0] >= 0.50:
                continue
            if i > 0 and cont.get(cues[i][3]):
                cues[i - 1][2] = join_zh(cues[i - 1][2], cues[i][2])
                cues[i - 1][1] = max(cues[i - 1][1], cues[i][1])
                del cues[i]; changed = True; break
            if i + 1 < len(cues) and cont.get(cues[i + 1][3]):
                cues[i + 1][0] = cues[i][0]
                cues[i + 1][2] = join_zh(cues[i][2], cues[i + 1][2])
                del cues[i]; changed = True; break

    # --- pass 2: timing hygiene -------------------------------------------
    n = len(cues)
    for i, c in enumerate(cues):
        nxt = cues[i + 1][0] if i + 1 < n else c[1] + max_dur
        if c[1] - c[0] > max_dur:
            c[1] = c[0] + max_dur
        want = max(0.45, nch(c[2]) / target_cps)
        if c[1] - c[0] < want:
            c[1] = min(c[0] + want, nxt - gap)
        if c[1] > nxt - gap:
            c[1] = nxt - gap
        if c[1] <= c[0] + 0.30:
            c[1] = c[0] + 0.30
    for i in range(n - 1):
        if cues[i][1] > cues[i + 1][0]:
            cues[i][1] = max(cues[i][0] + 0.25, cues[i + 1][0] - 0.01)

    # --- pass 3: split anything too wide for one line ----------------------
    def split(st, en, t, depth=0):
        if W(t) <= maxw or depth >= 3:
            return [[st, en, t]]
        p = best_split(t)
        if p is None:
            return [[st, en, t]]
        a, b = t[:p].strip(), t[p:].strip()
        if not a or not b:
            return [[st, en, t]]
        mid = st + (en - st) * nch(a) / max(nch(a) + nch(b), 1)
        if mid - st < min_dur or en - mid < min_dur:
            return [[st, en, t]]
        if nch(a) / (mid - st) > max_cps or nch(b) / (en - mid) > max_cps:
            return [[st, en, t]]
        return split(st, mid, a, depth + 1) + split(mid, en, b, depth + 1)

    out = []
    for gid, c in enumerate(cues):
        pieces = split(c[0], c[1], c[2])
        for p in pieces:
            p.append(gid)          # provenance: which original cue this came from
        out.extend(pieces)
    for i in range(len(out) - 1):
        if out[i][1] > out[i + 1][0] - 0.01:
            out[i][1] = out[i + 1][0] - 0.01
        if out[i][1] <= out[i][0]:
            out[i][1] = out[i][0] + 0.20
    return out


def report(out, font, size, variation, maxw):
    W = lambda t: text_width(t, font, size, variation=variation)
    ws = [W(c[2]) for c in out]
    issues = {
        "cues": len(out),
        "max_width_px": round(max(ws)),
        "over_maxw": sum(1 for x in ws if x > maxw),
        "overlaps": sum(1 for i in range(len(out) - 1) if out[i][1] > out[i + 1][0] + 1e-3),
        "too_fast_18cps": sum(1 for c in out if nch(c[2]) / (c[1] - c[0]) > 18),
        "under_0.35s": sum(1 for c in out if c[1] - c[0] < 0.35),
        "multiline": sum(1 for c in out if "\n" in c[2]),
        "latin_cjk_runons": sum(1 for c in out
                                if re.search(r"[A-Za-z0-9][一-鿿]", c[2])),
        # only a boundary the splitter introduced can have broken a term; two
        # adjacent sentences that merely abut on Latin words are fine
        "term_split_across_cues": sum(
            1 for i in range(len(out) - 1)
            if len(out[i]) > 3 and out[i][3] == out[i + 1][3]
            and re.search(r"[A-Za-z]$", out[i][2]) and re.match(r"^[A-Za-z]", out[i + 1][2])),
    }
    return issues


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("segments"); ap.add_argument("out")
    ap.add_argument("--font", required=True)
    ap.add_argument("--size", type=int, default=54)
    ap.add_argument("--variation", default=None)
    ap.add_argument("--maxw", type=float, default=1100)
    a = ap.parse_args()

    segs = json.load(open(a.segments, encoding="utf-8"))
    out = build(segs, a.font, a.size, a.variation, a.maxw)
    with open(a.out, "w", encoding="utf-8") as f:
        for i, c in enumerate(out, 1):
            f.write(f"{i}\n{fmt(c[0])} --> {fmt(c[1])}\n{c[2]}\n\n")

    for k, v in report(out, a.font, a.size, a.variation, a.maxw).items():
        print(f"  {k}: {v}")
    print(f"\nwrote {a.out}")


if __name__ == "__main__":
    main()
