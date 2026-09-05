import math

from sekai.level_utils import (
    LevelBpmChange,
    LevelNote,
    LevelSlide,
    LevelStage,
    LevelStageMaskChange,
    LevelStagePivotChange,
    LevelStageStyleChange,
    LevelStageTransformChange,
    build_level,
)
from sekai.lib.connector import ConnectorKind
from sekai.lib.ease import EaseType
from sekai.lib.layout import (
    FIELD_B_FACTOR,
    FIELD_T_FACTOR,
    FIELD_W_FACTOR,
    TARGET_ASPECT_RATIO,
    StageTransformAnchor,
)
from sekai.lib.note import NoteKind
from sekai.lib.stage import DivisionParity, JudgeLineColor, StageBorderStyle

NUM_STAGES = 7
STAGE_HALF_WIDTH = 1.0  # mask size 1 -> each stage is 2 lanes wide

# Distance from the judge line up to the perspective vanishing point, in judge-line lane widths, at
# stage tilt 1 with the default camera. The aspect terms cancel because this level always has stage
# transforms, which force the field to TARGET_ASPECT_RATIO. This level never changes the camera, so
# tilt stays 1 throughout and one judge-line lane width is exactly w_scale.
VANISH_DIST = (FIELD_T_FACTOR - FIELD_B_FACTOR) / (TARGET_ASPECT_RATIO * FIELD_W_FACTOR)

# Each stage's judge line is a chord of a circle through the shared vanishing point hub, and each
# stage is rotated to point at that hub. Because the chord midpoints sit exactly VANISH_DIST from
# the hub (the same distance the untransformed stage's judge line sits from its vanishing point),
# every transformed wedge converges on the hub: adjacent side borders are collinear at every depth,
# so the stages join seamlessly both along the judge-line arc and toward the vanishing point.
# That constraint fixes the arc step: half a chord (1 lane) against the apothem (VANISH_DIST).
ARC_STEP = 2 * math.atan(STAGE_HALF_WIDTH / VANISH_DIST)

BPM = 60.0
SLIDE_BEATS_PER_STAGE = 0.25
LTR_SLIDE_START_BEAT = 2.0
RTL_SLIDE_START_BEAT = 9.0


def arc_angle(index: int) -> float:
    """Angle of the stage's chord midpoint around the hub, from straight down, CCW-positive."""
    return (index - (NUM_STAGES - 1) / 2) * ARC_STEP


def stage_is_visible(index: int) -> bool:
    """Alternating visibility across the fan, starting and ending visible: 1010101.

    The stages still tile the full arc as above, but the hidden ones draw nothing (lane and judge
    line alpha 0), so the visible result is 4 wedges separated by 3 gaps. The gaps expose each
    visible wedge's own edges, which the seamless arrangement otherwise hides. Hidden stages keep
    their masks, so the slides still route joints through them.
    """
    return index % 2 == 0


def arc_stage(index: int) -> LevelStage:
    # The stage's judge-line center moves to its chord midpoint on the circle around the hub, and
    # the stage rotates by that same CCW angle so its lanes keep pointing at the hub; the engine's
    # rotate field is CW-positive, hence the negation.
    angle = arc_angle(index)
    alpha = 1.0 if stage_is_visible(index) else 0.0
    return LevelStage(
        from_start=True,
        until_end=True,
        mask_changes=[
            LevelStageMaskChange(beat=0.0, lane=0.0, size=STAGE_HALF_WIDTH, ease=EaseType.LINEAR),
        ],
        pivot_changes=[
            LevelStagePivotChange(
                beat=0.0,
                lane=0.0,
                division_size=2.0,
                division_parity=DivisionParity.ODD,
                abs_y_offset=0.0,
                y_beat_offset=0.0,
                ease=EaseType.LINEAR,
            ),
        ],
        style_changes=[
            LevelStageStyleChange(
                beat=0.0,
                judge_line_color=JudgeLineColor.PURPLE,
                left_border_style=StageBorderStyle.DEFAULT,
                right_border_style=StageBorderStyle.DEFAULT,
                lane_alpha=alpha,
                judge_line_alpha=alpha,
                ease=EaseType.LINEAR,
            ),
        ],
        transform_changes=[
            LevelStageTransformChange(
                beat=0.0,
                rotate=-math.degrees(angle),
                x_lane_translate=VANISH_DIST * math.sin(angle),
                y_lane_translate=VANISH_DIST * (1 - math.cos(angle)),
                anchor=StageTransformAnchor.DEFAULT,
                ease=EaseType.LINEAR,
            ),
        ],
    )


arc_stages = [arc_stage(i) for i in range(NUM_STAGES)]


def sweep_slide(start_beat: float, stage_order: list[LevelStage]) -> LevelSlide:
    """A hold sweeping across the stages, one joint per stage: tap head, tick joints, release tail."""
    last = len(stage_order) - 1
    slide = LevelSlide()
    slide.notes = [
        LevelNote(
            beat=start_beat + i * SLIDE_BEATS_PER_STAGE,
            lane=0.0,
            size=1.0,
            kind=NoteKind.NORM_HEAD_TAP if i == 0 else NoteKind.NORM_TAIL_RELEASE if i == last else NoteKind.NORM_TICK,
            stage=stage,
            segment_kind=ConnectorKind.ACTIVE_NORMAL,
            connector_ease=EaseType.LINEAR,
        )
        for i, stage in enumerate(stage_order)
    ]
    return slide


ltr_slide = sweep_slide(LTR_SLIDE_START_BEAT, arc_stages)
rtl_slide = sweep_slide(RTL_SLIDE_START_BEAT, arc_stages[::-1])

# Nonlinear transform parity: at the raw midpoint the IN_QUAD connector is one quarter of the way
# between the outer stage transforms. The attached tick and active connector hitbox must coincide.
nonlinear_transform_slide = LevelSlide(
    notes=[
        LevelNote(
            beat=5.0,
            lane=0.0,
            size=1.0,
            kind=NoteKind.NORM_HEAD_TAP,
            stage=arc_stages[0],
            segment_kind=ConnectorKind.ACTIVE_NORMAL,
            connector_ease=EaseType.IN_QUAD,
        ),
        LevelNote(
            beat=7.0,
            lane=0.0,
            size=1.0,
            kind=NoteKind.NORM_TAIL_RELEASE,
            stage=arc_stages[-1],
        ),
    ]
)
nonlinear_transform_tick = LevelNote(
    beat=6.0,
    lane=0.0,
    size=0.0,
    kind=NoteKind.NORM_TICK,
    attach=nonlinear_transform_slide,
)
nonlinear_transform_slide.notes.insert(1, nonlinear_transform_tick)

entities = [
    LevelBpmChange(beat=0.0, bpm=BPM),
    *arc_stages,
    ltr_slide,
    nonlinear_transform_slide,
    rtl_slide,
]

level = build_level(
    name="arc-test",
    title="Arc Test",
    bgm=None,
    entities=entities,
)
