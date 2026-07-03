# Next Rush Extended Level Data Format

## Skill

Represents a skill activation event.

### Fields

* **#BEAT (float)**
* **effect (int)**: The type of skill effect to apply. Takes on one of the following values:
  * SCORE = 0
  * HEAL = 1
  * JUDGMENT = 2
  * HIDE_COMBO = 3
  * HIDE_PRIMARY_METRIC = 4
  * HIDE_SECONDARY_METRIC = 5
  * HIDE_JUDGMENT = 6
* **level (int)**: The displayed level of the skill. May be negative (shown with a leading `-`). Defaults to 1.
* **value (int, optional)**: The amount of life restored by a HEAL skill. May be negative to drain life instead (shown with a leading `-`). Defaults to 250.
* **scale (float, optional)**: The score boost multiplier of a SCORE skill; displayed as a percentage (1.0 = 100%). Defaults to 1.0.
* **duration (float, optional)**: The effect duration in seconds for skills that have one (SCORE's score-boost window, JUDGMENT's perfect-lock window, and the `HIDE_*` skills' hide window). Defaults to 6.

### Hide skills

`HIDE_COMBO`, `HIDE_PRIMARY_METRIC`, `HIDE_SECONDARY_METRIC`, and `HIDE_JUDGMENT` hide a UI element for `duration` seconds starting at `#BEAT`. They activate silently — no skill bar sprite and no skill alarm sound — and fade the element out over 0.2s at the start and back in over 0.2s at the end.

| Effect                  | Hides                     |
| ----------------------- | ------------------------- |
| HIDE_COMBO              | Combo                     |
| HIDE_PRIMARY_METRIC     | Score bar (primary metric) |
| HIDE_SECONDARY_METRIC   | Life bar (secondary metric) |
| HIDE_JUDGMENT           | Judgment                  |

They act on the engine's **custom** UI only (the corresponding `Custom ...` option must be on). Native Sonolus UI visibility is fixed for the whole level and cannot be toggled at runtime, so when a custom element is disabled its native counterpart stays visible. They have no effect on score or life. `level`, `value`, and `scale` are ignored.

## FeverChance

Represents the start of the fever chance period.

**Note:** A level can contain exactly one `FeverChance` and exactly one `FeverStart` event. They must always appear as a pair, and `FeverChance` must occur at an earlier `#BEAT` than `FeverStart`.

### Fields

* **#BEAT (float)**
* **force (bool)**: Whether to force the fever chance UI and effects to appear even in scenarios where they normally wouldn't (e.g., solo play).

## FeverStart

Represents the start of the active fever period.

**Note:** A level can contain exactly one `FeverStart` event, which must be paired with and occur strictly after the `FeverChance` event.

### Fields

* **#BEAT (float)**