# Pipeline notes and known traps

Everything here was diagnosed the hard way during a real 22-minute burn-in. If
something in the pipeline is behaving oddly, check here before investigating from
scratch.

## Why captions are rendered in PIL, not by ffmpeg

The obvious approach is `ffmpeg -vf subtitles=sub.srt`, which needs **libass**.
Neither of the ffmpeg builds commonly present on macOS has it:

- conda-forge ffmpeg: `--enable-libfreetype` only, no libass
- Homebrew ffmpeg 9.0.2: no libass, and no libfreetype either — so `drawtext` is
  out as well. It does have libx264, and it is the build the scripts encode with
  where it exists (see the macOS traps below)

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

## Convert the overlay to yuva420p before `fps`, not after

`burn_in.py` and `splice.py` feed the overlay track through
`[1:v]format=yuva420p,fps=<fps>[ov]` into `overlay`. They used `format=rgba`
until October 2026. The pixels are the same, but rgba made the overlay the
slowest part of the encode.

`overlay` blends in yuva420p, so when handed RGBA, ffmpeg inserts its own
RGBA→YUVA conversion just before it. That is *after* `fps`, which has already
repeated each caption state out to the video's frame rate, so the conversion runs
single-threaded on every output frame — 214,000 of them for an hour at 60 fps —
and the queued RGBA frames cost gigabytes of memory. Converting before `fps`
does it once per caption state, and `fps` repeats the converted frame.

Measured back to back on an M4: 60 s of 1080p60 StarCraft footage, 20 caption
states, Homebrew ffmpeg 9.0.2, libx264 crf 20 preset fast.

| overlay graph | speed | peak memory |
|---|---|---|
| `format=rgba,fps=60/1` | 2.3x | 4.2 GB |
| `format=yuva420p,fps=60/1` | 3.1x | 0.9 GB |

On full-length videos with other work competing for the CPU, the gap was wider:
rgba ran at 0.27–0.5x and passed 5 GB, yuva420p held 1–1.5x under 1 GB.

Same output, checked three ways on that clip: the raw yuv420p frame at a
captioned timestamp was byte-identical; the framemd5 of all 3601 frames matched
under both ffmpeg 4.3.2 and 9.0.2; and `burn_in.py`'s H.264 stream had the same
MD5 with either graph. If the graph ever changes again, recheck it the same way:

```bash
for g in rgba yuva420p; do
  ffmpeg -i clip.mp4 -f concat -safe 0 -i ov/concat.txt -filter_complex \
    "[1:v]format=$g,fps=60/1[ov];[0:v][ov]overlay=0:0:eof_action=pass[v]" \
    -map "[v]" -f framemd5 -pix_fmt yuv420p $g.md5 -y
done
diff rgba.md5 yuva420p.md5 && echo identical
```

## Splicing: cut in packets, leave the audio alone

`splice.py` re-encodes only the video between two keyframes either side of the
change and joins it to the untouched rest with stream copy. Until October 2026 it
made every spliced file a little longer and left a glitch at each seam. On a 60 s
1080p60 clip, one splice by the old script against one by the current one:

| | video duration | audio | at the head→mid seam |
|---|---|---|---|
| before splicing | 60.0000 s | 60.0000 s, 2585 packets | — |
| old, ffmpeg 9.0.2 | 60.0462 s, starting at 0.0232 | 60.0694 s, 2586 packets | two frames on one PTS, DTS going backwards |
| old, ffmpeg 4.3.2 | +256 ms | | |
| now, either build | 60.0000 s | 60.0000 s, packets byte-identical | clean |

A real 1080p60 video spliced three times by the old script came out 133 ms long
in video and 141–149 ms in audio, with short near-silent blips at some seams.
Four separate causes:

**`-t` with `-c copy` cuts on DTS, not PTS.** The head was cut with
`-t <kf1> -c copy`. With x264's B-pyramid a frame's DTS runs two frames behind
its PTS, so the IDR at kf1 (PTS 25.000, DTS 24.967) and the P-frame decoded after
it (PTS 25.067, DTS 24.983) both passed the test and went into the head: 1502
frames where 1500 belonged. The frame arithmetic then started the middle piece at
frame 1502, so source frame 1501 was never shown, and the stray P-frame landed on
the same PTS as one of the middle's frames. `ffmpeg -i out.mp4 -f null -` reports
"non monotonically increasing dts" there, and a default (CFR) decode drops a
frame; `-fps_mode passthrough` decodes them all.

Now the current file's video packets are listed once with ffprobe (about 2 s for
an hour of 1080p60), and the cuts go at keyframes no other frame displays across:
nothing decoded before it is shown after it, and nothing decoded after it is
shown before it. With x264's default closed GOPs that is every keyframe. The head
is every packet before the kf1 IDR in decode order, the tail is the kf2 IDR
onward, and head + mid + tail equals the original frame count by construction.

