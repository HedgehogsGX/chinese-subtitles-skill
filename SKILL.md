---
name: video-chinese-subtitles
description: Translate any English video into Simplified Chinese and burn the captions into it, starting from nothing more than a link (YouTube, or anything yt-dlp supports) or a file already on disk. Downloads the video, its English captions and its description; covers glossary-consistent translation, one-line caption timing, stroked white captions with no background box, burned-in chapter-card translation, full encode, and cheap targeted re-encode when only a few lines change; delivers the captioned MP4, an SRT, a TXT with the preferred Chinese title and an exact translation of the video's description, and the video's cover image. Bundles EN→中文 glossaries for Apex Legends, Warframe, osu!, Minecraft speedrun/MCSR, StarCraft (SC2 and Brood War), Counter-Strike 2 (with per-map callouts) and ARC Raiders (with every map location), and works on non-gaming video too — talks, vlogs, tutorials, documentaries. Use this whenever the user pastes a video link and wants it in Chinese, wants Chinese subtitles or 中文字幕 on a video, wants captions burned/hardcoded into an MP4, wants a video translated for reposting, has a gameplay video that needs translating, asks to fix or restyle subtitles on a video they already have, or mentions 身法/lurch/tap-strafe translation — even if they do not name this skill and even if they only ask for "subtitles" generally.
---

# 视频中文字幕 — translate and burn in

Takes a video link, or an English video already on disk, and produces a
Simplified-Chinese hardcoded version. Four files are handed over: the captioned
MP4, a matching SRT, a TXT with the Chinese title and description, and the cover.

A bare link is a complete request. Download, translate, encode and deliver all
four files without asking for the file or for permission to download it.

The pipeline is subject-agnostic — it was built on a 22-minute Apex movement
video, but nothing in the scripts knows or cares what the footage is. What
changes per video is the glossary and the caption band position.

## What good output looks like

The person using this cares about a specific, already-settled look. These are not
defaults to reconsider each time — they were arrived at by iterating on real
output, and changing them silently will be treated as a regression:

- **Simplified Chinese only.** Never mixed Traditional. Verify before delivering.
- **One line per caption, always.** Two-line captions are the single most common
  complaint. If a line is too long, split it into two sequential cues rather than
  wrapping. `build_srt.py` enforces this.
- **Captions are short.** "One line" is not licence for a very wide line. Target
  at most ~1100px rendered width (about 57% of frame at 1080p).
- **No full stops.** No 。 anywhere in a caption: drop a trailing one, and where
  two sentences share a line, separate them with a space. Commas, question and
  exclamation marks stay. `build_srt.py` enforces this.
- **No background box.** White text, hard dark stroke, soft dark shadow.
- **思源黑体 / Source Han Sans Bold** (bundled at `assets/NotoSansSC-Bold.ttf`).
  Upright and heavy, with strong Latin glyphs — this style of video is full of
  English jargon set inside Chinese sentences, and a display face handles that
  badly.
- **Jargon the community actually says in English stays in English.** Which terms
  those are is a per-subject question, and it is what the glossaries answer.
- **Burned-in chapter cards get a Chinese line underneath**, not on top.

## Workflow

### 1. Get the source, and pick a glossary

From a link, work in a folder of its own:

```bash
python scripts/fetch.py "<url>" --outdir <work-dir>
```

Always quote the URL — unquoted, zsh treats the `?` in a YouTube link as a glob.
This writes `source.mp4`, `source.en.vtt` (English captions), `source.jpg` (the
cover), `source.info.json`, `title.en.txt` and `description.en.txt`, and prints
the size, fps, duration and frame count of the video and which caption track it
took.

The download is pinned to 1920x1080 H.264 with AAC audio, not "best": the overlay
is drawn for exactly that frame, and `splice.py` joins audio by stream copy. A
16:9 video that only exists smaller is upscaled. If `fetch.py` exits with
`PROBLEM: source is …, not 16:9` (vertical, ultrawide, 4:3), stop and ask the user
whether to pad it to 1920x1080 — a caption drawn for 1920x1080 lands off-frame.

If yt-dlp answers "Sign in to confirm you're not a bot", or the video is
age-restricted or members-only, ask the user before re-running with
`--cookies-from-browser chrome` (or their browser): it reads their logged-in
browser session. Do not reach for cookies unasked.

If the user gave a file rather than a link, probe it instead, and if they have the
link too, run `fetch.py "<url>" --no-video` to get the captions, title,
description and cover without downloading the video again:

