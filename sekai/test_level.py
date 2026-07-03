from sekai.level_utils import (
    LevelBpmChange,
    LevelCameraChange,
    LevelFeverChance,
    LevelFeverStart,
    LevelNote,
    LevelSkill,
    LevelSlide,
    LevelStage,
    LevelStageMaskChange,
    LevelStagePivotChange,
    LevelStageStyleChange,
    LevelStageTransformChange,
    build_level,
)
from sekai.lib.connector import ConnectorKind, ConnectorLayer, SegmentPresentation
from sekai.lib.ease import EaseType
from sekai.lib.layout import StageTransformAnchor
from sekai.lib.note import NoteKind
from sekai.lib.stage import DivisionParity, JudgeLineColor, JudgeLineStyle, StageBorderStyle

SLIDE_START_BEAT = 4.0
SLIDE_END_BEAT = 20.0
NUM_REGULAR_TICKS = 33  # head + 31 ticks + tail (~2 non-attached ticks/sec at BPM 60)
ATTACHED_PER_GAP = 3  # ~6 attached ticks/sec at BPM 60

STAGE_B_HALF_PERIOD_BEATS = 1.0  # 2-beat full back-and-forth = 2 seconds at BPM 60
STAGE_B_LANES = (-2.0, 2.0)  # right swing pulled in to leave room for the right-hand flick stage
STAGE_B_END_BEAT = SLIDE_END_BEAT + 4.0

RIGHT_FLICK_LANE = 5.0  # center of the right-hand flick stage (mask lanes 4..6)


def _stage_b_oscillation_beats() -> list[float]:
    beats: list[float] = []
    beat = 0.0
    while beat <= STAGE_B_END_BEAT + 1e-6:
        beats.append(beat)
        beat += STAGE_B_HALF_PERIOD_BEATS
    return beats


STAGE_A_LANE = -5.0
STAGE_A_Y_OFFSETS = (0.0, 0.8)  # alternate the left stage's y offset to exercise the judge line at an offset under tilt

# Reuse stage_b's oscillation cadence (one step per half-period) to alternate stage_a's y offset.
stage_a_pivot_changes = [
    LevelStagePivotChange(
        beat=beat,
        lane=STAGE_A_LANE,
        division_size=1.0,
        division_parity=DivisionParity.EVEN,
        abs_y_offset=STAGE_A_Y_OFFSETS[i % 2],
        y_beat_offset=0.0,
        ease=EaseType.IN_OUT_QUAD,
    )
    for i, beat in enumerate(_stage_b_oscillation_beats())
]

stage_a = LevelStage(
    from_start=True,
    until_end=True,
    mask_changes=[
        LevelStageMaskChange(beat=0.0, lane=STAGE_A_LANE, size=1.0, ease=EaseType.LINEAR),
    ],
    pivot_changes=stage_a_pivot_changes,
    style_changes=[
        LevelStageStyleChange(
            beat=0.0,
            judge_line_color=JudgeLineColor.GREEN,
            left_border_style=StageBorderStyle.DEFAULT,
            right_border_style=StageBorderStyle.DEFAULT,
            alpha=1.0,
            lane_alpha=1.0,
            judge_line_alpha=1.0,
            ease=EaseType.LINEAR,
        ),
    ],
)

stage_b_mask_changes = [
    LevelStageMaskChange(
        beat=beat,
        lane=STAGE_B_LANES[i % 2],
        size=2.0,
        ease=EaseType.IN_OUT_QUAD,
    )
    for i, beat in enumerate(_stage_b_oscillation_beats())
]

stage_b_pivot_changes = [
    LevelStagePivotChange(
        beat=beat,
        lane=STAGE_B_LANES[i % 2],
        division_size=1.0,
        division_parity=DivisionParity.EVEN,
        abs_y_offset=0.0,
        y_beat_offset=0.0,
        ease=EaseType.IN_OUT_QUAD,
    )
    for i, beat in enumerate(_stage_b_oscillation_beats())
]

# stage_b ramps division_line_alpha from full to faint so the lane dividers visibly fade out over the song
# (multiplicative with the lane's own alpha) without touching the judge line or borders.
stage_b = LevelStage(
    from_start=True,
    until_end=True,
    mask_changes=stage_b_mask_changes,
    pivot_changes=stage_b_pivot_changes,
    style_changes=[
        LevelStageStyleChange(
            beat=0.0,
            judge_line_color=JudgeLineColor.PURPLE,
            left_border_style=StageBorderStyle.DEFAULT,
            right_border_style=StageBorderStyle.DEFAULT,
            alpha=1.0,
            lane_alpha=1.0,
            judge_line_alpha=1.0,
            division_line_alpha=1.0,
            ease=EaseType.IN_OUT_QUAD,
        ),
        LevelStageStyleChange(
            beat=18.0,
            judge_line_color=JudgeLineColor.PURPLE,
            left_border_style=StageBorderStyle.DEFAULT,
            right_border_style=StageBorderStyle.DEFAULT,
            alpha=1.0,
            lane_alpha=1.0,
            judge_line_alpha=1.0,
            division_line_alpha=0.25,
            ease=EaseType.IN_OUT_QUAD,
        ),
    ],
    transform_changes=[
        LevelStageTransformChange(beat=0.0, ease=EaseType.IN_OUT_QUAD),
        LevelStageTransformChange(
            beat=8.0,
            rotate=12.0,
            x_lane_translate=0.4,
            y_lane_translate=0.7,
            anchor=StageTransformAnchor.CENTER,
            ease=EaseType.IN_OUT_QUAD,
        ),
        LevelStageTransformChange(beat=16.0, ease=EaseType.IN_OUT_QUAD),
    ],
)

