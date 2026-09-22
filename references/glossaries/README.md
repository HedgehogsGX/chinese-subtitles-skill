# Glossaries — index and routing

Each file here is a full EN→简体中文 glossary for one game. They exist because
machine translation gets game jargon wrong in a way that is invisible unless you
already play the game, and wrong in the same places every time: `fortress` vs
`stronghold`, `mod` as three unrelated things, `bastion` as 棱堡.

**Read the index below, pick the one glossary that matches the video, and read
its 字幕使用原则 section in full before translating anything.** That section is
short and it is where the per-game conventions live — which names stay in
English, which official translation to prefer, which two words must never be
conflated.

Do not read a whole glossary. `warframe.md` alone is 3,800 rows. Read the
principles section, then the sections the video actually touches, then grep for
individual terms as they come up:

```bash
grep -n "tap-strafe" references/glossaries/apex.md
```

## What is here

| Game | File | Rows | Scope as written | Last verified |
|---|---|---|---|---|
| Apex Legends | `apex.md` | 1,217 | 国际版，赛季 29「超频风暴」 | 2026-08-17 |
| Warframe | `warframe.md` | 3,844 | 国际服，更新 43 | 2026-07-28 |
| osu! | `osu.md` | 429 | 四个模式 + lazer/stable | 2026-07-26 |
| Minecraft 速通 / MCSR | `minecraft-mcsr.md` | 358 | 1.16.1 RSG + MCSR Ranked | 2026-09-21 |

## Which sections to read

**`apex.md`** — 身法 videos are the common case, and §3 身法与移动 is the section
that matters most; it is also the one auto-captions destroy. Add §5 for hero and
ability names, §6 for weapons and attachments, §10 for map POI names (all 128 HUD
locations have settled Simplified names — do not invent one), §12 for the
misreading list.

**`warframe.md`** — the three index sections at the end (§30 MOD, §31 武器, §32
灵化) are lookup tables, not reading material; grep them. For a build or farming
video read §5 MOD/配装, §7 货币资源, §8 任务类型. For lore or update coverage read
§13 阵营敌人, §20 Warframe: 1999. §26 国服名称混用警示 matters whenever the video
might touch the Tencent build — 国际服 and 国服 have entirely different Warframe
names and mixing them is the signature mistake.

**`osu.md`** — §1 modes and clients first (`standard` ≠ `stable` traps most
translators). Then the mode the video is about: §5–6 for osu! standard patterns
and play styles, §7–8 for mania key patterns, §9 taiko, §10 catch. §4 for mod
abbreviations, §12 for tournament vocabulary, §14 for the misreading list.

**`minecraft-mcsr.md`** — read §1 categories and timing and the warning at the
top about how much of this the Chinese community just says in English. Then §3
the run structure, and whichever of §4–8 the video covers. §13 is the misreading
list, and `fortress` / `stronghold` is the single highest-frequency error in the
whole file.

## When the video has no glossary here

Most videos will not. That is the normal case, not a failure:

- **Another game.** Say so up front, translate against whatever official
  Simplified names you can verify, and keep a list of the terms you had to decide
  on. Offer that list at the end — it is the seed of the next glossary file.
- **Not a game at all.** Talks, vlogs, documentaries, tutorials. Skip this
  directory entirely; the caption style rules in `SKILL.md` still apply, and they
  are the part that actually determines whether the output looks right.

Never guess a Chinese name and present it as official. If it is not verified, use
a descriptive translation and say in your handoff that it is not an official name.

## Adding a glossary

Drop a `<game>.md` file in this directory and add a row to the table above. The
four existing files share a shape worth copying, because it is what makes them
usable mid-translation rather than only as reading:

- YAML frontmatter with `source_scope` and `updated` — scope matters because
  game terminology is version-dependent, and a glossary without a date silently
  rots.
- A `字幕使用原则` section near the top: the numbered conventions for this game.
- Term tables with the columns **英文或缩写 | 字幕首选 | 中文社区常见说法 | 说明**.
  The third column is the point. Official names are findable; knowing that 弹幕
  says 猪堡 for a bastion remnant, and that it belongs in a stream clip but not
  in a tutorial, is not.
- A 最容易误译的词 section — the words that look translatable and are not.
- A sources section, separating official from community, so a later reader can
  tell which rows are authoritative and which are observed usage.

These four came from `HedgehogGX's Vault/Atlas/`. When a glossary is updated
there, copy it here again — this directory is the published copy, not the
working one.
