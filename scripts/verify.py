# -*- coding: utf-8 -*-
"""Check a finished burn-in: frame count, audio continuity, caption legibility.

Run:
  python verify.py out.mp4 --expect-frames 81258 [--seams 310.1 664.6] [--reference source.mp4]
  python verify.py out.mp4 --contact-sheet sheet.jpg --at 75 300 660 945 1340
  python verify.py source.mp4 --worst-strip        # find the hardest frames for legibility

With --expect-frames or --seams, the video's timestamps are checked too: DTS must
rise at every packet and the frames must sit one frame apart with no gap or
overlap. A splice that went wrong shows up here even when the frame count is right.

--reference is the file whose audio this one must carry unchanged: the source for
a full burn-in (burn_in.py copies its audio), or the pre-splice file for a splice.
Durations are compared with it, and the audio packets around each seam must be
identical to its; if they are not, the offset that lines the audio up is reported.

Without --reference, --seams falls back to looking for a near-silent 50 ms window
around each seam. That is weak: it cannot tell a dropped AAC frame from a pause
in speech, and it misses an offset or a doubled frame entirely.

--worst-strip scans the whole video for the brightest content in the band where
captions sit and reports the worst seconds. Test legibility THERE rather than on a
convenient dark frame - a white-on-bright frame is what breaks a caption style.
"""
import argparse, glob, os, shutil, subprocess, sys, tempfile
from fractions import Fraction

try:
    import numpy as np
    from PIL import Image
except ImportError:
    sys.exit("needs numpy and pillow")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from splice import ffprobe_for, packets, rows

# conda's ffmpeg 4.3.2 renices itself to 19 under x264 - see references/pipeline.md
FFMPEG = "/opt/homebrew/bin/ffmpeg" if os.path.exists("/opt/homebrew/bin/ffmpeg") else "ffmpeg"


def probe(path, stream, entries, ffprobe="ffprobe"):
    return subprocess.run([ffprobe, "-v", "error", "-select_streams", stream,
                           "-show_entries", entries, "-of", "csv=p=0", path],
                          capture_output=True, text=True).stdout.strip()


def audio_rms(video, start, dur, ffmpeg=FFMPEG):
    raw = tempfile.mktemp(suffix=".raw")
    subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error",
                    "-ss", str(start), "-t", str(dur), "-i", video,
                    "-vn", "-ac", "1", "-ar", "8000", "-f", "s16le", raw, "-y"],
                   check=True)
    a = np.fromfile(raw, dtype=np.int16).astype(float)
    os.remove(raw)
    w = 400
    return [float(np.sqrt((a[i:i + w] ** 2).mean())) for i in range(0, max(0, len(a) - w), w)]


def audio_pcm(video, start, dur, ffmpeg=FFMPEG):
    raw = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error",
                          "-ss", str(start), "-t", str(dur), "-i", video,
                          "-vn", "-ac", "1", "-f", "s16le", "-"],
                         check=True, capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.int16).astype(float)


def audio_packets(video, start, dur, ffprobe):
    """md5 of each audio packet whose PTS falls in [start, start+dur), keyed by PTS from the stream's first packet."""
    def read(interval):
        out = subprocess.run([ffprobe, "-v", "error", "-select_streams", "a:0", "-show_data_hash",
                              "md5", "-show_entries", "packet=pts,data_hash", "-read_intervals",
                              interval, "-of", "compact=p=0", video],
                             capture_output=True, text=True).stdout
        return [(int(f["pts"]), f["data_hash"]) for f in rows(out)
                if f.get("pts", "N/A") != "N/A"]
    tb = Fraction(probe(video, "a:0", "stream=time_base", ffprobe))
    first = read("%+#1")[0][0]
    lo, hi = Fraction(start) / tb, Fraction(start + dur) / tb
    return [(p - first, h) for p, h in read(f"{max(0, start - 1)}%{start + dur + 1}")
            if lo <= p - first < hi]