**Re-encoding the audio added AAC priming at every seam.** The middle piece's
audio was re-encoded to AAC, and ffmpeg's AAC encoder starts every stream with
1024 samples of priming (23.2 ms at 44.1 kHz) that the MP4 marks to be skipped.
The concat demuxer places each piece by its container start time, which counts
that priming packet at −1024 samples, so everything after it moved 23 ms later,
and the stream gained a packet. Captions never touch the audio, so the audio
track is now copied whole from the current file, and the middle piece is
video-only.

**The ffmpeg CLI rebases each input to its own start.** Even with video-only
pieces, the final command (`-f concat -i join.txt -i current.mp4`) shifted the
video 357 ticks (23.2 ms) late: the concat input exposes the current file's audio
stream too, its first packet is that −1024-sample priming packet, and ffmpeg
subtracts each input's start time. `-copyts` keeps every packet on the timestamp
it had in the current file.

**The concat demuxer's `auto_convert` rewrites keyframes.** It is on by default
and runs `h264_mp4toannexb`, which writes SPS/PPS in-band in front of every IDR:
44 bytes more per keyframe, head and tail included. `splice.py` switches it off
when the middle piece's SPS/PPS (the `avcC`) match the current file's, which they
do when both were encoded with the same ffmpeg and preset. When they differ, for
example with conda's 4.3.2 x264 against Homebrew's, or a full build made with
`--preset medium`, it leaves it on. The MP4 keeps only the first piece's SPS/PPS,
and the in-band copies are what let the middle decode.

The join is one pass straight from the current file, so the head and tail are
never written out as temporary files:

```
ffconcat version 1.0
file '/abs/current.mp4'
outpoint 24.958333     # half a frame before the kf1 IDR's DTS: outpoint compares DTS
duration 25.000000     # kf1's PTS, so the middle starts exactly there
file '/tmp/splice_x/mid.mp4'
duration 12.500000     # kf2 - kf1
file '/abs/current.mp4'
inpoint 37.500000      # kf2's PTS rounded UP to the microsecond: the seek is
                       # backward, and rounding down lands on the keyframe before
```

`outpoint` ends the file at the first packet of *any* stream at or past it, audio
included. That is safe for files ffmpeg muxed, because they are interleaved in DTS
order; the self-check below catches anything else.

Three smaller traps:

- **Seek the source half a frame early.** The middle is read from the source with
  an accurate `-ss`. At 30000/1001, hf/fps printed to six decimals is a hair past
  the frame (`8.341667` for 8.3416666…). ffmpeg 9.0.2 rounds that back onto the
  frame in a 1/30000 time base, but a finer time base might not, and the whole
  window would then show the next frame. `-ss (hf − ½)/fps` followed by
  `setpts=PTS-STARTPTS` takes the right frame without depending on that.
- **The B-frame delay must match.** Each piece's DTS runs a fixed number of
  frames behind its PTS: 2 for x264's presets with B-pyramid, 0 for `ultrafast`.
  If the middle's delay differs from the current file's, DTS goes backwards at one
  of the seams whichever way round. `splice.py` refuses and asks for the full
  build's `--preset`.
- **Time base.** The middle is written with the current file's
  `-video_track_timescale` (15360 at 60 fps), so ticks compare one for one.

The script checks its own output before handing it over, against the current
file: same frame count; head and tail packets identical (PTS, DTS, size, flags);
the new frames on the window's timestamps; DTS rising at every packet; the same
video start; audio packets identical. If any of it fails, the result is kept as
`<out>.splice-failed.mp4` and `<out>` is not touched. The output is written beside
`<out>` first, so splicing a file onto itself is safe.

**Files already spliced by the old script.** They carry the damage above at each
old seam. `verify.py --expect-frames N --seams … --reference source.mp4` shows it:
overlapping frames and gaps in the timestamps, durations that differ from the
source, and audio that lines up about 23 ms late. A new splice never moves
anything outside its window, so a splice elsewhere leaves old damage as it is.
A window that crosses an old seam replaces the bad frames, but those files'
timestamps run longer than their frame count, so the new frames end before the
old tail and the last one is held (46 ms in the test); `splice.py` warns when
that happens. Only re-running `burn_in.py` repairs such a file completely.

**Caption switches inside a window can move by a frame.** Not a splice bug, but
it shows up when comparing a spliced window with a full build. The overlay track
is a concat of PNGs, and the concat demuxer gives it the image stream's 1/25 s
time base, so every caption boundary snaps to a 40 ms grid that starts where the
track starts: 0.30 s becomes 0.32. A full build's track starts at 0; a splice's
starts at the window, so a boundary near a frame's midpoint can round to a
neighbouring frame. Both are within about 20 ms of the SRT. The window's frames
themselves line up with a full re-burn exactly: per-frame PSNR against it never
fell below 43 dB at offset 0, and dropped to 22 dB one frame either way.

