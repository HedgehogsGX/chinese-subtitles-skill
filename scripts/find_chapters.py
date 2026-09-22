# -*- coding: utf-8 -*-
"""Locate burned-in chapter/title cards so they can be translated too.

Many creators burn "Chapter 3: Lurching Stance" style cards into the video
itself rather than using YouTube chapter markers, so `yt-dlp --write-info-json`
reports zero chapters and you have to find them in the pixels.

Method: sample 1 fps, crop the middle band where card text sits, and count
near-white pixels. A card produces a spike of several hundred against a typical
background of single digits, and - crucially - it persists for 2-6 consecutive
seconds. Bright gameplay (snow, muzzle flash, sky) also spikes, but rarely in a
run that long, so requiring a multi-second run is what separates signal from noise.
Nothing here is game-specific - it keys on brightness and persistence, not content.

This narrows hundreds of frames to a handful of candidates. Always eyeball the
reported timestamps before trusting them - read the actual card text off a frame
rather than guessing the wording.

Run:
  python find_chapters.py video.mp4 [--fps 1] [--min-run 2] [--ffmpeg ffmpeg]
"""
import argparse, glob, os, shutil, subprocess, sys, tempfile

try:
    import numpy as np
    from PIL import Image
except ImportError:
    sys.exit("needs numpy and pillow")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--fps", type=float, default=1.0)
    ap.add_argument("--min-run", type=int, default=2,
                    help="consecutive bright seconds required to count as a card")
    ap.add_argument("--threshold", type=int, default=243)
    ap.add_argument("--min-pixels", type=int, default=400)
    ap.add_argument("--max-pixels", type=int, default=3000)
    ap.add_argument("--ffmpeg", default="ffmpeg")
    a = ap.parse_args()

    tmp = tempfile.mkdtemp(prefix="chapters_")
    try:
        # middle band only: 70% width, 28% height starting at 38% down
        vf = (f"fps={a.fps},crop=iw*0.7:ih*0.28:iw*0.15:ih*0.38,"
              f"scale=336:-1,format=gray")
        subprocess.run([a.ffmpeg, "-hide_banner", "-loglevel", "error",
                        "-i", a.video, "-vf", vf,
                        os.path.join(tmp, "f_%05d.png"), "-y"], check=True)

        files = sorted(glob.glob(os.path.join(tmp, "f_*.png")))
        counts = np.array([(np.asarray(Image.open(f)) > a.threshold).sum()
                           for f in files])

        hits = np.where((counts > a.min_pixels) & (counts < a.max_pixels))[0]
        groups = []
        for h in hits:
            if groups and h - groups[-1][-1] <= 2:
                groups[-1].append(h)
            else:
                groups.append([h])

        cards = [g for g in groups if len(g) >= a.min_run]
        print(f"scanned {len(files)} frames at {a.fps} fps; "
              f"median white-pixel count {np.median(counts):.0f}")
        print(f"{len(cards)} card-like runs (>= {a.min_run}s):\n")
        for g in cards:
            s = g[0] / a.fps
            e = (g[-1] + 1) / a.fps
            peak = counts[g[int(np.argmax(counts[g]))]]
            print(f'  {{"start": {s:.0f}, "end": {e:.0f}, "zh": ""}},'
                  f'   # peak {peak}, spans {s:.0f}-{e:.0f}s')
        print("\nRead each card's text off a frame before filling in \"zh\":")
        if cards:
            t = cards[0][0] / a.fps + 1
            print(f'  {a.ffmpeg} -ss {t:.0f} -i "{a.video}" -frames:v 1 card.png -y')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
