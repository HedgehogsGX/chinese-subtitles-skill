# -*- coding: utf-8 -*-
"""Download a video from a link, with its English captions, title, description and cover.

Run:
  python fetch.py "URL" [--outdir work] [--no-video] [--cookies-from-browser chrome]

Writes into outdir:
  source.mp4          1920x1080 H.264 with AAC audio (see below)
  source.en.vtt       English captions: the creator's own track if any, else ASR
  source.jpg          the cover - the video's own thumbnail, largest size offered
  source.info.json    everything yt-dlp knows about the video
  title.en.txt        the original title, verbatim
  description.en.txt  the original description, verbatim - the deliverable TXT
                      translates this, so it is kept exactly as uploaded
and prints what the rest of the pipeline needs: size, fps, duration, frame count
and which caption track it took. --no-video skips the video itself, for when the
user already has the file and only the captions, text and cover are missing.

Works for YouTube and anything else yt-dlp supports. Quote the URL: unquoted, zsh
treats the `?` in a YouTube link as a glob and the `&` as a command separator.

The format is pinned, not "best":
- 1920x1080, because render.py, build_overlay.py and verify.py all draw on a fixed
  1920x1080 frame. A 16:9 source that only exists smaller is upscaled here. Any
  other shape is reported and left alone - a 1920x1080 overlay on it would put the
  captions off-frame, and whether to pad it is the user's call.
- H.264 over VP9/AV1 at the same size, so any ffmpeg build can decode it.
- AAC audio. burn_in.py stream-copies the audio and splice.py re-encodes its middle
  piece to AAC before concatenating with stream copy, so an Opus source would make
  every later splice fail. Opus is converted to AAC here instead.

Caption choice: a creator-uploaded English track beats ASR - it usually has the
jargon right. Among YouTube's ASR tracks, `en-orig` is recognition of the spoken
audio; a bare `en` with no `en-orig` beside it is normally machine-translated from
another language, which means the video is probably not in English at all.

The metadata is fetched once (-J) and the download runs from that saved JSON, so
YouTube sees one extraction rather than two - its bot check triggers on volume.
"""
import argparse, json, os, shutil, subprocess, sys

W, H = 1920, 1080


def run(cmd):
    return subprocess.run(cmd, check=True, capture_output=True, text=True)


def js_runtime():
    """YouTube needs a JS runtime or it 403s and drops formats. Deno is yt-dlp's default."""
    if shutil.which("deno"):
        return []
    for rt in ("node", "bun"):
        if shutil.which(rt):
            return ["--js-runtimes", rt]
    print("WARNING: no deno, node or bun on PATH - YouTube may drop formats or return 403")
    return []


def pick_captions(info):
    """Best English track as (lang, is_asr), or (None, None)."""
    manual = [k for k in (info.get("subtitles") or {}) if k == "en" or k.startswith("en-")]
    for lang in ("en", "en-US", "en-GB", *sorted(manual)):
        if lang in manual:
            return lang, False
    auto = info.get("automatic_captions") or {}
    for lang in ("en-orig", "en"):
        if lang in auto:
            return lang, True
    return None, None


def probe(path):
    d = json.loads(run(["ffprobe", "-v", "error", "-show_entries",
                        "stream=codec_type,codec_name,width,height,r_frame_rate,nb_frames"
                        ":format=duration", "-of", "json", path]).stdout)
    v = next(s for s in d["streams"] if s["codec_type"] == "video")
    a = next((s for s in d["streams"] if s["codec_type"] == "audio"), None)
    return v, a, float(d["format"]["duration"])