```bash
ffprobe -v error -show_entries format=duration -show_entries stream=codec_type,codec_name,width,height,r_frame_rate -of default=nw=1 source.mp4
```

Either way, note duration and frame count exactly — later steps depend on them.

Then work out what the video is about and read `references/glossaries/README.md`,
which routes to the right file and says which of its sections to read. Read the
matched glossary's `字幕使用原则` section in full before translating — it is short,
and it is where the conventions for that game live.

Bundled: Apex Legends, Warframe, osu!, Minecraft 速通/MCSR, StarCraft 星际争霸,
Counter-Strike 反恐精英, ARC Raiders.

**If there is no glossary for this video, that is the normal case.** Translate
against verifiable official Simplified names, keep a list of the terms you had to
decide on, and hand that list over at the end. If a term has no official Chinese
name, use a descriptive translation and say that it is not official — do not
present a guess as settled. Never invent a name for something that already has one.

### 2. Get an English transcript with timings

`fetch.py` saved the best English track as `source.en.vtt` and said which kind it
is. A creator-uploaded track is cue-based and usually has the jargon right. A
YouTube ASR track is a usable base, but it is rolling captions with word-level
timing tags, so de-duplicate it into sentence segments.

If there is no English track at all, tell the user before going further: the
video may not be in English, or it needs transcribing first.

**Auto-captions mangle jargon badly and you must repair it while translating.**
ASR transcribes phonetically against a general-English model, so every domain
term that is not a common word comes back as a plausible wrong word. Real
examples from Apex movement footage: "forward rez/raft/raz" → `RAS`, "Neor
strafe" → `Neo strafe`, "pedo strafe" → `Pito strafe`, "mantel boost" → mantle
boost, "alerts" → lurches, "my VO was so high" → my velo (velocity), "I couldn't
attach out of that" → couldn't tap-strafe out of that. Expect the same class of
damage in any jargon-dense video — the glossary is what lets you recognise it.

Where speech is genuinely unrecoverable — music stings, overlapping shouting —
leave `zh` empty for that segment so it is dropped, and tell the user which
timestamps you dropped. Inventing a plausible line is worse than no line.

### 3. Translate into a segments JSON

```json
[{"i": 1, "start": 0.24, "end": 4.90,
  "en": "Seeing movement players pull off tricks like these is super cool and all, but",
  "zh": "看身法玩家秀出这种操作确实很酷，但真正的问题是"}]
```

Keep `en` — it is not decorative. `build_srt.py` uses it to tell a sentence
continuation from a separate utterance when deciding whether two cues may be
merged, which is what prevents run-ons like `算了好` or `是，长官你好啊`.

### 4. Build the SRT

```bash
python scripts/build_srt.py segments.json sub.srt --font assets/NotoSansSC-Bold.ttf
```

It prints a report. Treat non-zero `overlaps`, `multiline`, `latin_cjk_runons` or
`term_split_across_cues` as bugs to fix before encoding. A few `under_0.35s` cues
are fine when they are 1–3 character interjections — check them, don't assume.

### 5. Find and translate burned-in chapter cards

```bash
python scripts/find_chapters.py source.mp4
```

Creators often burn chapter cards into the video rather than using YouTube
chapters, so the metadata shows none. This reports candidate windows; extract a
frame from each and **read the actual card text** before writing the translation.
Output `chapters.json`: `[{"start":42,"end":46,"zh":"第 1 章：定义 lurch 组合"}]`.

### 6. Check for places captions would collide with on-screen text

Outro cards are the usual offender — captions at the normal position land on top
of the creator's socials. Extract a frame, find the gap, and declare it:

```json
[{"from": 1334.0, "to": 100000, "bottom": 820}]
```

The default caption band sits above a typical FPS HUD. A different game, or
non-gaming footage, may put its own elements there — a MOBA minimap, a rhythm
game's judgement line, a talk's lower third. Extract a frame and look before
accepting the default. To move the band for the whole video, give
`build_overlay.py` `--bottom <y>` (940 sits just above a StarCraft observer's
player-stats bar), and write the value down: every later splice needs it too.

### 7. Build the overlay and encode

```bash
python scripts/build_overlay.py sub.srt ov --font assets/NotoSansSC-Bold.ttf \
    --duration 1354.351 --chapters chapters.json --avoid avoid.json
python scripts/burn_in.py source.mp4 ov/concat.txt out.mp4
```

Check the overlay's reported drift is a few milliseconds, not hundreds.

