from enum import IntEnum

from sonolus.script.options import OptionCategory, select_option, slider_option, toggle_option
from sonolus.script.text import StandardText

from sekai.lib.localization import localized_options


class ScoreMode(IntEnum):
    WEIGHTED_FLAT = 0
    WEIGHTED_COMBO = 1
    UNWEIGHTED_FLAT = 2
    UNWEIGHTED_COMBO = 3


class GaugeMode(IntEnum):
    STANDARD = 0
    HEAVY = 1
    ULTIMA = 2


class StageCoverMode(IntEnum):
    STAGE = 0
    STAGE_AND_LINE = 1
    FULL_WIDTH = 2


class StageCoverNoteSpeedCompensation(IntEnum):
    OFF = 0
    FIXED_ONLY = 1
    FULL = 2


class VibrateMode(IntEnum):
    DISABLED = 0
    MISS = 1
    MISS_AND_GOOD = 2


class HitboxMode(IntEnum):
    ANGLED = 0
    VERTICAL = 1


class HitboxRange(IntEnum):
    DEFAULT = 0
    FULL_VERTICAL = 1
    FULL_ADAPTIVE = 2


class SkillMode(IntEnum):
    LEVEL_DEFAULT = 0
    SCORE = 1
    HEAL = 2
    JUDGMENT = 3
    HIDE_COMBO = 4
    HIDE_PRIMARY_METRIC = 5
    HIDE_SECONDARY_METRIC = 6
    HIDE_JUDGMENT = 7

    @classmethod
    def from_options(cls, option_val: int, legacy_val: int) -> "SkillMode":
        option_map = {1: cls.SCORE, 2: cls.HEAL, 3: cls.JUDGMENT}
        legacy_map = {
            1: cls.HEAL,
            2: cls.JUDGMENT,
            3: cls.HIDE_COMBO,
            4: cls.HIDE_PRIMARY_METRIC,
            5: cls.HIDE_SECONDARY_METRIC,
            6: cls.HIDE_JUDGMENT,
        }

        return option_map.get(option_val, legacy_map.get(legacy_val, cls.SCORE))


class Version(IntEnum):
    v3 = 0
    v1 = 1


class PreviewDisplayMode(IntEnum):
    EDITOR = 0
    INGAME = 1