def normalise(path, ffmpeg):
    """Make the file 1920x1080 with AAC audio. Returns a problem to report, or None."""
    v, a, _ = probe(path)
    if a is None:
        return "no audio track - burn_in.py maps the source audio and will fail"
    w, h = int(v["width"]), int(v["height"])
    resize = (w, h) != (W, H)
    if resize and abs(w / h - W / H) > 0.01:
        return (f"source is {w}x{h}, not 16:9 - captions drawn for a 1920x1080 frame "
                f"would land off-frame. Ask the user whether to pad it to 1920x1080.")
    reaudio = a["codec_name"] != "aac"
    if not resize and not reaudio:
        return None

    tmp = path + ".tmp.mp4"
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-stats", "-i", path]
    if resize:
        print(f"upscaling {w}x{h} -> {W}x{H}")
        cmd += ["-vf", f"scale={W}:{H}:flags=lanczos", "-c:v", "libx264", "-crf", "18",
                "-preset", "fast", "-pix_fmt", "yuv420p"]
    else:
        cmd += ["-c:v", "copy"]
    if reaudio:
        print(f"converting {a['codec_name']} audio -> AAC")
        cmd += ["-c:a", "aac", "-b:a", "192k"]
    else:
        cmd += ["-c:a", "copy"]
    subprocess.run(cmd + ["-movflags", "+faststart", tmp, "-y"], check=True)
    os.replace(tmp, path)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--outdir", default=".")
    ap.add_argument("--no-video", action="store_true",
                    help="captions, title and description only")
    ap.add_argument("--cookies-from-browser", default=None,
                    help="only with the user's go-ahead - it reads their browser login")
    ap.add_argument("--yt-dlp", default="yt-dlp")
    ap.add_argument("--ffmpeg", default="ffmpeg")
    a = ap.parse_args()
    sys.stdout.reconfigure(line_buffering=True)   # keep our lines in order with yt-dlp's

    os.makedirs(a.outdir, exist_ok=True)
    base = os.path.join(a.outdir, "source")
    common = js_runtime() + ["--no-playlist"]
    if a.cookies_from_browser:
        common += ["--cookies-from-browser", a.cookies_from_browser]
    if a.ffmpeg != "ffmpeg":
        common += ["--ffmpeg-location", a.ffmpeg]

    r = subprocess.run([a.yt_dlp, *common, "-J", a.url], capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(r.stderr.strip() or "yt-dlp failed")
    info = json.loads(r.stdout)
    if info.get("_type") == "playlist":
        sys.exit("that is a playlist link - give the link of a single video")

    info_path = base + ".info.json"
    with open(info_path, "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False)
    for name, key in (("title.en.txt", "title"), ("description.en.txt", "description")):
        with open(os.path.join(a.outdir, name), "w", encoding="utf-8") as f:
            f.write(info.get(key) or "")

    lang, asr = pick_captions(info)
    cmd = [a.yt_dlp, *common, "--load-info-json", info_path, "-o", base + ".%(ext)s",
           "--write-thumbnail", "--convert-thumbnails", "jpg"]
    if a.no_video:
        cmd += ["--skip-download"]
    else:
        cmd += ["-f", "bv*+ba[ext=m4a]/bv*+ba/b", "-S", "res:1080,vcodec:h264",
                "--merge-output-format", "mp4", "--remux-video", "mp4", "-N", "4"]
    if lang:
        cmd += ["--write-auto-subs" if asr else "--write-subs", "--sub-langs", lang,
                "--sub-format", "vtt/best", "--convert-subs", "vtt"]
    print(" ".join(cmd), "\n")
    if subprocess.run(cmd).returncode != 0:
        sys.exit("download failed - see the yt-dlp output above")

    subs = base + ".en.vtt"
    if lang and lang != "en" and os.path.exists(f"{base}.{lang}.vtt"):
        os.replace(f"{base}.{lang}.vtt", subs)

    problem = None
    print()
    if not a.no_video:
        video = base + ".mp4"
        problem = normalise(video, a.ffmpeg)
        v, au, dur = probe(video)
        num, den = map(int, v["r_frame_rate"].split("/"))
        print(f"{video}\n  {v['width']}x{v['height']}  "
              f"{v['codec_name']}/{au['codec_name'] if au else 'no audio'}  "
              f"fps {num / den:g} ({v['r_frame_rate']})  duration {dur:.3f}s  "
              f"frames {v.get('nb_frames')}")

    if not lang or not os.path.exists(subs):
        print("captions: NONE - no English track. The video may not be in English, or it "
              "needs transcribing; tell the user before going further.")
    elif not asr:
        print(f"captions: {subs}  (creator-uploaded, '{lang}')")
    else:
        print(f"captions: {subs}  (ASR, '{lang}' - rolling captions, de-duplicate them)")
        if lang == "en":
            print("  WARNING: ASR 'en' with no 'en-orig' is usually machine-translated "
                  "from another language - check the video is actually in English")
    if info.get("language") and not info["language"].startswith("en"):
        print(f"  WARNING: yt-dlp reports the video's language as '{info['language']}'")

    cover = base + ".jpg"
    if os.path.exists(cover):
        size = run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height",
                    "-of", "csv=s=x:p=0", cover]).stdout.strip()
        print(f"cover: {cover}  ({size})")
    else:
        print("cover: NONE - the site offered no thumbnail")

    desc = info.get("description") or ""
    print(f"title: {info.get('title')}")
    print(f"description: {len(desc.splitlines())} lines -> "
          f"{os.path.join(a.outdir, 'description.en.txt')}")
    if problem:
        print(f"\nPROBLEM: {problem}")
        sys.exit(3)


if __name__ == "__main__":
    main()
