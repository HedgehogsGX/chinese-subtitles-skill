# -*- coding: utf-8 -*-
"""Composite the overlay track onto the video and encode the final file.

Run:
  python burn_in.py source.mp4 overlay/concat.txt out.mp4 [--fps 30000/1001] [--crf 20]

Audio is stream-copied, so the encode only touches video. --fps defaults to the
source's own rate.

Expect roughly 1.2-1.7x realtime at preset fast on Apple silicon; a 22-minute
1080p60 video takes about 15-20 minutes. Re-encoding YouTube footage typically
lands around double the source bitrate, because CRF faithfully preserves the
compression artefacts already baked in. That is normal, not a mistake.

If you only changed a few captions, do NOT rerun this - use splice.py instead.
"""
import argparse, subprocess, sys


def source_fps(path):
    return subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                           "-show_entries", "stream=r_frame_rate", "-of", "csv=p=0", path],
                          check=True, capture_output=True, text=True).stdout.strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source"); ap.add_argument("concat"); ap.add_argument("out")
    ap.add_argument("--fps", default=None, help="default: the source's own rate")
    ap.add_argument("--crf", type=int, default=20)
    ap.add_argument("--preset", default="fast")
    ap.add_argument("--ffmpeg", default="ffmpeg")
    a = ap.parse_args()
    fps = a.fps or source_fps(a.source)

    cmd = [a.ffmpeg, "-hide_banner", "-loglevel", "error", "-stats",
           "-i", a.source, "-f", "concat", "-safe", "0", "-i", a.concat,
           "-filter_complex",
           f"[1:v]format=rgba,fps={fps}[ov];[0:v][ov]overlay=0:0:eof_action=pass[v]",
           "-map", "[v]", "-map", "0:a",
           "-c:v", "libx264", "-crf", str(a.crf), "-preset", a.preset,
           "-pix_fmt", "yuv420p", "-c:a", "copy",
           "-movflags", "+faststart", a.out, "-y"]
    print(" ".join(cmd), "\n")
    sys.exit(subprocess.run(cmd).returncode)


if __name__ == "__main__":
    main()
