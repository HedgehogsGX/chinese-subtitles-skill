# video-chinese-subtitles

A [Claude Code](https://claude.com/claude-code) skill that translates an English
video into Simplified Chinese and burns the captions into it.

Built from a real 22-minute Apex Legends burn-in, so the defaults are ones that
survived iteration rather than guesses. The pipeline itself is subject-agnostic —
nothing in the scripts knows what the footage is. What changes per video is the
glossary.

## What it does

- Translates against a bundled per-game EN→中文 glossary — **Apex Legends**
  (1,217 rows), **Warframe** (3,844), **osu!** (429), **Minecraft 速通/MCSR**
  (358), **StarCraft 星际争霸** (761), **Counter-Strike 反恐精英** (884, with
  callouts for every Active Duty map), **ARC Raiders** (1,069, with every official
  map location) — each with its own 字幕使用原则 conventions for which jargon stays
  in English and which official Simplified name to use
- Handles video with no glossary too: talks, vlogs, tutorials, other games. It
  translates against verifiable official names and hands back the list of terms
  it had to settle, which is the seed of the next glossary
- Builds a **one-line-only** SRT — long lines are split into sequential cues, never
  wrapped — with no overlaps and nothing too fast or too brief to read
- Renders captions as white text with a dark stroke and soft shadow, **no
  background box**, in 思源黑体 / Source Han Sans Bold
- Finds chapter cards that are burned into the video (not YouTube chapter markers)
  and places a Chinese line underneath each
- Moves captions out of the way where the video has its own on-screen text, such
  as a HUD or an outro card
- Encodes the final file, and can re-encode **just the seconds that changed** when
  you fix a few lines later — about 15 seconds instead of 20 minutes

Downloading video is out of scope. The source file must already exist locally.

## Install

```bash
git clone https://github.com/HedgehogsGX/chinese-subtitles-skill.git \
  ~/.claude/skills/video-chinese-subtitles
```

Then just ask Claude Code for Chinese subtitles on a video file — the skill
triggers on its own.

## Requirements

- `ffmpeg` (any build — **libass is not required**, which is the point; captions
  are rendered in PIL because the common macOS ffmpeg builds ship without it)
- Python with `pillow` and `numpy`

## Layout

```
SKILL.md                         workflow and the settled style rules
references/glossaries/
  README.md                      which glossary to read, and which of its sections
  apex.md                        Apex Legends, S29
  warframe.md                    Warframe, 国际服 update 43
  osu.md                         osu! — standard, mania, taiko, catch
  minecraft-mcsr.md              Minecraft 速通 1.16.1 RSG + MCSR Ranked
  starcraft.md                   星际争霸 — SC2 虚空之遗 ladder + Brood War
  counter-strike.md              反恐精英 — CS2, per-map callouts, 国服 differences
  arc-raiders.md                 ARC Raiders — client strings, every map location
references/pipeline.md           known traps: drift, splice arithmetic, term splitting
assets/NotoSansSC-Bold.ttf       思源黑体 Bold (static instance)
scripts/
  build_srt.py                   translations → one-line timed SRT
  render.py                      stroked caption renderer
  build_overlay.py               SRT → timed transparent overlay track
  find_chapters.py               locate burned-in chapter cards
  burn_in.py                     composite and encode
  splice.py                      re-encode only what changed, frame-exact
  verify.py                      frame count, audio seams, legibility contact sheet
```

## Adding a glossary

Drop a `<game>.md` file in `references/glossaries/` and add a row to the table in
its README. The existing seven share a shape — a `字幕使用原则` section, term tables
with **英文或缩写 | 字幕首选 | 中文社区常见说法 | 说明**, and a 最容易误译的词 list —
and that shape is what makes them usable while translating rather than only as
reading. `references/glossaries/README.md` has the full convention.

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

The scripts and glossaries are mine. `assets/NotoSansSC-Bold.ttf` is Noto Sans SC,
redistributed under the SIL Open Font License 1.1 — see `assets/NotoSansSC-OFL.txt`.