The pieces must still share resolution, pixel format and frame rate; the middle
is encoded from the source at the current file's own rate.

**The window needs the full build's placement flags.** `splice.py` rebuilds the
overlay for its window by calling `build_overlay.py`, and every flag it does not
pass falls back to `build_overlay.py`'s default. A StarCraft video built with
`--bottom 940`, just above the observer's player-stats bar, came back from a
splice with that window's captions at the default 975, on top of the scoreboard.
`splice.py` now takes `--bottom`, `--size`, `--chapter-bottom` and
`--chapter-size` and forwards them, as it already did `--variation`, `--chapters`
and `--avoid`; give it every one the full build had. (The old workaround, an
`avoid.json` entry spanning the whole video such as
`[{"from": 0, "to": 100000, "bottom": 940}]`, still works.) Changes made to the
overlay PNGs by hand after `build_overlay.py` — moving outro captions sideways,
say — are not replayed by a splice at all.

Verify after every splice, against the file you spliced:

```bash
python scripts/verify.py out_fixed.mp4 --expect-frames <frames> \
    --seams <change-from> <change-to> --reference out.mp4
```

- frame count unchanged
- timestamps clean: DTS rising, frames one frame apart, no gap or overlap. An
  uneven source (variable frame rate) shows uneven frames here too; check the
  source the same way before blaming the splice
- durations equal to the reference's
- audio packets around each seam identical to the reference's. Decoded samples
  are no good for this: ffmpeg's AAC encoder uses perceptual noise substitution,
  and the decoder's noise generator state depends on where each file's seek
  landed, so identical packets decode slightly differently after a seek. When the
  packets do differ, `verify.py` cross-correlates the decoded audio and reports
  the offset.

Without `--reference`, `--seams` only looks for a near-silent 50 ms window, which
cannot tell a dropped AAC frame from a pause in speech.

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

Encoding 1080p60 runs at about 3x realtime at preset fast on an M4 when nothing
else is encoding, and nearer 1x with a second encode competing.

## macOS / zsh environment traps

- **The first `ffmpeg` on PATH can be a slow one.** On the Mac this was built
  on it is miniconda's 4.3.2 (`/opt/miniconda3/bin/ffmpeg`), which drops itself to
  nice 19 within a second of starting an x264 encode — `ps -o nice= -p <pid>`
  shows 19 — so any other load starves it, and full encodes crawled at ~0.25x.
  Homebrew's 9.0.2 has libx264 and keeps its normal priority. `burn_in.py`,
  `splice.py`, `verify.py` and `fetch.py` therefore default to
  `/opt/homebrew/bin/ffmpeg` when it exists, and `fetch.py` hands the same binary
  to yt-dlp; `--ffmpeg` still overrides. Homebrew's lack of libass and libfreetype
  (see the top of this file) does not matter, because captions are drawn in PIL.
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

## Downloading

`fetch.py` handles all of this; the notes are for when it misbehaves.

**JavaScript runtime.** Modern yt-dlp needs one or YouTube returns 403 and drops
formats. Deno is its default; `fetch.py` passes `--js-runtimes node` (or bun) when
Deno is missing. Without any you get `No supported JavaScript runtime could be
found`, throttled speeds, and resumes that fail with 403.

**"Sign in to confirm you're not a bot."** YouTube's bot check, triggered by
request volume from one IP. It has appeared on the second lookup in a minute. This
is why `fetch.py` extracts once with `-J` and downloads from the saved JSON via
`--load-info-json` instead of letting yt-dlp extract twice. If it still appears,
`--cookies-from-browser <browser>` gets past it, but it reads the user's browser
login, so ask first.

**Why the format is pinned.** `-f "bv*+ba[ext=m4a]/bv*+ba/b" -S
"res:1080,vcodec:h264"` resolves to 1080p H.264 plus AAC (e.g. YouTube formats
137+140, or 299+140 at 60 fps) when they exist. Every stage draws on a fixed 1920x1080 frame, so a 4K or
720p file would put captions in the wrong place. AAC because the audio is copied
into the final MP4 untouched, and AAC is what every player and upload site
accepts there. (`splice.py` used to re-encode a window of the audio to AAC and
join it to Opus head and tail, which failed; it no longer touches the audio.)

**Which caption track.** A creator-uploaded `en` track beats ASR. Among ASR
tracks, `en-orig` is recognition of the actual audio; a bare `en` without
`en-orig` is usually machine-translated from another spoken language.
`--sub-langs "en.*"` grabs `en`, `en-orig` and any regional tracks at once and
leaves you to work out which is real; `fetch.py` picks one from the metadata
first and requests only that.

**Playlist links.** A watch URL carrying `&list=` downloads the whole playlist
unless `--no-playlist` is set. `fetch.py` sets it.

**Quote the URL.** In zsh an unquoted `?` is a glob, so `fetch.py
https://www.youtube.com/watch?v=…` dies with `no matches found` before Python
even runs.