# Tilt-only sweep (no zoom, rotation, or panning) so stage tilt can be inspected in isolation.
# Notes run over beats 4-20: classic perspective -> flat (held over beats 10-14) -> classic.
camera_changes = [
    LevelCameraChange(beat=0.0, stage_tilt=1.0, ease=EaseType.IN_OUT_QUAD),  # classic perspective
    LevelCameraChange(beat=4.0, stage_tilt=1.0, ease=EaseType.IN_OUT_QUAD),
    LevelCameraChange(beat=10.0, stage_tilt=0.4, ease=EaseType.IN_OUT_QUAD),  # flat: vertical lanes
    LevelCameraChange(beat=14.0, stage_tilt=0.4, ease=EaseType.IN_OUT_QUAD),  # hold flat for inspection
    LevelCameraChange(beat=20.0, stage_tilt=0.99, ease=EaseType.IN_OUT_QUAD),  # back to classic
]

regular_beats = [
    SLIDE_START_BEAT + i * (SLIDE_END_BEAT - SLIDE_START_BEAT) / (NUM_REGULAR_TICKS - 1)
    for i in range(NUM_REGULAR_TICKS)
]

slide = LevelSlide()
slide_notes: list[LevelNote] = []
attached_notes: list[LevelNote] = []

for i, beat in enumerate(regular_beats):
    is_first = i == 0
    is_last = i == NUM_REGULAR_TICKS - 1
    stage = stage_a if i % 2 == 0 else stage_b
    size = 1 if i % 2 == 0 else 2
    if is_first:
        kind = NoteKind.NORM_HEAD_TAP
    elif is_last:
        kind = NoteKind.NORM_TAIL_TAP
    else:
        kind = NoteKind.NORM_TICK
    slide_notes.append(
        LevelNote(
            beat=beat,
            lane=0.0,
            size=size,
            kind=kind,
            stage=stage,
            is_separator=is_first or is_last,
            segment_kind=ConnectorKind.ACTIVE_NORMAL,
            connector_ease=EaseType.IN_OUT_QUAD,
        )
    )
    if not is_last:
        next_beat = regular_beats[i + 1]
        for j in range(1, ATTACHED_PER_GAP + 1):
            frac = j / (ATTACHED_PER_GAP + 1)
            attached_notes.append(
                LevelNote(
                    beat=beat + frac * (next_beat - beat),
                    lane=0.0,
                    size=0.0,
                    kind=NoteKind.NORM_TICK,
                    stage=None,
                    attach=slide,
                )
            )

slide.notes = slide_notes


def _ease_in_out_quad(x: float) -> float:
    x = max(0.0, min(1.0, x))
    if x < 0.5:
        return 2 * x * x
    return 1 - 2 * (1 - x) ** 2


def _stage_b_pivot_at_beat(beat: float) -> float:
    pivot_beats = _stage_b_oscillation_beats()
    pivot_lanes = [STAGE_B_LANES[i % 2] for i in range(len(pivot_beats))]
    if beat <= pivot_beats[0]:
        return pivot_lanes[0]
    if beat >= pivot_beats[-1]:
        return pivot_lanes[-1]
    for i in range(len(pivot_beats) - 1):
        t_a = pivot_beats[i]
        t_b = pivot_beats[i + 1]
        if t_a <= beat <= t_b:
            frac = (beat - t_a) / (t_b - t_a)
            return pivot_lanes[i] + (pivot_lanes[i + 1] - pivot_lanes[i]) * _ease_in_out_quad(frac)
    return pivot_lanes[-1]


def _slide_abs_lane(i: int) -> float:
    if i % 2 == 0:
        return STAGE_A_LANE
    return _stage_b_pivot_at_beat(regular_beats[i])


guide_stage = LevelStage(
    from_start=True,
    until_end=True,
    pivot_changes=[
        LevelStagePivotChange(
            beat=0.0,
            lane=0.0,
            division_size=1.0,
            division_parity=DivisionParity.EVEN,
            abs_y_offset=0.0,
            y_beat_offset=0.0,
            ease=EaseType.LINEAR,
        ),
    ],
)

guide_slide = LevelSlide()
guide_slide.notes = [
    LevelNote(
        beat=beat,
        lane=_slide_abs_lane(i),
        size=1.0 if i % 2 == 0 else 2.0,
        kind=NoteKind.ANCHOR,
        stage=guide_stage,
        is_separator=True,
        segment_kind=ConnectorKind.GUIDE_RED,
        connector_ease=EaseType.IN_OUT_QUAD,
    )
    for i, beat in enumerate(regular_beats)
]