def compare_audio(video, ref, start, dur, rate, ffprobe, ffmpeg=FFMPEG):
    """'identical', or the lag (ms) that best lines `video` up with `ref` and how well."""
    # Packets first: equal packets are equal audio, whatever the decoder does.
    # Decoded samples cannot be compared exactly after a seek - ffmpeg's AAC
    # encoder uses noise substitution, and the decoder's noise generator depends
    # on how many frames it has decoded, i.e. on where each file's seek landed.
    a = audio_packets(video, start, dur, ffprobe)
    if a and a == audio_packets(ref, start, dur, ffprobe):
        return "audio packets identical to reference"
    a, b = audio_pcm(video, start, dur, ffmpeg), audio_pcm(ref, start, dur, ffmpeg)
    n = min(len(a), len(b))
    if n == 0:
        return "NO AUDIO to compare"
    a, b = a[:n], b[:n]
    m = 1 << (2 * n - 1).bit_length()
    xc = np.fft.irfft(np.fft.rfft(a, m) * np.conj(np.fft.rfft(b, m)), m)
    span = int(rate * 0.25)                       # look up to 250 ms either way
    lags = np.r_[np.arange(0, span + 1), np.arange(-span, 0)]
    best = lags[np.argmax(xc[lags])]
    corr = xc[best] / (np.sqrt((a ** 2).sum() * (b ** 2).sum()) or 1)
    return (f"AUDIO DIFFERS from reference (re-encoded or moved): lines up "
            f"{abs(best) * 1000 / rate:.1f} ms "
            f"{'late' if best > 0 else 'early' if best < 0 else 'with no offset'} "
            f"(correlation {corr:.3f})")


def timestamp_problems(video, ffprobe):
    """What is wrong with the video's DTS/PTS, as readable strings. Empty = clean."""
    tb = Fraction(probe(video, "v:0", "stream=time_base", ffprobe))
    step = 1 / Fraction(probe(video, "v:0", "stream=r_frame_rate", ffprobe)) / tb
    pk = packets(video, "v:0", ffprobe)
    t = lambda ticks: f"{float(ticks * tb):.3f}s"
    out = []
    back = [i for i in range(1, len(pk)) if pk[i][1] <= pk[i - 1][1]]
    if back:
        out.append(f"DTS does not rise at {len(back)} packet(s), first at {t(pk[back[0]][1])}")
    pts = sorted(p[0] for p in pk)
    for kind, bad in (("overlapping frames", [i for i in range(1, len(pts)) if pts[i] - pts[i - 1] < step]),
                      ("gaps", [i for i in range(1, len(pts)) if pts[i] - pts[i - 1] > step])):
        if bad:
            out.append(f"{kind} at {len(bad)} place(s): " + ", ".join(t(pts[i]) for i in bad[:4])
                       + (" ..." if len(bad) > 4 else ""))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--expect-frames", type=int, default=None)
    ap.add_argument("--seams", type=float, nargs="*", default=[])
    ap.add_argument("--reference", default=None,
                    help="file whose audio this one must carry unchanged (source, or pre-splice file)")
    ap.add_argument("--contact-sheet", default=None)
    ap.add_argument("--at", type=float, nargs="*", default=[])
    ap.add_argument("--worst-strip", action="store_true")
    ap.add_argument("--ffmpeg", default=FFMPEG)
    a = ap.parse_args()

    frames = probe(a.video, "v:0", "stream=nb_frames")
    dur = probe(a.video, "v:0", "stream=duration") or probe(a.video, "", "format=duration")
    print(f"frames {frames}   duration {dur}")
    if a.expect_frames is not None:
        ok = str(a.expect_frames) == frames
        print(f"  frame count {'OK' if ok else 'MISMATCH'} (expected {a.expect_frames})")

    ffprobe = ffprobe_for(a.ffmpeg)
    if a.expect_frames is not None or a.seams:
        bad = timestamp_problems(a.video, ffprobe)
        print("  timestamps " + ("OK (DTS rising, frames evenly spaced)" if not bad
                                 else "PROBLEM:\n    " + "\n    ".join(bad)))
        vdur = probe(a.video, "v:0", "stream=duration", ffprobe)
        adur = probe(a.video, "a:0", "stream=duration", ffprobe)
        print(f"  durations: video {vdur}  audio {adur or '-'}")
        if a.reference:
            rv = probe(a.reference, "v:0", "stream=duration", ffprobe)
            ra = probe(a.reference, "a:0", "stream=duration", ffprobe)
            same = (rv, ra) == (vdur, adur)
            print(f"  durations {'match' if same else 'DIFFER from'} reference "
                  f"(video {rv}  audio {ra or '-'})")

    rate = int(probe(a.video, "a:0", "stream=sample_rate") or 0) if a.reference else 0
    for s in a.seams:
        if a.reference:
            print(f"  seam {s:.2f}s: "
                  f"{compare_audio(a.video, a.reference, max(0, s - 6), 12, rate, ffprobe, a.ffmpeg)}")
            continue
        rms = audio_rms(a.video, max(0, s - 6), 12, a.ffmpeg)
        silent = [i for i, r in enumerate(rms) if r < 5]
        print(f"  seam {s:.2f}s: {'no gap' if not silent else f'GAP at windows {silent}'}"
              " (silence check only - give --reference for a real one)")

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