@localized_options
class Options:
    kizu = OptionCategory(title="kizu")
    gameplay = OptionCategory(title=StandardText.GAMEPLAY)
    graphics = OptionCategory(title=StandardText.GRAPHICS)
    ui = OptionCategory(title=StandardText.UI)
    audio = OptionCategory(title=StandardText.AUDIO)
    miscellaneous = OptionCategory(title=StandardText.MISCELLANEOUS)

    speed: float = slider_option(
        name=StandardText.SPEED,
        category=gameplay,
        standard=True,
        advanced=True,
        default=1,
        min=0.5,
        max=2,
        step=0.05,
        unit=StandardText.PERCENTAGE_UNIT,
    )
    gauge: GaugeMode = select_option(
        name="Gauge",
        category=kizu,
        standard=True,
        scope="Rush",
        default=GaugeMode.STANDARD,
        values=[
            "standard",
            "heavy",
            "ultima",
        ],
    )
    note_speed: float = slider_option(
        name=StandardText.NOTE_SPEED,
        category=gameplay,
        scope="Sekai",
        default=6,
        min=1,
        max=12,
        step=0.01,
    )
    stage_cover: float = slider_option(
        name=StandardText.STAGE_COVER_VERTICAL,
        category=graphics,
        advanced=True,
        scope="Sekai",
        default=0,
        min=0,
        max=1,
        step=0.01,
        unit=StandardText.PERCENTAGE_UNIT,
    )
    slide_alpha: float = slider_option(
        name="Slide Alpha",
        category=graphics,
        scope="Sekai",
        default=1,
        min=0,
        max=1,
        step=0.05,
        unit=StandardText.PERCENTAGE_UNIT,
    )
    guide_alpha: float = slider_option(
        name="Guide Alpha",
        category=graphics,
        scope="Sekai",
        default=0.6,
        min=0,
        max=1,
        step=0.05,
        unit=StandardText.PERCENTAGE_UNIT,
    )
    background_alpha: float = slider_option(
        name=StandardText.STAGE_ALPHA,
        category=graphics,
        scope="Sekai",
        default=1,
        min=0.5,
        max=1,
        step=0.1,
        unit=StandardText.PERCENTAGE_UNIT,
    )
    lane_alpha: float = slider_option(
        name=StandardText.LANE_ALPHA,
        category=graphics,
        scope="Sekai",
        default=1,
        min=0,
        max=1,
        step=0.1,
        unit=StandardText.PERCENTAGE_UNIT,
    )
    fever_effect: int = select_option(
        name="Fever Effect",
        category=graphics,
        scope="Rush",
        default=0,
        values=["default", "lightweight", "none"],
    )
    skill_effect: bool = toggle_option(
        name="Skill Effect",
        category=graphics,
        scope="Rush",
        default=True,
    )
    sim_line_enabled: bool = toggle_option(
        name=StandardText.SIMLINE,
        category=graphics,
        scope="Sekai",
        default=True,
    )
    ap_effect: bool = toggle_option(
        name="AP Effect",
        category=graphics,
        scope="Rush",
        default=True,
    )
    custom_accuracy: bool = toggle_option(
        name="Late/Fast/Flick",
        category=ui,
        scope="Rush",
        default=False,
    )
    mirror: bool = toggle_option(
        name=StandardText.MIRROR,
        category=gameplay,
        default=False,
    )
    custom_combo: bool = toggle_option(
        name="Custom Combo",
        category=ui,
        scope="Rush",
        default=True,
    )
    custom_score: int = select_option(
        name="Custom Score Indicator",
        category=ui,
        scope="Rush",
        default=0,
        values=["disable", "arcade_positive", "arcade_negative", "accuracy"],
    )
    custom_judgment: bool = toggle_option(
        name="Custom Judgment",
        category=ui,
        scope="Rush",
        default=True,
    )
    auto_judgment: bool = toggle_option(
        name="Auto Judgment Display",
        category=ui,
        scope="Rush",
        default=True,
    )
    custom_damage: bool = toggle_option(
        name="Custom Damage Effect",
        category=graphics,
        scope="Rush",
        default=True,
    )
    custom_life_bar: bool = toggle_option(
        name="Custom Life Bar",
        category=ui,
        scope="Rush",
        default=True,
    )
    custom_score_bar: bool = toggle_option(
        name="Custom Score Bar",
        category=ui,
        scope="Rush",
        default=True,
    )
    custom_tag: bool = toggle_option(
        name="Custom Tag",
        category=ui,
        scope="Rush",
        default=True,
    )
    ui_intro: bool = toggle_option(
        name="UI Intro Effect",
        category=ui,
        scope="Rush",
        default=True,
    )
    note_perspective: float = slider_option(
        name="Note Perspective",
        category=graphics,
        scope="Rush",
        default=1,
        min=0,
        max=1,
        step=0.1,
    )
    sfx_enabled: bool = toggle_option(
        name=StandardText.EFFECT,
        category=audio,
        scope="Sekai",
        default=True,
    )
    auto_sfx: bool = toggle_option(
        name=StandardText.EFFECT_AUTO,
        category=audio,
        scope="Sekai",
        default=False,
    )
    prevent_empty_lane_sfx: bool = toggle_option(
        name="Prevent Empty Lane Effect Overwrite",
        category=audio,
        scope="Rush",
        default=False,
    )
    tap_haptics_enabled: bool = toggle_option(
        name=StandardText.HAPTIC,
        category=gameplay,
        scope="Sekai",
        default=False,
    )
    vibrate_mode: VibrateMode = select_option(
        name="Vibration Mode",
        category=gameplay,
        scope="Sekai",
        values=[
            "disabled",
            "miss",
            "miss_and_good",
        ],
        default=0,
    )
    note_effect_enabled: bool = toggle_option(
        name=StandardText.NOTE_EFFECT,
        category=graphics,
        scope="Sekai",
        default=True,
    )
    note_effect_size: float = slider_option(
        name=StandardText.NOTE_EFFECT_SIZE,
        category=graphics,
        scope="Sekai",
        default=1,
        min=0.1,
        max=2,
        step=0.05,
        unit=StandardText.PERCENTAGE_UNIT,
    )
    marker_animation: bool = toggle_option(
        name=StandardText.MARKER_ANIMATION,
        category=graphics,
        scope="Sekai",
        default=True,
    )
    connector_animation: bool = toggle_option(
        name=StandardText.CONNECTOR_ANIMATION,
        category=graphics,
        scope="Sekai",
        default=True,
    )
    lane_effect_enabled: bool = toggle_option(
        name=StandardText.LANE_EFFECT,
        category=graphics,
        scope="Sekai",
        default=True,
    )
    slot_effect_enabled: bool = toggle_option(
        name=StandardText.SLOT_EFFECT,
        category=graphics,
        scope="Sekai",
        default=True,
    )
    slot_effect_size: float = slider_option(
        name=StandardText.SLOT_EFFECT_SIZE,
        category=graphics,
        scope="Sekai",
        default=1,
        min=0,
        max=2,
        step=0.05,
        unit=StandardText.PERCENTAGE_UNIT,
    )
    stage_cover_mode: StageCoverMode = select_option(
        name="Stage Cover Mode",
        category=graphics,
        advanced=True,
        scope="Sekai",
        values=[
            "stage",
            "stage_and_line",
            "full_width",
        ],
        default=1,
    )
    stage_cover_alpha: float = slider_option(
        name=StandardText.STAGE_COVER_ALPHA,
        category=graphics,
        advanced=True,
        scope="Sekai",
        default=1,
        min=0,
        max=1,
        step=0.01,
        unit=StandardText.PERCENTAGE_UNIT,
    )
    stage_cover_scroll_speed_compensation: StageCoverNoteSpeedCompensation = select_option(
        name="Stage Cover Note Speed Compensation",
        category=graphics,
        advanced=True,
        scope="Sekai",
        values=[
            "off",
            "fixed_only",
            "full",
        ],
        default=1,
    )
    hidden: float = slider_option(
        name=StandardText.HIDDEN,
        category=graphics,
        scope="Sekai",
        advanced=True,
        default=0,
        min=0,
        max=1,
        step=0.01,
        unit=StandardText.PERCENTAGE_UNIT,
    )
    lock_stage_aspect_ratio: bool = toggle_option(
        name=StandardText.STAGE_ASPECTRATIO_LOCK,
        category=graphics,
        scope="Sekai",
        default=True,
    )
    hide_ui: int = select_option(
        name="Hide UI",
        category=ui,
        scope="Rush",
        default=0,
        values=["none", "sonolus", "sonolus_and_custom_judgment", "all"],
    )
    show_lane: bool = toggle_option(
        name=StandardText.STAGE,
        category=graphics,
        scope="Sekai",
        default=True,
    )
    slide_quality: float = slider_option(
        name="Slide Quality",
        category=graphics,
        scope="Next Sekai",
        default=1,
        min=0.5,
        max=2,
        step=0.1,
        unit=StandardText.PERCENTAGE_UNIT,
    )
    guide_quality: float = slider_option(
        name="Guide Quality",
        category=graphics,
        scope="Next Sekai",
        default=1,
        min=0.5,
        max=2,
        step=0.1,
        unit=StandardText.PERCENTAGE_UNIT,
    )
    note_margin: float = slider_option(
        name="Note Margin",
        category=graphics,
        scope="Next Sekai",
        default=0.0,
        min=0.0,
        max=0.2,
        step=0.01,
    )
    preview_display_mode: PreviewDisplayMode = select_option(
        name="Preview Display Mode",
        category=graphics,
        scope="Rush",
        values=[
            "editor",
            "ingame",
        ],
        default=PreviewDisplayMode.EDITOR,
    )
    effect_animation_speed: float = slider_option(
        name="Effect Animation Speed",
        category=graphics,
        scope="Next Sekai",
        default=1,
        min=0.25,
        max=4,
        step=0.05,
        unit=StandardText.PERCENTAGE_UNIT,
    )
    alternative_approach_curve: bool = toggle_option(
        name="Alternative Approach Curve",
        category=gameplay,
        advanced=True,
        default=False,
        scope="Next Sekai",
    )
    disable_timescale: bool = toggle_option(
        name="Disable Timescale",
        category=gameplay,
        standard=True,
        advanced=True,
        default=False,
    )
    disable_fake_notes: bool = toggle_option(
        name="Disable Fake Notes",
        category=gameplay,
        standard=True,
        advanced=True,
        default=False,
    )
    forced_fever_chance: bool = toggle_option(
        name="Forced Fever Chance",
        category=gameplay,
        scope="Rush",
        default=False,
    )
    edge_touch_correction: bool = toggle_option(
        name="Edge Touch Correction",
        category=gameplay,
        scope="Next Sekai",
        default=True,
    )
    show_hitboxes: bool = toggle_option(
        name="Show Hitboxes",
        category=miscellaneous,
        advanced=True,
        scope="Next Sekai",
        default=False,
    )
    background_auto_correction: bool = toggle_option(
        name="Background Auto Correction",
        category=graphics,
        scope="Rush",
        advanced=True,
        default=False,
    )
    hitbox_range: HitboxRange = select_option(
        name="Hitbox",
        category=gameplay,
        advanced=True,
        scope="Rush",
        values=[
            "default",
            "full_vertical",
            "full_adaptive",
        ],
        default=HitboxRange.DEFAULT,
    )
    test_aspect_ratio: bool = toggle_option(
        name="Test Aspect Ratio",
        category=miscellaneous,
        advanced=True,
        scope="Next Sekai",
        default=False,
    )
    allow_debug_options_in_play_mode: bool = toggle_option(
        name="Allow Debug Options in Play Mode",
        category=miscellaneous,
        standard=True,
        advanced=True,
        default=False,
    )

    replay_fallback_option_names = (
        StandardText.SPEED,
        StandardText.NOTE_SPEED,
        StandardText.MIRROR,
        StandardText.EFFECT,
        StandardText.EFFECT_AUTO,
        "Effect Animation Speed",
        StandardText.NOTE_EFFECT,
        StandardText.NOTE_EFFECT_SIZE,
        StandardText.MARKER_ANIMATION,
        StandardText.SIMLINE,
        StandardText.CONNECTOR_ANIMATION,
        "Slide Alpha",
        "Guide Alpha",
        StandardText.LANE_EFFECT,
        StandardText.SLOT_EFFECT,
        StandardText.SLOT_EFFECT_SIZE,
        StandardText.STAGE_COVER_VERTICAL,
        StandardText.HIDDEN,
        StandardText.STAGE_ASPECTRATIO_LOCK,
        "Hide UI",
        StandardText.STAGE,
        "Slide Quality",
        "Guide Quality",
        "Note Margin",
        "Alternative Approach Curve",
        "Disable Timescale",
        StandardText.VERSION,
        "Custom Combo",
        "Custom Combo Number Distance",
        "Ap Effect",
        "Combo Judgment",
        "Late/Fast/Flick",
        "Auto Judgment",
        "Custom Damage Effect",
        "Custom Tag",
        StandardText.STAGE_ALPHA,
        StandardText.LANE_ALPHA,
        "Fever Effect",
        "Forced Fever Chance",
        "Skill Effect",
    )
