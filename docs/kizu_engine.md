# Kizu Engine — Score & Gauge Systems

This document describes two of the engine's gameplay systems: the **Kizu score
model** (how judgments become a 0–1,000,000 arcade score) and the **gauge / life
system** (how HP behaves during a run).

---

## Score System

The engine reports a single **arcade score** out of **1,000,000**. A flawless run
(every note Perfect) scores exactly 1,000,000; every non-Perfect judgment removes
a fraction of a note's value. The score is not stored per note but recomputed as a
normalized running total.

### Per-note raw score

For each scored note the engine computes:

```
note_raw_score = judgment_multiplier × (archetype_multiplier + entity_multiplier)
```

* **judgment_multiplier** — Perfect `3.0`, Great `2.0`, Good `1.0`, Miss `0`.
* **archetype_multiplier** — the note type's base weight. Every note type carries
  the same weight, `10`.
* **entity_multiplier** — a per-note bonus, normally `0`, raised by an active
  **Score Up** skill (see below).

### Normalization

The final displayed score is the earned total divided by the **ideal total**
(the sum of every note's all-Perfect raw score), scaled to 1,000,000:

```
score = clamp( (Σ note_raw_score / Σ ideal_note_raw_score) × 1,000,000, 0, 1,000,000 )
```

Because the denominator is the all-Perfect total, a full-Perfect clear always
lands on exactly 1,000,000 regardless of note count or chart length.

### Value per judgment

Since every note carries the same weight and there is no combo streak bonus, each
note is worth an equal share of 1,000,000, and a given judgment yields a fixed
fraction of that share:

| Judgment | Fraction of note value | Raw score (entity_multiplier = 0) |
| -------- | ---------------------- | --------------------------------- |
| Perfect  | 100%                   | `3.0 × 10 = 30`                    |
| Great    | 66.6%                  | `2.0 × 10 = 20`                    |
| Good     | 33.3%                  | `1.0 × 10 = 10`                    |
| Miss     | 0%                     | `0`                               |

### Score Up skill

An active **Score Up** skill raises the `entity_multiplier` of every note that
falls inside its window (`start` to `start + duration`):

```
entity_multiplier += scale × (archetype_multiplier + entity_multiplier)
```

where `scale` is the skill's boost factor. The ideal-total denominator is computed
with the same boost applied, so skills redistribute score toward the boosted
section rather than pushing the maximum past 1,000,000.

### Score indicators

Separate from the arcade score, an optional on-screen percentage indicator can be
chosen with the **Custom Score Indicator** option:

| Value | Indicator     | Meaning                                                 |
| ----- | ------------- | ------------------------------------------------------- |
| 0     | Disable       | No percentage shown.                                    |
| 1     | Arcade% (+)   | Earned score as a percentage, counting up from 0%.      |
| 2     | Arcade% (−)   | Starts at 100% and subtracts each note's lost fraction. |
| 3     | Accuracy%     | Running average of `(1 − abs(timing error)) × 100`.     |

These are display-only; the submitted score is always the 1,000,000 arcade score.

---

## Gauge (Life) System

The gauge system offers three selectable difficulty gauges. The choice is made
through the **Gauge** option ([options.py](../sekai/lib/options.py)), a persistent,
replay-recorded setting:

| Gauge      | Character                                        |
| ---------- | ------------------------------------------------ |
| Standard   | Forgiving — Greats still heal, small penalties.  |
| Heavy      | Greats are neutral, larger penalties.            |
| Ultima     | Greats hurt, harshest penalties.                 |

### HP scale

* HP is **displayed** on a `0–1000` scale and every run **starts at 1000**.
* Internally, life is stored at **×10** (`0–10000`) so that combo-normalized
  per-note deltas stay integral. The displayed value is the internal value ÷ 10.
* HP is **capped at 1000**: at full HP no judgment can add life. At **0 HP the run
  is dead** and no judgment can restore it.

### Per-judgment values

Each gauge defines a base life delta per judgment (on the displayed `0–1000`
scale, before combo normalization):

| Judgment | Standard | Heavy | Ultima |
| -------- | -------- | ----- | ------ |
| Perfect  | `+3`     | `+3`  | `+2`   |
| Great    | `+2`     | `0`   | `−50`  |
| Good     | `−25`    | `−75` | `−100` |
| Miss     | `−50`    | `−150`| `−200` |

### Combo normalization

Base values are normalized by the chart's total combo so that every chart has the
same overall life budget regardless of length. The actual HP change a note applies
is:

```
displayed_delta = base × 2000 / total_combo
```

(`total_combo` is the number of scored notes.) Internally the stored increment is
`floor(base × factor × 20000 / total_combo)`, where `factor` is the note-type
multiplier below.

Because a positive delta is scaled by `2000 / total_combo` and summed over the
whole chart, a perfect clear pushes far past the 1000 cap — so recovery is
generous but wasted while already full. Conversely the penalties are large enough
that a run of misses drains the whole bar well before the chart ends, which is
what separates the gauges by difficulty.

### Halved note types

Notes that are cheaper to hit contribute **half** the life change (`factor = 0.5`):

* All Trace and Trace Flick notes (including Head / Tail variants)
* Slide Ticks (normal, critical, hidden)
* Damage notes

All other scored notes use the full value (`factor = 1.0`). Anchor notes have no
life effect (`factor = 0`).

### Heal skill

A **Life Up** skill schedules a fixed heal at its start time. The heal amount is
the skill's `value` (default `250` on the displayed scale), applied at the internal
`×10` scale and clamped to the `0–1000` cap. Heals are scheduled during
initialization (after the life scale is known), not in the skill's own preprocess.

### Death behavior

When the custom life bar is active (default), reaching 0 HP is **sticky**: the bar
stays empty and the dead effect plays for the rest of the run. The life value is
recorded every frame into the replay life stream (at the internal `×10` scale), so
a server reading the stream must divide by 10.
