# -*- coding: utf-8 -*-
"""Re-encode only the part of the video whose captions changed, then splice.

A late fix to two or three cues does not justify a 20-minute full re-encode. This
re-encodes just the window between two keyframes either side of the change, from
the SOURCE with a fresh overlay, and joins it to the untouched video either side
with stream copy. Typical cost: about 15 seconds.

Run:
  python splice.py current.mp4 source.mp4 new_sub.srt out.mp4 \
      --font <ttf> --change-from 310.0 --change-to 316.0 \
      --duration 1354.351 [--chapters c.json] [--avoid a.json] [--bottom 940]

out.mp4 may be the same path as current.mp4; the result is written beside it and
only moved into place once it has been checked.

The window's overlay is rebuilt from scratch by build_overlay.py, so it must get
every placement flag the full build got: --bottom, --size, --chapter-bottom,
--chapter-size, --variation, and the same --chapters and --avoid. A flag left out
falls back to build_overlay.py's default, and the re-encoded window then puts its
captions somewhere other than the rest of the video - at y=975 instead of 940,
say, on top of a StarCraft observer's scoreboard.

The cut is done in packets, not seconds. `-t`/`-ss` with `-c copy` cut on the
decode timestamp, and with B-frames the keyframe's DTS is two frames before its
PTS - so `-t kf1` used to drag the keyframe and the P-frame after it into the
head, where they collided with the middle piece. Instead the current file's
video packets are listed once (about 2 s for an hour of 1080p60), the cuts go at
keyframes that no other frame displays across (closed GOP, x264's default), and
head + mid + tail is the original frame count by construction.

Only video is spliced. The audio track is copied whole from the current file:
captions never touch it, and re-encoding a window of it to AAC used to add
encoder priming at every seam, which the concat demuxer counted as part of the
middle piece - +23 to +256 ms per splice, plus a near-silent blip.

Frames become seconds through the frame rate, so it must be the file's real one.
--fps defaults to what ffprobe reports for the current file (e.g. 30000/1001). A
fixed 60 would put the middle window at half its true time on a 30 fps video.

The script checks its own output against the current file before handing it
over: same frame count, head and tail packets identical, every frame on its
original timestamp, DTS strictly increasing, audio packets identical. Run
verify.py afterwards as well (see references/pipeline.md).
"""
import argparse, atexit, math, os, shutil, subprocess, sys, tempfile
from fractions import Fraction

HERE = os.path.dirname(os.path.abspath(__file__))
# conda's ffmpeg 4.3.2 renices itself to 19 under x264 - see references/pipeline.md
FFMPEG = "/opt/homebrew/bin/ffmpeg" if os.path.exists("/opt/homebrew/bin/ffmpeg") else "ffmpeg"


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, capture_output=True, text=True, **kw)


def ffprobe_for(ffmpeg):
    # the ffprobe from the same build: timestamps read by one version and cut by
    # another could disagree on how an MP4 edit list is applied
    p = os.path.join(os.path.dirname(ffmpeg), "ffprobe")
    return p if os.path.dirname(ffmpeg) and os.path.exists(p) else "ffprobe"


def probe(path, stream, entries, ffprobe="ffprobe"):
    out = run([ffprobe, "-v", "error", "-select_streams", stream,
               "-show_entries", entries, "-of", "csv=p=0", path]).stdout.strip()
    return out.split("\n")[0]


def rows(compact):
    """Parse ffprobe -of compact=p=0 output into dicts, one per section."""
    lines = []
    for line in compact.splitlines():
        if line.startswith("|") and lines:     # 4.3.2 breaks the line where side data goes
            lines[-1] += line
        elif line:
            lines.append(line)
    return [dict(kv.split("=", 1) for kv in line.split("|") if "=" in kv) for line in lines]


def packets(path, stream="v:0", ffprobe="ffprobe"):
    """Packets of one stream in decode order: (pts, dts, size, keyframe), in time_base ticks."""
    out = run([ffprobe, "-v", "error", "-select_streams", stream,
               "-show_entries", "packet=pts,dts,size,flags", "-of", "compact=p=0", path]).stdout
    pk = []
    for f in rows(out):
        if "pts" not in f:
            continue
        if f["pts"] == "N/A" or f["dts"] == "N/A":
            sys.exit(f"{path}: {stream} packet without a timestamp; cannot splice it")
        pk.append((int(f["pts"]), int(f["dts"]), int(f["size"]), f["flags"].startswith("K")))
    return pk


