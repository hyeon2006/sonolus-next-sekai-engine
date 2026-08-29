from enum import IntEnum

from sonolus.script.options import OptionCategory, select_option, slider_option, toggle_option
from sonolus.script.text import StandardText

from sekai.lib.localization import localized_options


class ScoreMode(IntEnum):
    WEIGHTED_FLAT = 0
    WEIGHTED_COMBO = 1
    UNWEIGHTED_FLAT = 2
    UNWEIGHTED_COMBO = 3


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


@localized_options
class Options:
    gameplay = OptionCategory(title=StandardText.GAMEPLAY)
    graphics = OptionCategory(title=StandardText.GRAPHICS)
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
    note_speed: float = slider_option(
        name=StandardText.NOTE_SPEED,
        category=gameplay,
        scope="Sekai",
        default=6,
        min=1,
        max=12,
        step=0.01,
    )
    mirror: bool = toggle_option(
        name=StandardText.MIRROR,
        category=gameplay,
        default=False,
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
    sim_line_enabled: bool = toggle_option(
        name=StandardText.SIMLINE,
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
        default=0,
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
    hide_ui: bool = toggle_option(
        name="Hide UI",
        category=graphics,
        scope="Sekai",
        default=False,
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
    score_mode: ScoreMode = select_option(
        name="Score Mode",
        category=gameplay,
        scope="Sekai",
        values=[
            "weighted_flat",
            "weighted_combo",
            "unweighted_flat",
            "unweighted_combo",
        ],
        standard=True,
        advanced=True,
        default=1,
    )
    show_hitboxes: bool = toggle_option(
        name="Show Hitboxes",
        category=miscellaneous,
        advanced=True,
        scope="Next Sekai",
        default=False,
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
    )