fever_chance = LevelFeverChance(beat=1.0, force=True)
fever_start = LevelFeverStart(beat=100)
test_skill = LevelSkill(beat=1.0, effect=4)


# Full-screen guide overlay: exercises SegmentPresentation.FULL_SCREEN. While a segment is at the
# judge line (the current time falls within its target-time span), it fills the entire screen with
# the guide sprite at that segment's alpha sampled at the judge line, ignoring camera/zoom/tilt.
# The per-segment alpha ramps so the overlay intensity changes as successive segments cross the
# judge line; nothing is drawn before the first or after the last note. The window (beats 8-12.5)
# overlaps the flat-tilt hold (beats 10-14) to confirm the quad still covers the whole screen.
full_screen_guide_segments = [(8.0, 0.15), (9.5, 2), (11.0, 0.15), (12.5, 0.4)]
full_screen_guide = LevelSlide()
full_screen_guide.notes = [
    LevelNote(
        beat=beat,
        lane=0.0,
        size=1.0,
        kind=NoteKind.ANCHOR,
        stage=guide_stage,
        is_separator=True,
        segment_kind=ConnectorKind.GUIDE_BLUE,
        segment_alpha=alpha,
        segment_presentation=SegmentPresentation.FULL_SCREEN,
        connector_ease=EaseType.LINEAR,
        segment_layer=ConnectorLayer.OVER,
    )
    for beat, alpha in full_screen_guide_segments
]


# A separate stage on the right hosting a flick on every beat, to exercise flick rendering
# (bodies + arrows) under the tilt sweep. Its mask (lanes 4..6) sits just past stage_b's pulled-in
# right swing, so the visible masks don't overlap.
#
# It also exercises judge_line_style / full_width: it starts as a normal red judge line, fades into a
# SINGLE_LINE judge line (lanes 4..6) around the flat-camera hold so the single-line look and the
# suppressed slot effect on the flicks can be inspected without covering the screen, then widens to a
# full-width single line and finally to a full-width default judge line at the very end.
def _right_flick_style(beat: float, style: JudgeLineStyle, full_width: bool) -> LevelStageStyleChange:
    return LevelStageStyleChange(
        beat=beat,
        judge_line_color=JudgeLineColor.RED,
        judge_line_style=style,
        left_border_style=StageBorderStyle.DEFAULT,
        right_border_style=StageBorderStyle.DEFAULT,
        full_width=full_width,
        alpha=1.0,
        lane_alpha=1.0,
        judge_line_alpha=1.0,
        division_line_alpha=1.0,
        ease=EaseType.IN_OUT_QUAD,
    )


right_flick_stage = LevelStage(
    from_start=True,
    until_end=True,
    mask_changes=[
        LevelStageMaskChange(beat=0.0, lane=RIGHT_FLICK_LANE, size=1.0, ease=EaseType.LINEAR),
    ],
    pivot_changes=[
        LevelStagePivotChange(
            beat=0.0,
            lane=RIGHT_FLICK_LANE,
            division_size=1.0,
            division_parity=DivisionParity.EVEN,
            abs_y_offset=0.0,
            y_beat_offset=0.0,
            ease=EaseType.LINEAR,
        ),
    ],
    style_changes=[
        _right_flick_style(0.0, JudgeLineStyle.DEFAULT, full_width=False),
        _right_flick_style(6.0, JudgeLineStyle.DEFAULT, full_width=False),  # hold default
        _right_flick_style(9.0, JudgeLineStyle.SINGLE_LINE, full_width=False),  # fade to single line
        _right_flick_style(14.0, JudgeLineStyle.SINGLE_LINE, full_width=False),  # hold single line (slot effect off)
        _right_flick_style(17.0, JudgeLineStyle.SINGLE_LINE, full_width=True),  # widen to full-width single line
        _right_flick_style(19.0, JudgeLineStyle.SINGLE_LINE, full_width=True),  # hold full-width single line
        _right_flick_style(20.0, JudgeLineStyle.DEFAULT, full_width=True),  # full-width default judge line
    ],
)

right_flicks = [
    LevelNote(
        beat=float(b),
        lane=0.0,  # at the right stage's pivot
        size=1.0,
        kind=NoteKind.CRIT_FLICK,
        stage=right_flick_stage,
    )
    for b in range(1, int(SLIDE_END_BEAT) + 1)
]


entities = [
    LevelBpmChange(beat=0.0, bpm=60.0),
    stage_a,
    stage_b,
    guide_stage,
    right_flick_stage,
    *camera_changes,
    slide,
    guide_slide,
    fever_chance,
    fever_start,
    test_skill,
    full_screen_guide,
    *attached_notes,
    *right_flicks,
]

level = build_level(
    name="test",
    title="Test",
    bgm=None,
    entities=entities,
)


def load_levels():
    yield level