def clean_cuts(pk):
    """Keyframe indices where nothing decoded before displays after, and nothing after displays before."""
    n = len(pk)
    suffix_min = [0] * (n + 1)
    suffix_min[n] = float("inf")
    for i in range(n - 1, -1, -1):
        suffix_min[i] = min(pk[i][0], suffix_min[i + 1])
    cuts, prefix_max = [], float("-inf")
    for i, (pts, _, _, key) in enumerate(pk):
        if key and prefix_max < pts and suffix_min[i] == pts:
            cuts.append(i)
        prefix_max = max(prefix_max, pts)
    return cuts


def quote(path):
    return "'" + os.path.abspath(path).replace("'", "'\\''") + "'"


def check(out, current, cur_v, i1, i2, window, ffprobe, exact=True):
    """List what differs between the spliced file and the current one. Empty = good.

    window: the PTS the new frames should have. exact=False: keyframes may have
    grown by the SPS/PPS repeated in front of them.
    """
    problems = []
    out_v = packets(out, "v:0", ffprobe)
    if len(out_v) != len(cur_v):
        return [f"{len(out_v)} frames, current has {len(cur_v)}"]
    o0, c0 = out_v[0][0], cur_v[0][0]
    rel = lambda p, z: (p[0] - z, p[1] - z, p[2] if exact or not p[3] else 0, p[3])
    if [rel(p, o0) for p in out_v[:i1]] != [rel(p, c0) for p in cur_v[:i1]]:
        problems.append("head packets differ from the current file")
    if [rel(p, o0) for p in out_v[i2:]] != [rel(p, c0) for p in cur_v[i2:]]:
        problems.append("tail packets differ from the current file")
    if sorted(p[0] - o0 for p in out_v[i1:i2]) != [p - c0 for p in window]:
        problems.append("new frames are not on the expected timestamps")
    bad = [i for i in range(1, len(out_v)) if out_v[i][1] <= out_v[i - 1][1]]
    if bad:
        problems.append(f"DTS not increasing at {len(bad)} packet(s), first at frame {bad[0]}")
    if o0 != c0:
        problems.append(f"video starts at tick {o0}, current starts at {c0}")
    if packets(out, "a", ffprobe) != packets(current, "a", ffprobe):
        problems.append("audio packets differ from the current file")
    return problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("current"); ap.add_argument("source")
    ap.add_argument("srt"); ap.add_argument("out")
    ap.add_argument("--font", required=True)
    ap.add_argument("--change-from", type=float, required=True)
    ap.add_argument("--change-to", type=float, required=True)
    ap.add_argument("--duration", type=float, required=True)
    ap.add_argument("--fps", default=None, help="default: the current file's own rate")
    ap.add_argument("--crf", type=int, default=20)
    ap.add_argument("--preset", default="fast")
    ap.add_argument("--chapters", default=None)
    ap.add_argument("--avoid", default=None)
    ap.add_argument("--variation", default=None)
    # placement, passed on to build_overlay.py - give the values the full build used
    ap.add_argument("--size", type=int, default=None)
    ap.add_argument("--chapter-size", type=int, default=None)
    ap.add_argument("--bottom", type=int, default=None)
    ap.add_argument("--chapter-bottom", type=int, default=None)
    ap.add_argument("--ffmpeg", default=FFMPEG)
    a = ap.parse_args()
    ffprobe = ffprobe_for(a.ffmpeg)
    fps = Fraction(a.fps or probe(a.current, "v:0", "stream=r_frame_rate", ffprobe))
    tb = Fraction(probe(a.current, "v:0", "stream=time_base", ffprobe))
    start = probe(a.current, "", "format=start_time", ffprobe)
    start = Fraction(start) if start not in ("", "N/A") else Fraction(0)

    pk = packets(a.current, "v:0", ffprobe)
    total = len(pk)
    print(f"current file: {total} frames")

    cuts = clean_cuts(pk)
    before = [i for i in cuts if pk[i][0] * tb <= a.change_from]
    after = [i for i in cuts if pk[i][0] * tb >= a.change_to and (not before or i > before[-1])]
    if not before:
        sys.exit("no clean keyframe at or before --change-from")
    i1 = before[-1]
    i2 = after[0] if after else total          # no keyframe after: re-encode to the end
    kf1 = pk[i1][0] * tb
    kf2 = pk[i2][0] * tb if i2 < total else None
    print(f"splice at keyframes {float(kf1):.3f} and "
          f"{f'{float(kf2):.3f}' if kf2 is not None else 'end of file'}")

    hf, mf, tf = i1, i2 - i1, total - i2
    head_end = float(hf / fps)
    mid_end = float((hf + mf) / fps)
    print(f"head {hf}  mid {mf}  tail {tf}  -> mid window {head_end:.6f}..{mid_end:.6f}")

    tmp = tempfile.mkdtemp(prefix="splice_")
    atexit.register(shutil.rmtree, tmp, True)      # on every exit, aborts included
    mid = os.path.join(tmp, "mid.mp4")

    ovdir = os.path.join(tmp, "ov")
    cmd = [sys.executable, os.path.join(HERE, "build_overlay.py"), a.srt, ovdir,
           "--font", a.font, "--duration", str(a.duration),
           "--start", f"{head_end:.6f}", "--end", f"{mid_end:.6f}"]
    if a.chapters: cmd += ["--chapters", a.chapters]
    if a.avoid:    cmd += ["--avoid", a.avoid]
    if a.variation: cmd += ["--variation", a.variation]
    for flag, val in (("--size", a.size), ("--chapter-size", a.chapter_size),
                      ("--bottom", a.bottom), ("--chapter-bottom", a.chapter_bottom)):
        if val is not None: cmd += [flag, str(val)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    print(r.stdout)
    if r.returncode != 0:
        sys.exit(f"build_overlay.py failed:\n{r.stderr}")

    # Seek half a frame early: hf/fps is not exact in 6 decimals at 30000/1001, and
    # landing on the right frame should not depend on how ffmpeg rounds it back.
    # setpts then puts the first kept frame at 0, where the overlay track starts. yuva420p before fps, as in
    # burn_in.py: converted once per caption state. Video only - audio is copied.
    seek = ["-ss", f"{float((hf - Fraction(1, 2)) / fps):.6f}"] if hf else []
    timescale = ["-video_track_timescale", str(tb.denominator)] if tb.numerator == 1 else []
    run([a.ffmpeg, "-hide_banner", "-loglevel", "error", "-stats",
         *seek, "-i", a.source,
         "-f", "concat", "-safe", "0", "-i", os.path.join(ovdir, "concat.txt"),
         "-filter_complex",
         f"[0:v]setpts=PTS-STARTPTS[m];[1:v]format=yuva420p,fps={fps}[ov];"
         f"[m][ov]overlay=0:0:eof_action=pass[v]",
         "-map", "[v]", "-frames:v", str(mf),
         "-c:v", "libx264", "-crf", str(a.crf), "-preset", a.preset,
         "-pix_fmt", "yuv420p", *timescale, mid, "-y"])

    mk = packets(mid, "v:0", ffprobe)
    if len(mk) != mf:
        sys.exit(f"middle segment is {len(mk)} frames, expected {mf}; aborting")
    if Fraction(probe(mid, "v:0", "stream=time_base", ffprobe)) != tb:
        sys.exit("middle segment's time base differs from the current file's; aborting")
    # Each piece's DTS runs a fixed number of frames behind its PTS (2 for x264's
    # B-pyramid). Unequal delays make DTS jump backwards at a seam.
    if mk[0][0] - mk[0][1] != pk[i1][0] - pk[i1][1]:
        sys.exit("middle segment's B-frame delay differs from the current file's - "
                 "was the full build made with another --preset? Re-run with that one.")
    # The MP4 keeps one copy of SPS/PPS, the first piece's. If the middle piece's
    # differ (another --preset in the full build), let the concat demuxer's
    # auto_convert repeat them in front of every keyframe, which costs ~50 bytes per
    # keyframe; otherwise switch it off so head and tail stay byte-identical.
    xd = lambda p: run([ffprobe, "-v", "error", "-select_streams", "v:0", "-show_data_hash",
                        "md5", "-show_entries", "stream=extradata_hash", "-of", "csv=p=0",
                        p]).stdout.strip()
    same_params = xd(mid) == xd(a.current)
    if not same_params:
        print("note: the middle piece's SPS/PPS differ from the current file's; "
              "repeating them in-band at every keyframe")
    # The new frames take the window's slots from kf1 on, and nothing outside the
    # window moves: the audio stays aligned with the head and tail it came with.
    # In a clean file they fill the window exactly. A file spliced by the old
    # splice.py can have a window longer than its frame count (its seams overlapped
    # and shifted); the last new frame is then held until the tail.
    window = sorted(pk[i1][0] + p[0] - mk[0][0] for p in mk)
    regular = window == sorted(p[0] for p in pk[i1:i2])
    if i2 < total and not regular:
        gap = pk[i2][0] - window[-1] - (1 / fps) / tb
        if gap < 0:
            sys.exit("the window's timestamps are irregular (an earlier splice?) and the new "
                     "frames would overlap the tail; re-run burn_in.py for a clean base")
        print(f"warning: the window's timestamps are irregular (an earlier splice?); the last "
              f"new frame is held {float(gap * tb * 1000):.1f} ms before the tail")
    mid_dur = kf2 - kf1 if i2 < total else mf / fps

    # One pass over the current file: head up to kf1's IDR (outpoint is checked
    # against DTS, so it sits half a frame before that packet's DTS), the new
    # middle, then the tail from kf2's IDR (inpoint rounded up to the microsecond,
    # so the backward seek lands on it rather than the keyframe before).
    # Durations are given exactly, so no piece's own start or end moves the next.
    lst = os.path.join(tmp, "join.txt")
    us = lambda t: f"{float(t):.6f}"
    with open(lst, "w") as f:
        f.write("ffconcat version 1.0\n")
        if hf:
            f.write(f"file {quote(a.current)}\n"
                    f"outpoint {us(pk[i1][1] * tb - Fraction(1, 2) / fps)}\n"
                    f"duration {us(kf1 - start)}\n")
        f.write(f"file {quote(mid)}\nduration {us(mid_dur)}\n")
        if tf:
            c = math.ceil(pk[i2][0] * tb * 1000000)
            f.write(f"file {quote(a.current)}\ninpoint {c // 1000000}.{c % 1000000:06d}\n")

    # -copyts: without it ffmpeg rebases each input to its own start, and the concat
    # input's start is the AAC priming packet at -1024 samples - which shifted the
    # whole video 23 ms later. The concat demuxer has already taken `start` off.
    out_dir = os.path.dirname(os.path.abspath(a.out))
    staged = os.path.join(out_dir, f".splice-{os.getpid()}.mp4")
    atexit.register(lambda: os.path.exists(staged) and os.remove(staged))
    run([a.ffmpeg, "-hide_banner", "-loglevel", "error", "-copyts",
         *(["-itsoffset", us(start)] if start else []),
         "-f", "concat", "-safe", "0", "-auto_convert", "0" if same_params else "1",
         "-i", lst, "-i", a.current,
         "-map", "0:v", "-map", "1:a?", "-c", "copy", "-movflags", "+faststart", staged, "-y"])

    problems = check(staged, a.current, pk, i1, i2, window, ffprobe, same_params)
    if problems:
        kept = os.path.splitext(a.out)[0] + ".splice-failed.mp4"
        os.replace(staged, kept)
        sys.exit(f"\nsplice check failed, {a.out} left untouched; result kept at {kept}:"
                 "\n  " + "\n  ".join(problems))
    os.replace(staged, a.out)
    print(f"\n{a.out}: {total} frames (source had {total}) OK - head, tail and audio "
          f"unchanged, " + ("every frame on its original timestamp" if regular else
                            "window re-timed (see warning)"))


if __name__ == "__main__":
    main()
