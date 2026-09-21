# -*- coding: utf-8 -*-
"""Check a finished burn-in: frame count, audio continuity, caption legibility.

Run:
  python verify.py out.mp4 --expect-frames 81258 [--seams 310.1 664.6]
  python verify.py out.mp4 --contact-sheet sheet.jpg --at 75 300 660 945 1340
  python verify.py source.mp4 --worst-strip        # find the hardest frames for legibility

--seams checks a window around each splice point for a silent gap. An AAC seam
that drops a frame shows up as a near-zero RMS window; continuous audio never does.

--worst-strip scans the whole video for the brightest content in the band where
captions sit and reports the worst seconds. Test legibility THERE rather than on a
convenient dark frame - a white-on-bright frame is what breaks a caption style.
"""
import argparse, glob, os, shutil, subprocess, sys, tempfile

try:
    import numpy as np
    from PIL import Image
except ImportError:
    sys.exit("needs numpy and pillow")


def probe(path, stream, entries):
    return subprocess.run(["ffprobe", "-v", "error", "-select_streams", stream,
                           "-show_entries", entries, "-of", "csv=p=0", path],
                          capture_output=True, text=True).stdout.strip()


def audio_rms(video, start, dur, ffmpeg="ffmpeg"):
    raw = tempfile.mktemp(suffix=".raw")
    subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error",
                    "-ss", str(start), "-t", str(dur), "-i", video,
                    "-vn", "-ac", "1", "-ar", "8000", "-f", "s16le", raw, "-y"],
                   check=True)
    a = np.fromfile(raw, dtype=np.int16).astype(float)
    os.remove(raw)
    w = 400
    return [float(np.sqrt((a[i:i + w] ** 2).mean())) for i in range(0, max(0, len(a) - w), w)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--expect-frames", type=int, default=None)
    ap.add_argument("--seams", type=float, nargs="*", default=[])
    ap.add_argument("--contact-sheet", default=None)
    ap.add_argument("--at", type=float, nargs="*", default=[])
    ap.add_argument("--worst-strip", action="store_true")
    ap.add_argument("--ffmpeg", default="ffmpeg")
    a = ap.parse_args()

    frames = probe(a.video, "v:0", "stream=nb_frames")
    dur = probe(a.video, "v:0", "stream=duration") or probe(a.video, "", "format=duration")
    print(f"frames {frames}   duration {dur}")
    if a.expect_frames is not None:
        ok = str(a.expect_frames) == frames
        print(f"  frame count {'OK' if ok else 'MISMATCH'} (expected {a.expect_frames})")

    for s in a.seams:
        rms = audio_rms(a.video, max(0, s - 6), 12, a.ffmpeg)
        silent = [i for i, r in enumerate(rms) if r < 5]
        print(f"  seam {s:.2f}s: {'no gap' if not silent else f'GAP at windows {silent}'}")

    if a.worst_strip:
        tmp = tempfile.mkdtemp(prefix="strip_")
        try:
            subprocess.run([a.ffmpeg, "-hide_banner", "-loglevel", "error", "-i", a.video,
                            "-vf", "fps=1,crop=1320:100:300:880,scale=330:-1,format=gray",
                            os.path.join(tmp, "s_%05d.png"), "-y"], check=True)
            fs = sorted(glob.glob(os.path.join(tmp, "s_*.png")))
            means = np.array([np.asarray(Image.open(f)).mean() for f in fs])
            top = np.argsort(-means)[:8]
            print("\nbrightest caption-strip seconds (test legibility here):")
            for i in sorted(top):
                print(f"   t={i + 1:5d}s  mean luma {means[i]:.1f}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    if a.contact_sheet and a.at:
        tmp = tempfile.mkdtemp(prefix="sheet_")
        try:
            for i, t in enumerate(a.at):
                subprocess.run([a.ffmpeg, "-hide_banner", "-loglevel", "error",
                                "-ss", str(t), "-i", a.video, "-frames:v", "1",
                                "-vf", "crop=1920:620:0:440,scale=470:-1",
                                os.path.join(tmp, f"c_{i:02d}.jpg"), "-y"], check=True)
            cols = 2
            rows = (len(a.at) + cols - 1) // cols
            subprocess.run([a.ffmpeg, "-hide_banner", "-loglevel", "error",
                            "-pattern_type", "glob", "-i", os.path.join(tmp, "c_*.jpg"),
                            "-filter_complex", f"tile={cols}x{rows}",
                            a.contact_sheet, "-y"], check=True)
            print(f"\ncontact sheet -> {a.contact_sheet}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
