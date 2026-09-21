# apex-chinese-subtitles

A [Claude Code](https://claude.com/claude-code) skill that translates an Apex
Legends gameplay video from English into Simplified Chinese and burns the
captions into the video.

Built from a real 22-minute burn-in, so the defaults are ones that survived
iteration rather than guesses.

## What it does

- Translates against a bundled 1,246-row Apex EN→中文 glossary, keeping movement
  technique names in English (`lurch`, `tap-strafe`, `RAS`, `Neo strafe`, `bhop` …)
  and using official Simplified hero names (动力小子, 兰伯特, 导管 …)
- Builds a **one-line-only** SRT — long lines are split into sequential cues, never
  wrapped — with no overlaps and nothing too fast or too brief to read
- Renders captions as white text with a dark stroke and soft shadow, **no
  background box**, in 思源黑体 / Source Han Sans Bold
- Finds chapter cards that are burned into the video (not YouTube chapter markers)
  and places a Chinese line underneath each
- Moves captions out of the way where the video has its own on-screen text, such
  as an outro card
- Encodes the final file, and can re-encode **just the seconds that changed** when
  you fix a few lines later — about 15 seconds instead of 20 minutes

Downloading video is out of scope. The source file must already exist locally.

## Install

```bash
git clone https://github.com/HedgehogsGX/apex-chinese-subtitles.git \
  ~/.claude/skills/apex-chinese-subtitles
```

Then just ask Claude Code for Chinese subtitles on a video file — the skill
triggers on its own.

## Requirements

- `ffmpeg` (any build — **libass is not required**, which is the point; captions
  are rendered in PIL because the common macOS ffmpeg builds ship without it)
- Python with `pillow` and `numpy`

## Layout

```
SKILL.md                    workflow and the settled style rules
references/glossary.md      full Apex EN→中文 glossary, 16 sections
references/pipeline.md      known traps: drift, splice arithmetic, term splitting
assets/NotoSansSC-Bold.ttf  思源黑体 Bold (static instance)
scripts/
  build_srt.py              translations → one-line timed SRT
  render.py                 stroked caption renderer
  build_overlay.py          SRT → timed transparent overlay track
  find_chapters.py          locate burned-in chapter cards
  burn_in.py                composite and encode
  splice.py                 re-encode only what changed, frame-exact
  verify.py                 frame count, audio seams, legibility contact sheet
```

## Using the scripts directly

```bash
python scripts/build_srt.py segments.json sub.srt --font assets/NotoSansSC-Bold.ttf
python scripts/build_overlay.py sub.srt ov --font assets/NotoSansSC-Bold.ttf \
    --duration 1354.351 --chapters chapters.json --avoid avoid.json
python scripts/burn_in.py source.mp4 ov/concat.txt out.mp4
python scripts/verify.py out.mp4 --expect-frames 81258 --contact-sheet sheet.jpg --at 75 660 1340
```

`build_srt.py` prints a report; treat non-zero `overlaps`, `multiline`,
`latin_cjk_runons` or `term_split_across_cues` as bugs to fix before encoding.

## Licence

The scripts and glossary are mine. `assets/NotoSansSC-Bold.ttf` is Noto Sans SC,
redistributed under the SIL Open Font License 1.1 — see `assets/NotoSansSC-OFL.txt`.
