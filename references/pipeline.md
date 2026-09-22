# Pipeline notes and known traps

Everything here was diagnosed the hard way during a real 22-minute burn-in. If
something in the pipeline is behaving oddly, check here before investigating from
scratch.

## Why captions are rendered in PIL, not by ffmpeg

The obvious approach is `ffmpeg -vf subtitles=sub.srt`, which needs **libass**.
Neither of the ffmpeg builds commonly present on macOS has it:

- conda-forge ffmpeg: `--enable-libfreetype` only, no libass
- Homebrew ffmpeg 9.0.2: no libass, and no libfreetype either — so `drawtext` is
  out as well

Check before assuming:

```bash
ffmpeg -hide_banner -buildconf | grep -iE 'libass|libfreetype'
ffmpeg -hide_banner -filters | grep -wE 'subtitles|ass'
```

So captions are rendered as transparent PNGs in PIL and composited with `overlay`.
This needs no extra dependency, and it gives exact control over stroke, shadow and
per-cue vertical position — which the style requires anyway.

## Caption legibility over bright footage

A plain outline is not enough. Almost any source has near-white frames somewhere —
concrete, snow, muzzle flash, a blown-out sky, a whiteboard, a slide — and a thin
stroke there has nothing to contrast against. The style is therefore two layers: a
hard black stroke on the glyphs, plus a blurred dark halo under them that gives the
text a local darkening to sit on.

Do not judge legibility on a convenient frame. Find the worst one:

```bash
python scripts/verify.py source.mp4 --worst-strip
```

In the reference video the hardest moment was mean luma 217/255 in the caption
band. That is the frame to test against.

## Line length is measured in pixels, not characters

Fonts differ enormously in width for the same text. 得意黑 is condensed; 思源黑体
is roughly **30% wider** for identical Chinese. A character-count threshold tuned
for one font produces badly overlong lines with the other.

`build_srt.py` measures rendered width with the actual font, so switching fonts
means re-running it — the split points will legitimately move.

## Merging cues without creating run-ons

ASR fragments sometimes get a window too short to read (0.24s for 8 characters is
35 chars/sec — unreadable). Merging is the fix, but merging two *separate*
utterances produces nonsense: `算了好`, `是，长官你好啊`,
`当然，也要配合 tap-strafe我应该顺手也把这个做出来`.

The English source segment tells you which case you are in: if the previous
segment's English did not end with `.`/`!`/`?`, the next segment continues that
sentence and joining is safe. This is why the segments JSON must keep `en`.

Merging is deliberately **not** width-capped, because splitting runs afterwards —
a merge that produces an overlong line simply gets re-split at a better boundary.
Capping the merge instead blocks legitimate joins and leaves the unreadable
fragment in place.

## Never split inside a multi-word Latin term

When no punctuation is available, the splitter falls back to a space. Unguarded,
that once broke `Neo strafe` across two cues: `…怎么把 Neo` / `strafe 接成前向 bhop`.
A space is only a valid split point if it is not flanked by Latin letters on both
sides. Same hazard applies to `RAS strafe`, `Pito strafe`, `wall push` — and to
any multi-word Latin term the subject happens to use, such as `chordjack stamina`,
`bastion remnant` or `Void Relic`.

Detect it:

```python
re.search(r'[A-Za-z]$', cue_a) and re.match(r'^[A-Za-z]', cue_b)
```

## Micro-gaps silently desynchronise the overlay

Cue boundaries create intervals a few milliseconds long. Skipping them as
"negligible" shortens the overlay track, so every subsequent caption drifts
**earlier** by the running total. In a real run this reached 0.55s by the end of a
22-minute video — small enough to pass a spot check at the start, obvious at the end.

Fold each micro-gap into the previous segment instead of dropping it. Then confirm
the overlay's total equals the video duration; `build_overlay.py` prints the drift.

## concat.txt paths resolve against the list file, not the cwd

ffmpeg's concat demuxer resolves a relative `file` entry against the directory
holding the list, **not** the working directory. So a list at `ov/concat.txt`
whose entries read `file 'ov/s00001.png'` sends ffmpeg looking for
`ov/ov/s00001.png`, and the documented two-step run dies immediately:

```
[concat @ 0x…] Impossible to open 'ov/ov/s00001.png'
ov/concat.txt: No such file or directory
```

`build_overlay.py` therefore writes bare basenames, which resolve correctly and
work whether the outdir was passed as a relative or an absolute path. If you ever
hand-build a concat list, use basenames or absolute paths — never a path relative
to the cwd.

This is also why `splice.py` never hit the bug: it passes an absolute `ovdir`
under its temp directory, so the joined paths happened to be absolute already.

## Splicing: do the arithmetic in frames

`-t` and `-ss` with `-c copy` land on keyframe boundaries and rarely return
exactly the time requested. Asking for "the segment from 310.0" and assuming you
got it gives duplicated or missing frames at the seam.

Cut head and tail first, count their frames with ffprobe, and derive the middle as
`total - head - tail`. Encode the middle with `-frames:v <that number>`. The three
parts must sum to the original frame count exactly.

The pieces must also share codec parameters or `concat` will refuse or glitch —
same H.264 profile, resolution, fps, and same audio sample rate and channel count.

Verify after every splice:
- frame count unchanged
- no silent window at either seam (`verify.py --seams`)

## Sync between captions and video

The safest check is content, not arithmetic: extract frames at a couple of points
where you know what should be on screen (a chapter card, the outro card) and
confirm the caption timing lines up. Matching durations between the caption source
and the video is good evidence but not proof.

## Output size

Re-encoding YouTube footage at CRF 20 typically lands at roughly **double** the
source bitrate, because CRF faithfully preserves compression artefacts already
baked in. A 932 MB source became about 2.1 GB. That ratio matched the previous
video in the same series, so it is expected, not a misconfiguration.

Encoding runs about 1.2–1.7x realtime at preset fast on Apple silicon.

## macOS / zsh environment traps

- **`timeout` does not exist** on macOS. Use a background process plus `sleep`
  and `kill`, or install coreutils for `gtimeout`.
- **zsh aborts the whole command on an unmatched glob.** `rm -f a/*.part a/*.ytdl`
  runs *nothing* if `*.ytdl` matches nothing — so a cleanup you believe happened
  silently did not, and a stale partial file survives. Use
  `find dir -maxdepth 1 -name '*.part' -delete` instead.
- **`ps aux | grep '[y]t-dlp'` can match your own command line**, reporting a
  process that is not running. `pgrep -fl` is reliable; a growing/static file size
  is better evidence still.
- **Variable fonts** (the Google Fonts Noto Sans SC download is one) load at Thin
  by default in PIL. Either call `set_variation_by_name('Bold')` or bake a static
  instance with `fontTools.varLib.instancer`. The bundled asset is already static.

## If you need YouTube auto-captions

Out of scope for this skill, but for reference: modern yt-dlp needs a JavaScript
runtime or YouTube returns 403 and drops formats. Point it at Node:

```bash
yt-dlp --js-runtimes node --write-auto-subs --sub-langs "en.*" --skip-download URL
```

Without it you get `No supported JavaScript runtime could be found`, throttled
speeds, and resumes that fail with 403.
