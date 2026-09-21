# -*- coding: utf-8 -*-
"""Re-encode only the part of the video whose captions changed, then splice.

A late fix to two or three cues does not justify a 20-minute full re-encode. This
cuts the finished file at keyframes either side of the change, re-encodes just
that window from the SOURCE with a fresh overlay, and concatenates the three
pieces with stream copy. Typical cost: about 15 seconds.

Run:
  python splice.py current.mp4 source.mp4 new_sub.srt out.mp4 \
      --font <ttf> --change-from 310.0 --change-to 316.0 \
      --duration 1354.351 [--chapters c.json] [--avoid a.json]

The arithmetic is the fiddly part, so it is done in frames rather than seconds.
`-t` and `-ss` with `-c copy` land on keyframe boundaries and rarely give back
exactly the time you asked for, so asking for "the segment from 310.0" and
assuming you got it is how you end up with duplicated or missing frames at the
seam. Instead: cut head and tail first, count their frames, and derive the middle
as whatever is left over. head + mid + tail must equal the original frame count
exactly - the script refuses to continue if it does not.

After splicing, verify two things: the frame count still matches, and the audio
has no silent window at either seam (see verify.py).
"""
import argparse, json, os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, capture_output=True, text=True, **kw)


def probe(path, stream, entries):
    out = run(["ffprobe", "-v", "error", "-select_streams", stream,
               "-show_entries", entries, "-of", "csv=p=0", path]).stdout.strip()
    return out.split("\n")[0]


def keyframes(path, start, span):
    out = run(["ffprobe", "-v", "error", "-select_streams", "v:0",
               "-skip_frame", "nokey", "-show_entries", "frame=best_effort_timestamp_time",
               "-of", "csv=p=0", "-read_intervals", f"{start}%+{span}", path]).stdout
    return [float(x) for x in out.split() if x.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("current"); ap.add_argument("source")
    ap.add_argument("srt"); ap.add_argument("out")
    ap.add_argument("--font", required=True)
    ap.add_argument("--change-from", type=float, required=True)
    ap.add_argument("--change-to", type=float, required=True)
    ap.add_argument("--duration", type=float, required=True)
    ap.add_argument("--fps", type=int, default=60)
    ap.add_argument("--crf", type=int, default=20)
    ap.add_argument("--preset", default="fast")
    ap.add_argument("--chapters", default=None)
    ap.add_argument("--avoid", default=None)
    ap.add_argument("--variation", default=None)
    ap.add_argument("--ffmpeg", default="ffmpeg")
    a = ap.parse_args()

    total = int(probe(a.current, "v:0", "stream=nb_frames"))
    print(f"current file: {total} frames")

    kfs = keyframes(a.current, max(0, a.change_from - 20), (a.change_to - a.change_from) + 40)
    before = [k for k in kfs if k <= a.change_from]
    after = [k for k in kfs if k >= a.change_to]
    if not before or not after:
        sys.exit("could not find keyframes bracketing the change; widen the window")
    kf1, kf2 = before[-1], after[0]
    print(f"splice at keyframes {kf1:.3f} and {kf2:.3f}")

    tmp = tempfile.mkdtemp(prefix="splice_")
    head = os.path.join(tmp, "head.mp4")
    tail = os.path.join(tmp, "tail.mp4")
    mid = os.path.join(tmp, "mid.mp4")

    run([a.ffmpeg, "-hide_banner", "-loglevel", "error", "-i", a.current,
         "-t", f"{kf1:.6f}", "-c", "copy", "-avoid_negative_ts", "make_zero", head, "-y"])
    run([a.ffmpeg, "-hide_banner", "-loglevel", "error", "-ss", f"{kf2:.6f}",
         "-i", a.current, "-c", "copy", "-avoid_negative_ts", "make_zero", tail, "-y"])

    hf = int(probe(head, "v:0", "stream=nb_frames"))
    tf = int(probe(tail, "v:0", "stream=nb_frames"))
    mf = total - hf - tf
    if mf <= 0:
        sys.exit(f"frame arithmetic failed: head {hf} + tail {tf} >= total {total}")
    head_end = hf / a.fps
    mid_end = (hf + mf) / a.fps
    print(f"head {hf}  mid {mf}  tail {tf}  -> mid window {head_end:.6f}..{mid_end:.6f}")

    ovdir = os.path.join(tmp, "ov")
    cmd = [sys.executable, os.path.join(HERE, "build_overlay.py"), a.srt, ovdir,
           "--font", a.font, "--duration", str(a.duration),
           "--start", f"{head_end:.6f}", "--end", f"{mid_end:.6f}"]
    if a.chapters: cmd += ["--chapters", a.chapters]
    if a.avoid:    cmd += ["--avoid", a.avoid]
    if a.variation: cmd += ["--variation", a.variation]
    print(subprocess.run(cmd, capture_output=True, text=True).stdout)

    run([a.ffmpeg, "-hide_banner", "-loglevel", "error", "-stats",
         "-ss", f"{head_end:.6f}", "-i", a.source,
         "-f", "concat", "-safe", "0", "-i", os.path.join(ovdir, "concat.txt"),
         "-filter_complex",
         f"[1:v]format=rgba,fps={a.fps}[ov];[0:v][ov]overlay=0:0:eof_action=pass[v]",
         "-map", "[v]", "-map", "0:a", "-frames:v", str(mf),
         "-c:v", "libx264", "-crf", str(a.crf), "-preset", a.preset,
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", mid, "-y"])

    got = int(probe(mid, "v:0", "stream=nb_frames"))
    if got != mf:
        sys.exit(f"middle segment is {got} frames, expected {mf}; aborting")

    lst = os.path.join(tmp, "join.txt")
    with open(lst, "w") as f:
        for p in (head, mid, tail):
            f.write(f"file '{p}'\n")
    run([a.ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0",
         "-i", lst, "-c", "copy", "-movflags", "+faststart", a.out, "-y"])

    final = int(probe(a.out, "v:0", "stream=nb_frames"))
    print(f"\n{a.out}: {final} frames (source had {total}) "
          f"{'OK' if final == total else 'MISMATCH - inspect the seams'}")


if __name__ == "__main__":
    main()