Before committing to a ~20 minute encode, composite one overlay PNG onto a real
frame in PIL and look at it. It costs seconds and catches position and font
mistakes that would otherwise surface 20 minutes later.

### 8. Write the title and description TXT while the encode runs

`<name>.txt`, next to `<name>.mp4`, UTF-8, in exactly this shape:

```
【标题】
<the preferred Chinese title>

【简介】
<the description, translated in full>
```

The title and the description are different jobs.

**The title is the preferred one, singular** — the title you would actually
publish, not a list of options and not a word-for-word gloss. Keep the original's
hook and its claims; do not inflate it into clickbait it was not. Keep the
creator's name, series name or episode number if the original has them. The
glossary applies exactly as it does to the captions, so jargon the community says
in English stays in English.

**The description is an exact translation** of `description.en.txt` — translate
from that file, not from memory of the page:

- Every line, in order. Nothing summarised, merged, reordered, added or left out;
  line breaks and blank lines stay where they are.
- Kept verbatim: URLs, @handles, hashtags, email addresses, creator or discount
  codes, and timestamps. The chapter name after a timestamp is translated, and
  matches the chapter-card translation where both name the same chapter.
- Music and licence attribution blocks stay in their original English, because the
  licence requires that exact form.
- Same glossary choices as the captions, and Simplified Chinese only.
- Normal Chinese punctuation, 。 included — the no-full-stop rule is for captions.
- An empty description becomes `（原视频无简介）` under `【简介】`.

If the video is a repost, say in chat — not in the file — that a first-person
description reads as the reposter's own words. The file stays an exact
translation either way.

### 9. Verify

```bash
python scripts/verify.py out.mp4 --expect-frames <frames> \
    --contact-sheet sheet.jpg --at 75 300 660 945 1340
```

Look at the sheet. Confirm: single lines, legible over bright frames, chapter
lines under their cards, nothing colliding with HUD or outro text.

### 10. Later fixes — splice, don't re-encode

When the user asks to change a few lines (they will), rebuild the SRT, diff it
against the previous one to find which cues moved, then:

```bash
python scripts/splice.py out.mp4 source.mp4 sub.srt out_fixed.mp4 \
    --font assets/NotoSansSC-Bold.ttf --change-from 310 --change-to 316 \
    --duration 1354.351 --chapters chapters.json --avoid avoid.json
python scripts/verify.py out_fixed.mp4 --expect-frames <frames> --seams 310 316
```

15 seconds instead of 20 minutes. The frame count must come out identical.

**A splice gets the same placement flags as the full build.** `splice.py`
re-renders its window with `build_overlay.py`, so pass it everything the full
build was given — `--bottom`, `--size`, `--chapter-bottom`, `--chapter-size`,
`--variation`, and the same `--chapters` and `--avoid` — and it forwards them. A
flag left out falls back to its default: a video built with `--bottom 940` gets
its spliced window drawn at 975, on top of the scoreboard. Anything done to the
overlay PNGs by hand after `build_overlay.py` is not replayed either; a fix inside
such a stretch needs the overlay rebuilt and that step redone.

## Deliverables

Four files side by side, sharing one base name — `<video-id>.zh` unless the
user asks for something else:

- `<name>.mp4` — the captioned video
- `<name>.srt` — dialogue plus chapter lines, merged and renumbered, so the
  captions can be edited later without redoing the work
- `<name>.txt` — the preferred Chinese title and the exact translation of the
  description (step 8)
- `<name>.jpg` — the cover: `source.jpg`, the video's own thumbnail, unaltered.
  A separate file, not embedded in the MP4 — upload forms take the cover on its
  own. If `fetch.py` reported no cover, say so rather than grabbing a frame.

Keep `source.mp4` and the work folder until the user is done asking for fixes —
`splice.py` re-encodes from the source.

If you had to settle terms that were not in a glossary, list them. A term decided
once and written down is worth more than the same decision made differently next
time; `references/glossaries/README.md` says how to turn a list like that into a
glossary file.

## Reference material

- `references/glossaries/README.md` — which glossary to read, which sections of
  it, and what to do when the video has none. Start here.
- `references/glossaries/*.md` — the glossaries themselves. Large. Read the
  principles section and the relevant sections; grep for individual terms.
- `references/pipeline.md` — technical notes and the specific traps in this
  pipeline. Read it before debugging anything that looks like a download, timing,
  splice, or rendering problem; most of them have already been diagnosed once.
