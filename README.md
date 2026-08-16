# Next RUSH+ Sonolus Engine

Perspective-lane rhythm game for [Sonolus](https://sonolus.com).

## Quick Dev Setup

1. Install [uv](https://docs.astral.sh/uv/).
2. Run `uv sync`.
3. Add resources (full exported scp files) such as skins and levels to the `/resources` folder.
4. [Ensure your venv is activated](https://docs.astral.sh/uv/pip/environments/#using-a-virtual-environment).
5. Run `sonolus-py dev`.

## Custom Resources

### Skin Sprites

For each role below, the engine picks the first available sprite in the listed
order. Earlier entries take precedence over later ones, and `->` separates
fallbacks from highest to lowest priority.

Shorthand used in the tables:

- `{A, B, C}` expands to one sprite per listed value, e.g.
  `Sekai Normal Note {Left, Middle, Right}` = `Sekai Normal Note Left`,
  `Sekai Normal Note Middle`, `Sekai Normal Note Right`.
- `{1..6}` expands to a range, e.g.
  `Sekai Flick Arrow Up {1..6}` = `Sekai Flick Arrow Up 1` through
  `Sekai Flick Arrow Up 6`.
- When both appear together, every combination applies, e.g.
  `Sekai Flick Arrow {Up, Up Left, Down, Down Left} {1..6}` = 4 \* 6 = 24 sprites.

#### Stage

`<Color>` = `{Neutral, Red, Green, Blue, Yellow, Purple, Cyan, Black}`.

| Role                     | Sprite                                                              |
| ------------------------ | ------------------------------------------------------------------- |
| Stage                    | `Sekai Stage` (optional)                                            |
| Stage Border             | `Sekai Stage Border`                                                |
| Lane Background          | `Sekai Lane Background`                                             |
| Lane Divider             | `Sekai Lane Divider`                                                |
| Lane Background Preview  | `Sekai Lane Background Preview`                                     |
| Lane Divider Preview     | `Sekai Lane Divider Preview`                                        |
| Stage Border Preview     | `Sekai Stage Border Preview`                                        |
| Judgment Line Background | `Sekai Judgment Background <Color>` -> `Sekai Judgment Background`  |
| Judgment Gradient        | `Sekai Judgment Gradient <Color>`                                   |
| Judgment Edge            | `Sekai Judgment Edge <Color>`                                       |
| Judgment Single Line     | `Sekai Judgment Single Line <Color>` -> `Sekai Judgment Edge <Color>` |
| Judgment Edge Left       | `Sekai Judgment Edge Left <Color>` -> `Sekai Judgment Edge <Color>` |
| Judgment Center          | `Sekai Judgment Center <Color>`                                     |

#### Note Bodies

| Note Type                 | Bucket Icon                             | Render Style | Body Precedence                                                                                                                                                                                                                                       |
| ------------------------- | --------------------------------------- | ------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Tap                       | `Sekai Normal Note Basic`               | Normal       | `Sekai Normal Note {Left, Middle, Right}` -> `Sekai Note Cyan {Left, Middle, Right}` -> `NOTE_HEAD_CYAN`                                                                                                                                              |
| Slide                     | `Sekai Slide Note Basic`                | Normal       | `Sekai Slide Note {Left, Middle, Right}` -> `Sekai Note Green {Left, Middle, Right}` -> `NOTE_HEAD_GREEN`                                                                                                                                             |
| Flick                     | `Sekai Flick Note Basic`                | Normal       | `Sekai Flick Note {Left, Middle, Right}` -> `Sekai Note Red {Left, Middle, Right}` -> `NOTE_HEAD_RED`                                                                                                                                                 |
| Down Flick                | `Sekai Flick Note Basic`                | Normal       | `Sekai Down Flick Note {Left, Middle, Right}` -> `Sekai Flick Note {Left, Middle, Right}` -> `Sekai Note Red {Left, Middle, Right}` -> `NOTE_HEAD_RED`                                                                                                |
| Critical                  | `Sekai Critical Note Basic`             | Normal       | `Sekai Critical Note {Left, Middle, Right}` -> `Sekai Note Yellow {Left, Middle, Right}` -> `NOTE_HEAD_YELLOW`                                                                                                                                        |
| Critical Slide            | `Sekai Critical Slide Note Basic`       | Normal       | `Sekai Critical Slide Note {Left, Middle, Right}` -> `Sekai Critical Note {Left, Middle, Right}` -> `Sekai Note Yellow {Left, Middle, Right}` -> `NOTE_HEAD_YELLOW`                                                                                   |
| Critical Flick            | `Sekai Critical Flick Note Basic`       | Normal       | `Sekai Critical Flick Note {Left, Middle, Right}` -> `Sekai Critical Note {Left, Middle, Right}` -> `Sekai Note Yellow {Left, Middle, Right}` -> `NOTE_HEAD_YELLOW`                                                                                   |
| Critical Down Flick       | `Sekai Critical Flick Note Basic`       | Normal       | `Sekai Critical Down Flick Note {Left, Middle, Right}` -> `Sekai Critical Flick Note {Left, Middle, Right}` -> `Sekai Critical Note {Left, Middle, Right}` -> `Sekai Note Yellow {Left, Middle, Right}` -> `NOTE_HEAD_YELLOW`                         |
| Trace                     | `Sekai Normal Trace Note Basic`         | Slim         | `Sekai Normal Trace Note {Left, Middle, Right}` -> `Sekai Trace Note Green {Left, Middle, Right}` -> `NOTE_HEAD_GREEN`                                                                                                                                |
| Trace Flick               | `Sekai Trace Flick Note Basic`          | Slim         | `Sekai Trace Flick Note {Left, Middle, Right}` -> `Sekai Trace Note Red {Left, Middle, Right}` -> `NOTE_HEAD_RED`                                                                                                                                     |
| Trace Down Flick          | `Sekai Trace Flick Note Basic`          | Slim         | `Sekai Trace Down Flick Note {Left, Middle, Right}` -> `Sekai Trace Flick Note {Left, Middle, Right}` -> `Sekai Trace Note Red {Left, Middle, Right}` -> `NOTE_HEAD_RED`                                                                              |
| Critical Trace            | `Sekai Critical Trace Note Basic`       | Slim         | `Sekai Critical Trace Note {Left, Middle, Right}` -> `Sekai Trace Note Yellow {Left, Middle, Right}` -> `NOTE_HEAD_YELLOW`                                                                                                                            |
| Critical Trace Flick      | `Sekai Critical Trace Flick Note Basic` | Slim         | `Sekai Critical Trace Flick Note {Left, Middle, Right}` -> `Sekai Critical Trace Note {Left, Middle, Right}` -> `Sekai Trace Note Yellow {Left, Middle, Right}` -> `NOTE_HEAD_YELLOW`                                                                 |
| Critical Trace Down Flick | `Sekai Critical Trace Flick Note Basic` | Slim         | `Sekai Critical Trace Down Flick Note {Left, Middle, Right}` -> `Sekai Critical Trace Flick Note {Left, Middle, Right}` -> `Sekai Critical Trace Note {Left, Middle, Right}` -> `Sekai Trace Note Yellow {Left, Middle, Right}` -> `NOTE_HEAD_YELLOW` |
| Damage                    | `Sekai Damage Note Basic`               | Slim         | `Sekai Damage Note {Left, Middle, Right}` -> `Sekai Trace Note Purple {Left, Middle, Right}` -> `NOTE_HEAD_PURPLE`                                                                                                                                    |

#### Slide Tick Diamonds

| Tick Type                      | Precedence                                                                                                                                                                |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Normal Slide Tick              | `Sekai Normal Slide Diamond` -> `Sekai Diamond Green` -> `NOTE_TICK_GREEN`                                                                                                |
| Critical Slide Tick            | `Sekai Critical Slide Diamond` -> `Sekai Diamond Yellow` -> `NOTE_TICK_YELLOW`                                                                                            |
| Trace Tick (Green)             | `Sekai Normal Trace Diamond` -> `Sekai Trace Diamond Green` -> `NOTE_TICK_GREEN`                                                                                          |
| Trace Flick Tick               | `Sekai Trace Flick Diamond` -> `Sekai Trace Diamond Red` -> `NOTE_TICK_RED`                                                                                               |
| Trace Down Flick Tick          | `Sekai Trace Down Flick Diamond` -> `Sekai Trace Flick Diamond` -> `Sekai Trace Diamond Red` -> `NOTE_TICK_RED`                                                           |
| Critical Trace Tick            | `Sekai Critical Trace Diamond` -> `Sekai Trace Diamond Yellow` -> `NOTE_TICK_YELLOW`                                                                                      |
| Critical Trace Flick Tick      | `Sekai Critical Trace Flick Diamond` -> `Sekai Critical Trace Diamond` -> `Sekai Trace Diamond Yellow` -> `NOTE_TICK_YELLOW`                                              |
| Critical Trace Down Flick Tick | `Sekai Critical Trace Down Flick Diamond` -> `Sekai Critical Trace Flick Diamond` -> `Sekai Critical Trace Diamond` -> `Sekai Trace Diamond Yellow` -> `NOTE_TICK_YELLOW` |

#### Active Slide Connectors

| Connector | Precedence                                                                                                                                                |
| --------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Normal    | `Sekai Normal Active Slide Connection {Normal, Active}` -> `Sekai Active Slide Connection {Green, Green Active}` -> `NOTE_CONNECTION_GREEN_SEAMLESS`      |
| Critical  | `Sekai Critical Active Slide Connection {Normal, Active}` -> `Sekai Active Slide Connection {Yellow, Yellow Active}` -> `NOTE_CONNECTION_YELLOW_SEAMLESS` |

#### Slots & Slot Glows

| Note Type               | Slot Precedence                                                                                                                              | Slot Glow Precedence                                                                                                                                                  |
| ----------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Tap                     | `Sekai Slot Normal` -> `Sekai Slot Cyan`                                                                                                     | `Sekai Slot Glow Normal` -> `Sekai Slot Glow Cyan`                                                                                                                    |
| Slide                   | `Sekai Slot Slide` -> `Sekai Slot Green`                                                                                                     | `Sekai Slot Glow Slide` -> `Sekai Slot Glow Green`                                                                                                                    |
| Flick                   | `Sekai Slot Flick` -> `Sekai Slot Red`                                                                                                       | `Sekai Slot Glow Flick` -> `Sekai Slot Glow Red`                                                                                                                      |
| Down Flick              | `Sekai Slot Down Flick` -> `Sekai Slot Flick` -> `Sekai Slot Red`                                                                            | `Sekai Slot Glow Down Flick` -> `Sekai Slot Glow Flick` -> `Sekai Slot Glow Red`                                                                                      |
| Critical                | `Sekai Slot Critical` -> `Sekai Slot Yellow`                                                                                                 | `Sekai Slot Glow Critical` -> `Sekai Slot Glow Yellow`                                                                                                                |
| Critical Slide          | `Sekai Slot Critical Slide` -> `Sekai Slot Yellow Slider` -> `Sekai Slot Critical` -> `Sekai Slot Yellow`                                    | `Sekai Slot Glow Critical Slide` -> `Sekai Slot Glow Yellow Slider Tap` -> `Sekai Slot Glow Critical` -> `Sekai Slot Glow Yellow`                                     |
| Critical Flick          | `Sekai Slot Critical Flick` -> `Sekai Slot Yellow Flick` -> `Sekai Slot Critical` -> `Sekai Slot Yellow`                                     | `Sekai Slot Glow Critical Flick` -> `Sekai Slot Glow Yellow Flick` -> `Sekai Slot Glow Critical` -> `Sekai Slot Glow Yellow`                                          |
| Critical Down Flick     | `Sekai Slot Critical Down Flick` -> `Sekai Slot Critical Flick` -> `Sekai Slot Yellow Flick` -> `Sekai Slot Critical` -> `Sekai Slot Yellow` | `Sekai Slot Glow Critical Down Flick` -> `Sekai Slot Glow Critical Flick` -> `Sekai Slot Glow Yellow Flick` -> `Sekai Slot Glow Critical` -> `Sekai Slot Glow Yellow` |
| Active Slide (Normal)   | --                                                                                                                                           | `Sekai Normal Slide Slot Glow` -> `Sekai Slot Glow Slide` -> `Sekai Slot Glow Green`                                                                                  |
| Active Slide (Critical) | --                                                                                                                                           | `Sekai Critical Slide Slot Glow` -> `Sekai Slot Glow Critical Slide` -> `Sekai Slot Glow Yellow Slider Tap` -> `Sekai Slot Glow Critical` -> `Sekai Slot Glow Yellow` |

| Connector   | Sprite                               |
| ----------- | ------------------------------------ |
| Green Hold  | `Sekai Slot Glow Green Slider Hold`  |
| Yellow Hold | `Sekai Slot Glow Yellow Slider Hold` |

#### Flick Arrows

| Note Family                                                                             | Precedence                                                                                                                                                            |
| --------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Flick / Down Flick / Trace Flick / Trace Down Flick                                     | `Sekai Flick Arrow {Up, Up Left, Down, Down Left} {1..6}` -> `Sekai Flick Arrow Red {Up, Up Left, Down, Down Left} {1..6}` -> `DIRECTIONAL_MARKER_RED`                |
| Critical Flick / Critical Down Flick / Critical Trace Flick / Critical Trace Down Flick | `Sekai Critical Flick Arrow {Up, Up Left, Down, Down Left} {1..6}` -> `Sekai Flick Arrow Yellow {Up, Up Left, Down, Down Left} {1..6}` -> `DIRECTIONAL_MARKER_YELLOW` |

#### Guides

| Color   | Precedence                                                  |
| ------- | ----------------------------------------------------------- |
| Green   | `Sekai Guide Green` -> `NOTE_CONNECTION_GREEN_SEAMLESS`     |
| Yellow  | `Sekai Guide Yellow` -> `NOTE_CONNECTION_YELLOW_SEAMLESS`   |
| Red     | `Sekai Guide Red` -> `NOTE_CONNECTION_RED_SEAMLESS`         |
| Purple  | `Sekai Guide Purple` -> `NOTE_CONNECTION_PURPLE_SEAMLESS`   |
| Cyan    | `Sekai Guide Cyan` -> `NOTE_CONNECTION_CYAN_SEAMLESS`       |
| Blue    | `Sekai Guide Blue` -> `NOTE_CONNECTION_BLUE_SEAMLESS`       |
| Neutral | `Sekai Guide Neutral` -> `NOTE_CONNECTION_NEUTRAL_SEAMLESS` |
| Black   | `Sekai Guide Black` -> `NOTE_CONNECTION_NEUTRAL_SEAMLESS`   |

#### UI & Custom Elements

| Role              | Sprite                                                                                                                                                                                                                          |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Judgments         | `Judge {Perfect, Great, Good, Bad, Miss, Auto}`                                                                                                                                                                                 |
| Combo Numbers     | `Combo Number {0..11}` (optional; falls back to `UI Number` glyphs when absent, in which case AP/glow combo effects are disabled), `Combo Number Glow {0..11}`                                                                   |
| Combo Labels      | `Combo Label`, `Combo Label Glow`                                                                                                                                                                                               |
| AP Combo          | `AP Combo Number {0..11}`, `AP Combo Label`                                                                                                                                                                                     |
| UI & Life Numbers | `UI Number {0..17}` (`0`-`9` digits, `10` = alt-color `0`, `11` = `+`, `12` = `-`, `13` = `l`, `14` = `v`, `15` = `.`, `16` = `%`, `17` = seconds suffix), `Life Number {0..9}`                                                     |
| Accuracy Warnings | `Judge {Fast, Late, Flick} Warning`                                                                                                                                                                                             |
| Gameplay Effects  | `Damage Flash`, `Dead Effect`, `Auto Live`                                                                                                                                                                                      |
| Life Bar          | `Life Bar Pause`, `Life Bar Skip`, `Life Bar Disable`, `Life Bar Normal Background`, `Life Bar Danger Background`, `Life Bar Gauge Normal`, `Life Bar Gauge Danger`, `Life Bar Gauge Normal Edge`, `Life Bar Gauge Danger Edge` |
| Score Bar         | `Score Bar`, `Score Bar Panel`, `Score Bar Gauge`, `Score Bar Mask`, `Score Bar Cover`                                                                                                                                          |
| Score Rank        | `Score Rank {S, A, B, C, D}`, `Score Rank Text {S, A, B, C, D}`                                                                                                                                                                 |
| Skill System      | `Skill Bar Life`, `Skill Bar Score`, `Skill Bar Judgment`, `Skill Number {0..17}` (optional; same glyph layout as `UI Number`, used in preference when present, otherwise falls back to `UI Number`), `Skill Icon {1..5}`, `Skill Judgment Line` |

#### Damage Slide Connectors

| Connector        | Precedence                                                                |
|------------------|---------------------------------------------------------------------------|
| Damage           | `Sekai Damage Slide Connection` -> `NOTE_CONNECTION_PURPLE_SEAMLESS`      |
| Damage (Touched) | `Sekai Damage Slide Connection Active` -> `NOTE_CONNECTION_RED_SEAMLESS`  |

### Effect Clips

| Name                   |
| ---------------------- |
| `Sekai Tick`           |
| `Sekai Critical Tap`   |
| `Sekai Critical Flick` |
| `Sekai Critical Hold`  |
| `Sekai Critical Tick`  |
| `Sekai Trace`          |
| `Sekai Critical Trace` |
| `Sekai Skill`          |

### Particle Effects

| Name                                          |
| --------------------------------------------- |
| `Sekai Note Lane Linear`                      |
| `Sekai Slide Lane Linear`                     |
| `Sekai Flick Lane Linear`                     |
| `Sekai Down Flick Lane Linear`                |
| `Sekai Critical Lane Linear`                  |
| `Sekai Critical Slide Lane Linear`            |
| `Sekai Critical Flick Lane Linear`            |
| `Sekai Critical Down Flick Lane Linear`       |
| `Sekai Circular Tap Cyan Great`               |
| `Sekai Circular Tap Cyan Good`                |
| `Sekai Linear Tap Cyan Great`                 |
| `Sekai Linear Tap Cyan Good`                  |
| `Sekai Slot Linear Tap Cyan`                  |
| `Sekai Slot Linear Tap Cyan Great`            |
| `Sekai Slot Linear Tap Cyan Good`             |
| `Sekai Slot Linear Tap Green`                 |
| `Sekai Slot Linear Alternative Red`           |
| `Sekai Trace Note Circular Green`             |
| `Sekai Trace Note Linear Green`               |
| `Sekai Slot Linear Tap Yellow`                |
| `Sekai Critical Slide Circular Yellow`        |
| `Sekai Critical Slide Linear Yellow`          |
| `Sekai Slot Linear Slide Tap Yellow`          |
| `Sekai Critical Flick Circular Yellow`        |
| `Sekai Critical Flick Linear Yellow`          |
| `Sekai Slot Linear Alternative Yellow`        |
| `Sekai Trace Note Circular Yellow`            |
| `Sekai Trace Note Linear Yellow`              |
| `Sekai Normal Slide Trail Linear`             |
| `Sekai Slot Linear Slide Green`               |
| `Sekai Critical Slide Trail Linear`           |
| `Sekai Slot Linear Slide Yellow`              |
| `Sekai Normal Note Circular`                  |
| `Sekai Normal Note Linear`                    |
| `Sekai Normal Note Slot Linear`               |
| `Sekai Slide Note Circular`                   |
| `Sekai Slide Note Linear`                     |
| `Sekai Slide Note Slot Linear`                |
| `Sekai Flick Note Circular`                   |
| `Sekai Flick Note Linear`                     |
| `Sekai Flick Note Slot Linear`                |
| `Sekai Flick Note Directional`                |
| `Sekai Down Flick Note Circular`              |
| `Sekai Down Flick Note Linear`                |
| `Sekai Down Flick Note Slot Linear`           |
| `Sekai Down Flick Note Directional`           |
| `Sekai Trace Note Circular`                   |
| `Sekai Trace Note Linear`                     |
| `Sekai Critical Note Circular`                |
| `Sekai Critical Note Linear`                  |
| `Sekai Critical Note Slot Linear`             |
| `Sekai Critical Slide Note Circular`          |
| `Sekai Critical Slide Note Linear`            |
| `Sekai Critical Slide Note Slot Linear`       |
| `Sekai Critical Flick Note Circular`          |
| `Sekai Critical Flick Note Linear`            |
| `Sekai Critical Flick Note Slot Linear`       |
| `Sekai Critical Note Directional`             |
| `Sekai Critical Down Flick Note Circular`     |
| `Sekai Critical Down Flick Note Linear`       |
| `Sekai Critical Down Flick Note Slot Linear`  |
| `Sekai Critical Down Flick Note Directional`  |
| `Sekai Critical Trace Note Circular`          |
| `Sekai Critical Trace Note Linear`            |
| `Sekai Normal Slide Tick Note`                |
| `Sekai Critical Slide Tick Note`              |
| `Sekai Normal Slide Connector Circular`       |
| `Sekai Normal Slide Connector Linear`         |
| `Sekai Normal Slide Connector Trail Linear`   |
| `Sekai Normal Slide Connector Slot Linear`    |
| `Sekai Critical Slide Connector Circular`     |
| `Sekai Critical Slide Connector Linear`       |
| `Sekai Critical Slide Connector Trail Linear` |
| `Sekai Critical Slide Connector Slot Linear`  |
| `Sekai Damage Note Circular`                  |
| `Sekai Damage Note Linear`                    |
| `Sekai Fever Chance Text`                     |
| `Sekai Fever Chance Lane`                     |
| `Sekai Fever Text`                            |
| `Sekai Fever Lane`                            |
| `Sekai Super Fever Text`                      |
| `Sekai Super Fever Lane`                      |
| `Sekai Super Fever Effect`                    |
| `Sekai Fever Border`                          |
