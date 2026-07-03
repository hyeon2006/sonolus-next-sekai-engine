from __future__ import annotations

from enum import IntEnum
from math import ceil, cos, floor, pi
from typing import Protocol, assert_never, cast

from sonolus.script import runtime
from sonolus.script.archetype import EntityRef, get_archetype_by_name
from sonolus.script.array import Array, Dim
from sonolus.script.interval import clamp, interp, lerp, unlerp_clamped
from sonolus.script.quad import Quad, QuadLike, Rect
from sonolus.script.record import Record
from sonolus.script.runtime import is_multiplayer, is_play, is_replay, is_watch, time
from sonolus.script.sprite import Sprite
from sonolus.script.vec import Vec2

from sekai.lib import archetype_names
from sekai.lib.baseevent import get_event_as, query_event_list
from sekai.lib.custom_elements import (
    SkillHide,
    draw_life_number,
    draw_score_bar_number,
    draw_score_bar_raw_number,
    draw_score_number,
)
from sekai.lib.ease import EaseType, ease
from sekai.lib.effect import SFX_DISTANCE, Effects
from sekai.lib.layer import (
    LAYER_BACKGROUND,
    LAYER_BACKGROUND_COVER,
    LAYER_COVER,
    LAYER_JUDGMENT,
    LAYER_OVERLAY,
    LAYER_STAGE,
    LAYER_STAGE_LANE,
    ZIndexes,
    get_z,
    get_z_alt,
)
from sekai.lib.layout import (
    IDENTITY_AFFINE_TRANSFORM,
    TEST_ASPECT_SCALE,
    AffineTransform2d,
    DynamicLayout,
    Layout,
    ScoreGaugeType,
    StageTransform,
    StageTransformAnchor,
    StaticUiLayout,
    approach,
    compute_stage_transform,
    current_layout_transform,
    current_stage_tilt,
    identity_stage_transform,
    layout_full_width_stage_cover,
    layout_hidden_cover,
    layout_life_gauge,
    layout_particle_lane,
    layout_score_gauge,
    layout_sekai_stage,
    layout_stage_cover,
    layout_stage_cover_and_line,
    layout_stage_lane_by_edges,
    perspective_rect,
    stage_aspect_ratio_locked,
    tilt_depth,
    tilt_widened_edge,
    tilt_width_factor,
    transformed_vec_at,
)
from sekai.lib.level_config import LevelConfig
from sekai.lib.options import Options, StageCoverMode, Version
from sekai.lib.particle import ActiveParticles
from sekai.lib.skin import (
    ActiveSkin,
    JudgmentSpriteSet,
    LifeBarType,
    ScoreRankType,
)


class JudgeLineColor(IntEnum):
    NEUTRAL = 0
    RED = 1
    GREEN = 2
    BLUE = 3
    YELLOW = 4
    PURPLE = 5
    CYAN = 6
    BLACK = 7


class DivisionParity(IntEnum):
    EVEN = 0
    ODD = 1


class DivisionProps(Record):
    size: int
    parity: DivisionParity


class StageBorderStyle(IntEnum):
    DEFAULT = 0
    LIGHT = 1
    DISABLED = 2
    MEDIUM = 3


class JudgeLineStyle(IntEnum):
    DEFAULT = 0
    SINGLE_LINE = 1


FULL_WIDTH_HALF_EXTENT = 48.0
JUDGE_LINE_BORDER_FACTOR = 5.0


def full_width_factor(full_width: bool) -> float:
    return 1.0 if full_width else 0.0


class Transition[T](Record):
    start: T
    end: T
    progress: float


def judge_line_style_weight(style: Transition[JudgeLineStyle], target: JudgeLineStyle) -> float:
    weight = 0.0
    if style.start == target:
        weight += 1 - style.progress
    if style.end == target:
        weight += style.progress
    return weight


def resolve_judge_line_style(style: Transition[JudgeLineStyle]) -> JudgeLineStyle:
    """The dominant judge line style at the current moment, for discrete decisions (e.g. slot effects)."""
    if style.progress < 0.5:
        return style.start
    return style.end


class StageProps(Record):
    lane: float
    width: float
    pivot_lane: float
    division: Transition[DivisionProps]
    judge_line_color: Transition[JudgeLineColor]
    left_border_style: Transition[StageBorderStyle]
    right_border_style: Transition[StageBorderStyle]
    order: int
    lane_alpha: float
    judge_line_alpha: float
    y_offset: float
    judge_line_style: Transition[JudgeLineStyle]
    full_width: float
    division_line_alpha: float
    note_alpha: float
    rotate: float
    x_lane_translate: float
    y_lane_translate: float
    center_weight: float

    def stage_transform(self) -> StageTransform:
        return compute_stage_transform(
            current_layout_transform(),
            self.rotate,
            self.x_lane_translate,
            self.y_lane_translate,
            self.lane,
            self.center_weight,
        )

    def has_transform(self) -> bool:
        return (
            self.rotate != 0.0
            or self.x_lane_translate != 0.0
            or self.y_lane_translate != 0.0
            or self.center_weight != 0.0
        )

    def draw(self):
        ui_alpha = 1.0
        if Options.ui_intro and time() < -1.0:
            ui_alpha = unlerp_clamped(-2.0, -1.0, time())
        transform = +StageTransform
        if self.has_transform():
            transform @= self.stage_transform()
        else:
            transform @= identity_stage_transform()
        draw_dynamic_stage(
            lane=self.lane,
            width=self.width,
            pivot_lane=self.pivot_lane,
            division=self.division,
            judge_line_color=self.judge_line_color,
            judge_line_style=self.judge_line_style,
            left_border_style=self.left_border_style,
            right_border_style=self.right_border_style,
            order=self.order,
            lane_alpha=self.lane_alpha,
            judge_line_alpha=self.judge_line_alpha,
            y_offset=self.y_offset,
            alpha=ui_alpha,
            full_width=self.full_width,
            division_line_alpha=self.division_line_alpha,
            transform=transform.transform(),
        )


class StageMaskChangeLike(Protocol):
    time: float
    lane: float
    size: float
    ease: EaseType
    next_ref: EntityRef
    prev_ref: EntityRef

    @classmethod
    def at(cls, index: int) -> StageMaskChangeLike: ...

    @property
    def index(self) -> int: ...


class StagePivotChangeLike(Protocol):
    time: float
    lane: float
    division_size: float
    division_parity: DivisionParity
    y_offset: float
    ease: EaseType
    next_ref: EntityRef
    prev_ref: EntityRef

    @classmethod
    def at(cls, index: int) -> StagePivotChangeLike: ...

    @property
    def index(self) -> int: ...


class StageStyleChangeLike(Protocol):
    time: float
    judge_line_color: JudgeLineColor
    judge_line_style: JudgeLineStyle
    left_border_style: StageBorderStyle
    right_border_style: StageBorderStyle
    full_width: bool
    lane_alpha: float
    judge_line_alpha: float
    division_line_alpha: float
    note_alpha: float
    ease: EaseType
    next_ref: EntityRef
    prev_ref: EntityRef

    @classmethod
    def at(cls, index: int) -> StageStyleChangeLike: ...

    @property
    def index(self) -> int: ...


class StageTransformChangeLike(Protocol):
    time: float
    rotate: float
    x_lane_translate: float
    y_lane_translate: float
    anchor: StageTransformAnchor
    ease: EaseType
    next_ref: EntityRef
    prev_ref: EntityRef

    @classmethod
    def at(cls, index: int) -> StageTransformChangeLike: ...

    @property
    def index(self) -> int: ...


class DynamicStageLike(Protocol):
    from_start: bool
    until_end: bool
    first_mask_change_ref: EntityRef
    first_pivot_change_ref: EntityRef
    first_style_change_ref: EntityRef
    first_transform_change_ref: EntityRef

    @property
    def index(self) -> int: ...


def _stage_mask_change_archetype() -> type[StageMaskChangeLike]:
    return cast(type[StageMaskChangeLike], get_archetype_by_name(archetype_names.STAGE_MASK_CHANGE))


def _stage_pivot_change_archetype() -> type[StagePivotChangeLike]:
    return cast(type[StagePivotChangeLike], get_archetype_by_name(archetype_names.STAGE_PIVOT_CHANGE))


def _stage_style_change_archetype() -> type[StageStyleChangeLike]:
    return cast(type[StageStyleChangeLike], get_archetype_by_name(archetype_names.STAGE_STYLE_CHANGE))


def _stage_transform_change_archetype() -> type[StageTransformChangeLike]:
    return cast(type[StageTransformChangeLike], get_archetype_by_name(archetype_names.STAGE_TRANSFORM_CHANGE))


def center_anchor_weight(anchor: StageTransformAnchor) -> float:
    return 1.0 if anchor == StageTransformAnchor.CENTER else 0.0


def get_start_time(stage: DynamicStageLike) -> float:
    if stage.from_start:
        return -1e8
    result = 1e8
    if stage.first_mask_change_ref.index > 0:
        result = min(result, get_event_as(stage.first_mask_change_ref, _stage_mask_change_archetype()).time)
    if stage.first_pivot_change_ref.index > 0:
        result = min(result, get_event_as(stage.first_pivot_change_ref, _stage_pivot_change_archetype()).time)
    if stage.first_style_change_ref.index > 0:
        result = min(result, get_event_as(stage.first_style_change_ref, _stage_style_change_archetype()).time)
    if stage.first_transform_change_ref.index > 0:
        result = min(result, get_event_as(stage.first_transform_change_ref, _stage_transform_change_archetype()).time)
    return result


def get_end_time(stage: DynamicStageLike) -> float:
    if stage.until_end:
        return 1e8
    result = -1e8
    if stage.first_mask_change_ref.index > 0:
        last_ref, _ = query_event_list(stage.first_mask_change_ref, 1e8, lambda e: e.time)
        result = max(result, get_event_as(last_ref, _stage_mask_change_archetype()).time)
    if stage.first_pivot_change_ref.index > 0:
        last_ref, _ = query_event_list(stage.first_pivot_change_ref, 1e8, lambda e: e.time)
        result = max(result, get_event_as(last_ref, _stage_pivot_change_archetype()).time)
    if stage.first_style_change_ref.index > 0:
        last_ref, _ = query_event_list(stage.first_style_change_ref, 1e8, lambda e: e.time)
        result = max(result, get_event_as(last_ref, _stage_style_change_archetype()).time)
    if stage.first_transform_change_ref.index > 0:
        last_ref, _ = query_event_list(stage.first_transform_change_ref, 1e8, lambda e: e.time)
        result = max(result, get_event_as(last_ref, _stage_transform_change_archetype()).time)
    return result


def get_draw_start_time(stage: DynamicStageLike) -> float:
    if stage.from_start:
        return -1e8
    if stage.first_mask_change_ref.index > 0:
        return get_event_as(stage.first_mask_change_ref, _stage_mask_change_archetype()).time
    return 1e8


def get_draw_end_time(stage: DynamicStageLike) -> float:
    if stage.until_end:
        return 1e8
    if stage.first_mask_change_ref.index > 0:
        last_ref, _ = query_event_list(stage.first_mask_change_ref, 1e8, lambda e: e.time)
        return get_event_as(last_ref, _stage_mask_change_archetype()).time
    return -1e8


def get_next_event_time(stage: DynamicStageLike, t: float) -> float:
    result = 1e8
    if stage.first_mask_change_ref.index > 0:
        _, b_ref = query_event_list(stage.first_mask_change_ref, t, lambda e: e.time)
        if b_ref.index > 0:
            result = min(result, get_event_as(b_ref, _stage_mask_change_archetype()).time)
    if stage.first_pivot_change_ref.index > 0:
        _, b_ref = query_event_list(stage.first_pivot_change_ref, t, lambda e: e.time)
        if b_ref.index > 0:
            result = min(result, get_event_as(b_ref, _stage_pivot_change_archetype()).time)
    if stage.first_style_change_ref.index > 0:
        _, b_ref = query_event_list(stage.first_style_change_ref, t, lambda e: e.time)
        if b_ref.index > 0:
            result = min(result, get_event_as(b_ref, _stage_style_change_archetype()).time)
    if stage.first_transform_change_ref.index > 0:
        _, b_ref = query_event_list(stage.first_transform_change_ref, t, lambda e: e.time)
        if b_ref.index > 0:
            result = min(result, get_event_as(b_ref, _stage_transform_change_archetype()).time)
    return result


def get_stage_props(stage: DynamicStageLike, target_time: float | None = None, left_limit: bool = False) -> StageProps:
    t = target_time if target_time is not None else runtime.time()
    result = +StageProps
    result.order = stage.index
    result.note_alpha = 1.0

    first_mask_change_ref = stage.first_mask_change_ref
    first_pivot_change_ref = stage.first_pivot_change_ref
    first_style_change_ref = stage.first_style_change_ref
    first_transform_change_ref = stage.first_transform_change_ref

    # Query mask changes
    mask_a_ref, mask_b_ref = query_event_list(first_mask_change_ref, t, lambda e: e.time)
    if left_limit and mask_a_ref.index > 0:
        mask_curr = get_event_as(mask_a_ref, _stage_mask_change_archetype())
        if mask_curr.time == t:
            # Walk back through any same-time chain so b_ref ends up at the earliest at-t event.
            mask_probe_ref = +mask_curr.prev_ref
            while mask_probe_ref.index > 0:
                if get_event_as(mask_probe_ref, _stage_mask_change_archetype()).time != t:
                    break
                mask_a_ref.index = mask_probe_ref.index
                mask_probe_ref.index = get_event_as(mask_probe_ref, _stage_mask_change_archetype()).prev_ref.index
            mask_b_ref.index = mask_a_ref.index
            mask_a_ref.index = mask_probe_ref.index
    if mask_a_ref.index > 0:
        mask_a = get_event_as(mask_a_ref, _stage_mask_change_archetype())
        result.lane = mask_a.lane
        result.width = mask_a.size
        if mask_b_ref.index > 0:
            mask_b = get_event_as(mask_b_ref, _stage_mask_change_archetype())
            t_a = mask_a.time
            t_b = mask_b.time
            if t_b > t_a:
                p = ease(mask_a.ease, (t - t_a) / (t_b - t_a))
                result.lane = lerp(mask_a.lane, mask_b.lane, p)
                result.width = lerp(mask_a.size, mask_b.size, p)
    elif mask_b_ref.index > 0:
        mask_b = get_event_as(mask_b_ref, _stage_mask_change_archetype())
        result.lane = mask_b.lane
        result.width = mask_b.size

    # Query pivot changes
    pivot_a_ref, pivot_b_ref = query_event_list(first_pivot_change_ref, t, lambda e: e.time)
    if left_limit and pivot_a_ref.index > 0:
        pivot_curr = get_event_as(pivot_a_ref, _stage_pivot_change_archetype())
        if pivot_curr.time == t:
            pivot_probe_ref = +pivot_curr.prev_ref
            while pivot_probe_ref.index > 0:
                if get_event_as(pivot_probe_ref, _stage_pivot_change_archetype()).time != t:
                    break
                pivot_a_ref.index = pivot_probe_ref.index
                pivot_probe_ref.index = get_event_as(pivot_probe_ref, _stage_pivot_change_archetype()).prev_ref.index
            pivot_b_ref.index = pivot_a_ref.index
            pivot_a_ref.index = pivot_probe_ref.index
    if pivot_a_ref.index > 0:
        pivot_a = get_event_as(pivot_a_ref, _stage_pivot_change_archetype())
        result.pivot_lane = pivot_a.lane
        result.division.start.size = int(pivot_a.division_size)
        result.division.start.parity = pivot_a.division_parity
        result.division.end @= result.division.start
        result.y_offset = pivot_a.y_offset
        if pivot_b_ref.index > 0:
            pivot_b = get_event_as(pivot_b_ref, _stage_pivot_change_archetype())
            t_a = pivot_a.time
            t_b = pivot_b.time
            if t_b > t_a:
                p = ease(pivot_a.ease, (t - t_a) / (t_b - t_a))
                result.pivot_lane = lerp(pivot_a.lane, pivot_b.lane, p)
                result.division.end.size = int(pivot_b.division_size)
                result.division.end.parity = pivot_b.division_parity
                result.division.progress = p
                result.y_offset = lerp(pivot_a.y_offset, pivot_b.y_offset, p)
    elif pivot_b_ref.index > 0:
        pivot_b = get_event_as(pivot_b_ref, _stage_pivot_change_archetype())
        result.pivot_lane = pivot_b.lane
        result.division.start.size = int(pivot_b.division_size)
        result.division.start.parity = pivot_b.division_parity
        result.division.end @= result.division.start
        result.y_offset = pivot_b.y_offset

    # Query style changes
    style_a_ref, style_b_ref = query_event_list(first_style_change_ref, t, lambda e: e.time)
    if left_limit and style_a_ref.index > 0:
        style_curr = get_event_as(style_a_ref, _stage_style_change_archetype())
        if style_curr.time == t:
            style_probe_ref = +style_curr.prev_ref
            while style_probe_ref.index > 0:
                if get_event_as(style_probe_ref, _stage_style_change_archetype()).time != t:
                    break
                style_a_ref.index = style_probe_ref.index
                style_probe_ref.index = get_event_as(style_probe_ref, _stage_style_change_archetype()).prev_ref.index
            style_b_ref.index = style_a_ref.index
            style_a_ref.index = style_probe_ref.index
    if style_a_ref.index > 0:
        style_a = get_event_as(style_a_ref, _stage_style_change_archetype())
        result.judge_line_color.start = style_a.judge_line_color
        result.judge_line_color.end = style_a.judge_line_color
        result.judge_line_style.start = style_a.judge_line_style
        result.judge_line_style.end = style_a.judge_line_style
        result.left_border_style.start = style_a.left_border_style
        result.left_border_style.end = style_a.left_border_style
        result.right_border_style.start = style_a.right_border_style
        result.right_border_style.end = style_a.right_border_style
        result.lane_alpha = style_a.lane_alpha
        result.judge_line_alpha = style_a.judge_line_alpha
        result.full_width = full_width_factor(style_a.full_width)
        result.division_line_alpha = style_a.division_line_alpha
        result.note_alpha = style_a.note_alpha
        if style_b_ref.index > 0:
            style_b = get_event_as(style_b_ref, _stage_style_change_archetype())
            t_a = style_a.time
            t_b = style_b.time
            if t_b > t_a:
                p = ease(style_a.ease, (t - t_a) / (t_b - t_a))
                result.judge_line_color.end = style_b.judge_line_color
                result.judge_line_color.progress = p
                result.judge_line_style.end = style_b.judge_line_style
                result.judge_line_style.progress = p
                result.left_border_style.end = style_b.left_border_style
                result.left_border_style.progress = p
                result.right_border_style.end = style_b.right_border_style
                result.right_border_style.progress = p
                result.lane_alpha = lerp(style_a.lane_alpha, style_b.lane_alpha, p)
                result.judge_line_alpha = lerp(style_a.judge_line_alpha, style_b.judge_line_alpha, p)
                result.full_width = lerp(
                    full_width_factor(style_a.full_width), full_width_factor(style_b.full_width), p
                )
                result.division_line_alpha = lerp(style_a.division_line_alpha, style_b.division_line_alpha, p)
                result.note_alpha = lerp(style_a.note_alpha, style_b.note_alpha, p)
    elif style_b_ref.index > 0:
        style_b = get_event_as(style_b_ref, _stage_style_change_archetype())
        result.judge_line_color.start = style_b.judge_line_color
        result.judge_line_color.end = style_b.judge_line_color
        result.judge_line_style.start = style_b.judge_line_style
        result.judge_line_style.end = style_b.judge_line_style
        result.left_border_style.start = style_b.left_border_style
        result.left_border_style.end = style_b.left_border_style
        result.right_border_style.start = style_b.right_border_style
        result.right_border_style.end = style_b.right_border_style
        result.lane_alpha = style_b.lane_alpha
        result.judge_line_alpha = style_b.judge_line_alpha
        result.full_width = full_width_factor(style_b.full_width)
        result.division_line_alpha = style_b.division_line_alpha
        result.note_alpha = style_b.note_alpha

    # Query transform changes
    transform_a_ref, transform_b_ref = query_event_list(first_transform_change_ref, t, lambda e: e.time)
    if left_limit and transform_a_ref.index > 0:
        transform_curr = get_event_as(transform_a_ref, _stage_transform_change_archetype())
        if transform_curr.time == t:
            transform_probe_ref = +transform_curr.prev_ref
            while transform_probe_ref.index > 0:
                if get_event_as(transform_probe_ref, _stage_transform_change_archetype()).time != t:
                    break
                transform_a_ref.index = transform_probe_ref.index
                transform_probe_ref.index = get_event_as(
                    transform_probe_ref, _stage_transform_change_archetype()
                ).prev_ref.index
            transform_b_ref.index = transform_a_ref.index
            transform_a_ref.index = transform_probe_ref.index
    if transform_a_ref.index > 0:
        transform_a = get_event_as(transform_a_ref, _stage_transform_change_archetype())
        result.rotate = transform_a.rotate
        result.x_lane_translate = transform_a.x_lane_translate
        result.y_lane_translate = transform_a.y_lane_translate
        result.center_weight = center_anchor_weight(transform_a.anchor)
        if transform_b_ref.index > 0:
            transform_b = get_event_as(transform_b_ref, _stage_transform_change_archetype())
            t_a = transform_a.time
            t_b = transform_b.time
            if t_b > t_a:
                p = ease(transform_a.ease, (t - t_a) / (t_b - t_a))
                result.rotate = lerp(transform_a.rotate, transform_b.rotate, p)
                result.x_lane_translate = lerp(transform_a.x_lane_translate, transform_b.x_lane_translate, p)
                result.y_lane_translate = lerp(transform_a.y_lane_translate, transform_b.y_lane_translate, p)
                result.center_weight = lerp(
                    center_anchor_weight(transform_a.anchor), center_anchor_weight(transform_b.anchor), p
                )
    elif transform_b_ref.index > 0:
        transform_b = get_event_as(transform_b_ref, _stage_transform_change_archetype())
        result.rotate = transform_b.rotate
        result.x_lane_translate = transform_b.x_lane_translate
        result.y_lane_translate = transform_b.y_lane_translate
        result.center_weight = center_anchor_weight(transform_b.anchor)

    return result


TEST_ASPECT_BOX_EDGE = 0.004


def draw_aspect_box(sprite: Sprite, ratio: float, sub: int):
    if not stage_aspect_ratio_locked():
        return
    hf = TEST_ASPECT_SCALE * Layout.field_h / 2
    wf = TEST_ASPECT_SCALE * Layout.field_w / 2
    if ratio < wf / hf:
        hw = wf
        hh = wf / ratio
    else:
        hw = ratio * hf
        hh = hf
    e = TEST_ASPECT_BOX_EDGE
    top = Rect(l=-hw - e, r=hw + e, t=hh + e, b=hh - e)
    bottom = Rect(l=-hw - e, r=hw + e, t=-hh + e, b=-hh - e)
    left = Rect(l=-hw - e, r=-hw + e, t=hh, b=-hh)
    right = Rect(l=hw - e, r=hw + e, t=hh, b=-hh)
    sprite.draw(top.as_quad(), z=get_z_alt(LAYER_OVERLAY, 1000 + 4 * sub).tuple, a=1.0)
    sprite.draw(bottom.as_quad(), z=get_z_alt(LAYER_OVERLAY, 1000 + 4 * sub + 1).tuple, a=1.0)
    sprite.draw(left.as_quad(), z=get_z_alt(LAYER_OVERLAY, 1000 + 4 * sub + 2).tuple, a=1.0)
    sprite.draw(right.as_quad(), z=get_z_alt(LAYER_OVERLAY, 1000 + 4 * sub + 3).tuple, a=1.0)


def draw_test_aspect_overlay():
    if not Options.test_aspect_ratio:
        return
    # Higher sub = drawn on top; 16:9 (the field reference) is drawn last so it sits topmost.
    draw_aspect_box(ActiveSkin.guide_red, 21 / 9, 0)
    draw_aspect_box(ActiveSkin.guide_blue, 4 / 3, 1)
    draw_aspect_box(ActiveSkin.guide_green, 16 / 9, 2)


def draw_stage_and_accessories(
    ap: bool,
    score: float,
    note_score: float,
    note_time: float,
    percentage: float,
    background_cover: Quad,
    dead_effect_quads: Array[Quad, Dim[4]],
    ui_layout: StaticUiLayout,
    life: float = 1000.0,
    last_time: float = 1e8,
    dead_time: float = 1e8,
    layout_stage: Quad = Quad.zero(),  # noqa: B008
):
    ui_alpha = 1.0
    if Options.ui_intro and time() < -1.0:
        ui_alpha = unlerp_clamped(-2.0, -1.0, time())
    if not LevelConfig.skip_default_stage:
        draw_basic_stage(ui_alpha, layout_stage)
    draw_stage_cover(ui_alpha)
    draw_test_aspect_overlay()
    draw_auto_play(ui_layout)
    draw_background_cover(background_cover)
    draw_dead(life, dead_time, background_cover, dead_effect_quads)
    draw_score_number(
        ap=ap,
        score=percentage,
        alpha=ui_alpha,
    )
    draw_life_bar(
        life,
        last_time,
        ui_layout,
        alpha=ui_alpha,
    )
    draw_score_bar(
        score,
        note_score,
        note_time,
        ui_layout,
        alpha=ui_alpha,
    )


def normalize_transition[T](value: Transition[T] | T) -> Transition[T]:
    if isinstance(value, Transition):
        return value
    return Transition(start=value, end=value, progress=0)


def draw_basic_stage(alpha=1.0, layout=Quad.zero()):  # noqa: B008
    if not Options.show_lane:
        return
    if (
        ActiveSkin.sekai_stage_lane.is_available
        and ActiveSkin.sekai_stage_cover.is_available
        and not LevelConfig.dynamic_stages
    ):
        draw_sekai_divided_stage(LAYER_STAGE_LANE, LAYER_COVER, alpha, layout)
    else:
        draw_dynamic_stage(
            lane=0,
            width=6,
            pivot_lane=0,
            division=DivisionProps(size=2, parity=DivisionParity.EVEN),
            judge_line_color=JudgeLineColor.PURPLE,
            left_border_style=StageBorderStyle.DEFAULT,
            right_border_style=StageBorderStyle.DEFAULT,
            order=0,
            lane_alpha=alpha,
            judge_line_alpha=alpha,
            transform=IDENTITY_AFFINE_TRANSFORM,
        )


def draw_sekai_stage(z_stage, alpha):
    layout = layout_sekai_stage()
    ActiveSkin.sekai_stage.draw(layout, z=z_stage, a=alpha)


def draw_sekai_divided_stage(z_stage_lane, z_stage_cover, alpha, layout):
    resolved = +Quad
    if layout == Quad.zero():
        resolved @= layout_sekai_stage()
    else:
        resolved @= layout
    ActiveSkin.sekai_stage_lane.draw(resolved, z=z_stage_lane, a=alpha)
    if Options.lane_alpha > 0:
        ActiveSkin.sekai_stage_cover.draw(resolved, z=z_stage_cover, a=Options.lane_alpha * alpha)


def get_judgment_sprites(judge_line_color: JudgeLineColor) -> JudgmentSpriteSet:
    result = +JudgmentSpriteSet
    match judge_line_color:
        case JudgeLineColor.NEUTRAL:
            result @= ActiveSkin.judgment_neutral
        case JudgeLineColor.RED:
            result @= ActiveSkin.judgment_red
        case JudgeLineColor.GREEN:
            result @= ActiveSkin.judgment_green
        case JudgeLineColor.BLUE:
            result @= ActiveSkin.judgment_blue
        case JudgeLineColor.YELLOW:
            result @= ActiveSkin.judgment_yellow
        case JudgeLineColor.PURPLE:
            result @= ActiveSkin.judgment_purple
        case JudgeLineColor.CYAN:
            result @= ActiveSkin.judgment_cyan
        case JudgeLineColor.BLACK:
            result @= ActiveSkin.judgment_black
        case _:
            assert_never(judge_line_color)
    return result


def draw_dynamic_stage(
    lane: float,
    width: float,
    pivot_lane: float,
    division: Transition[DivisionProps] | DivisionProps,
    judge_line_color: Transition[JudgeLineColor] | JudgeLineColor,
    left_border_style: Transition[StageBorderStyle] | StageBorderStyle,
    right_border_style: Transition[StageBorderStyle] | StageBorderStyle,
    order: int,
    lane_alpha: float = 1,
    judge_line_alpha: float = 1,
    y_offset: float = 0,
    alpha: float = 1,
    judge_line_style: Transition[JudgeLineStyle] | JudgeLineStyle = JudgeLineStyle.DEFAULT,
    full_width: float = 0,
    division_line_alpha: float = 1,
    *,
    transform: AffineTransform2d,
):
    division = normalize_transition(division)
    judge_line_color = normalize_transition(judge_line_color)
    judge_line_style = normalize_transition(judge_line_style)
    left_border_style = normalize_transition(left_border_style)
    right_border_style = normalize_transition(right_border_style)

    def place(q: QuadLike) -> QuadLike:
        return transform.transform_quad(q)

    sprites_same = judge_line_color.start == judge_line_color.end
    sprites_a = get_judgment_sprites(judge_line_color.start)
    sprites_b = get_judgment_sprites(judge_line_color.end)
    p_sprites = judge_line_color.progress

    w_default = judge_line_style_weight(judge_line_style, JudgeLineStyle.DEFAULT)
    w_single_line = judge_line_style_weight(judge_line_style, JudgeLineStyle.SINGLE_LINE)
    fw = clamp(full_width, 0, 1)

    if not ActiveSkin.lane_background.is_available:
        draw_fallback_stage(
            lane,
            width,
            division.end.size,
            division.end.parity,
            pivot_lane,
            order,
            lane_alpha,
            judge_line_alpha,
            y_offset,
            alpha,
            judge_line_style,
            fw,
            transform=transform,
        )
        return

    travel = approach(1 - y_offset)
    nh = DynamicLayout.note_h
    l = lane - width
    r = lane + width
    half_jl = lerp(width, FULL_WIDTH_HALF_EXTENT, fw)
    l_jl = lane - half_jl
    r_jl = lane + half_jl
    z_bg0 = get_z_alt(LAYER_STAGE)
    z_bg1_a = get_z_alt(LAYER_STAGE, 1)
    z_bg1_b = get_z_alt(LAYER_STAGE, 2)
    z_lane0 = get_z_alt(LAYER_STAGE, 3)
    z_lane1 = get_z_alt(LAYER_STAGE, 4)
    z_a0 = get_z_alt(LAYER_STAGE, 5)
    z_a1 = get_z_alt(LAYER_STAGE, 6)
    z_a2 = get_z_alt(LAYER_STAGE, 7)
    z_a3 = get_z_alt(LAYER_STAGE, 8)
    z_b0 = get_z_alt(LAYER_STAGE, 9)
    z_b1 = get_z_alt(LAYER_STAGE, 10)
    z_b2 = get_z_alt(LAYER_STAGE, 11)
    z_b3 = get_z_alt(LAYER_STAGE, 12)
    z_a4 = get_z_alt(LAYER_STAGE, 13)
    z_b4 = get_z_alt(LAYER_STAGE, 14)
    z_single_a = get_z_alt(LAYER_STAGE, 15)
    z_single_b = get_z_alt(LAYER_STAGE, 16)

    f = 5  # sizing factor for judge line border

    def draw_left_border(style: StageBorderStyle, z: ZIndexes, a: float):
        match style:
            case StageBorderStyle.DEFAULT | StageBorderStyle.MEDIUM:
                scale = 0.5 if style == StageBorderStyle.MEDIUM else 1.0
                layout_b = layout_stage_lane_by_edges(
                    l - 0.08 * scale, l
                )  # Artificially thicken the top so it renders better
                layout_t = layout_stage_lane_by_edges(tilt_widened_edge(l - 0.08 * scale, l - 0.64 * scale), l)
                ActiveSkin.stage_border.draw(
                    place(Quad(bl=layout_b.bl, tl=layout_t.tl, tr=layout_t.tr, br=layout_b.br)), z=z.tuple, a=a
                )
            case StageBorderStyle.LIGHT:
                layout_b = layout_stage_lane_by_edges(l - 0.0125, l + 0.0125)
                layout_t = layout_stage_lane_by_edges(
                    tilt_widened_edge(l - 0.0125, l - 0.1), tilt_widened_edge(l + 0.0125, l + 0.1)
                )
                ActiveSkin.lane_divider.draw(
                    place(Quad(bl=layout_b.bl, tl=layout_t.tl, tr=layout_t.tr, br=layout_b.br)), z=z.tuple, a=a
                )
            case StageBorderStyle.DISABLED:
                pass
            case _:
                assert_never(style)

    def draw_right_border(style: StageBorderStyle, z: ZIndexes, a: float):
        match style:
            case StageBorderStyle.DEFAULT | StageBorderStyle.MEDIUM:
                scale = 0.5 if style == StageBorderStyle.MEDIUM else 1.0
                layout_b = layout_stage_lane_by_edges(r + 0.08 * scale, r)  # Flip horizontally
                layout_t = layout_stage_lane_by_edges(tilt_widened_edge(r + 0.08 * scale, r + 0.64 * scale), r)
                ActiveSkin.stage_border.draw(
                    place(Quad(bl=layout_b.bl, tl=layout_t.tl, tr=layout_t.tr, br=layout_b.br)), z=z.tuple, a=a
                )
            case StageBorderStyle.LIGHT:
                layout_b = layout_stage_lane_by_edges(r - 0.0125, r + 0.0125)
                layout_t = layout_stage_lane_by_edges(
                    tilt_widened_edge(r - 0.0125, r - 0.1), tilt_widened_edge(r + 0.0125, r + 0.1)
                )
                ActiveSkin.lane_divider.draw(
                    place(Quad(bl=layout_b.bl, tl=layout_t.tl, tr=layout_t.tr, br=layout_b.br)), z=z.tuple, a=a
                )
            case StageBorderStyle.DISABLED:
                pass
            case _:
                assert_never(style)

    def draw_dividers(division_size: int, parity: DivisionParity, pivot: float, z: ZIndexes, a: float):
        eps = 0.001
        parity_offset = division_size / 2 if parity == DivisionParity.ODD else 0
        shifted_pivot = pivot + parity_offset

        if division_size <= 0:
            return

        k_start = floor((l - shifted_pivot + eps) / division_size) + 1
        k_end = ceil((r - shifted_pivot - eps) / division_size) - 1

        for k in range(k_start, k_end + 1):
            pos = shifted_pivot + k * division_size
            div_layout_b = layout_stage_lane_by_edges(pos - 0.0125, pos + 0.0125)
            div_layout_t = layout_stage_lane_by_edges(
                tilt_widened_edge(pos - 0.0125, pos - 0.1), tilt_widened_edge(pos + 0.0125, pos + 0.1)
            )
            ActiveSkin.lane_divider.draw(
                place(Quad(bl=div_layout_b.bl, tl=div_layout_t.tl, tr=div_layout_t.tr, br=div_layout_b.br)),
                z=z.tuple,
                a=a,
            )

    thickness_scale = lerp(1.0, clamp(1 / travel, 1, 4) if travel > 0 else 4, current_stage_tilt())
    judgment_divider_size = 0.014 * thickness_scale * tilt_width_factor(travel) * DynamicLayout.w_scale
    judgment_divider_offset = Vec2(judgment_divider_size, 0).rotate(-DynamicLayout.rotate)
    divider_depth_b = tilt_depth(1 + nh - nh / f + 0.001, travel)
    divider_depth_t = tilt_depth(1 - nh + nh / f - 0.001, travel)

    def layout_judgment_divider(lane: float):
        b = transformed_vec_at(lane, divider_depth_b)
        t = transformed_vec_at(lane, divider_depth_t)
        return Quad(
            bl=b - judgment_divider_offset,
            tl=t - judgment_divider_offset,
            tr=t + judgment_divider_offset,
            br=b + judgment_divider_offset,
        )

    def draw_judgment_dividers(
        sprites: JudgmentSpriteSet, half_offset: bool, pivot: float, z_lo: ZIndexes, z_hi: ZIndexes, a: float
    ):
        eps = 0.001
        shifted_pivot = pivot + (0.5 if half_offset else 0)

        k_start = floor(l - shifted_pivot + eps) + 1
        k_end = ceil(r - shifted_pivot - eps) - 1

        for k in range(k_start, k_end + 1):
            pos = shifted_pivot + k
            div_layout = place(layout_judgment_divider(pos))
            edge_weight = abs(pos - lane) / width if width > 0 else 0
            sprites.judgment_center.draw(div_layout, z=z_lo.tuple, a=a)
            sprites.judgment_edge.draw(div_layout, z=z_hi.tuple, a=a * edge_weight)

    def draw_left_judgment_border(sprites: JudgmentSpriteSet, style: StageBorderStyle, z: ZIndexes, a: float):
        match style:
            case StageBorderStyle.DEFAULT | StageBorderStyle.MEDIUM:
                if width <= 0:
                    return
                layout = place(
                    perspective_rect(
                        l,
                        min(l + 1 / f / 2, lane),
                        1 - nh + nh / f,
                        1 + nh - nh / f,
                        travel,
                    )
                )
                sprites.judgment_edge_left.draw(layout, z=z.tuple, a=a)
            case StageBorderStyle.LIGHT:
                layout = place(layout_judgment_divider(l))
                sprites.judgment_edge.draw(layout, z=z.tuple, a=a)
            case StageBorderStyle.DISABLED:
                pass
            case _:
                assert_never(style)

    def draw_right_judgment_border(sprites: JudgmentSpriteSet, style: StageBorderStyle, z: ZIndexes, a: float):
        match style:
            case StageBorderStyle.DEFAULT | StageBorderStyle.MEDIUM:
                if width <= 0:
                    return
                layout = place(
                    perspective_rect(
                        r,
                        max(r - 1 / f / 2, lane),
                        1 - nh + nh / f,
                        1 + nh - nh / f,
                        travel,
                    )
                )
                sprites.judgment_edge_left.draw(layout, z=z.tuple, a=a)
            case StageBorderStyle.LIGHT:
                layout = place(layout_judgment_divider(r))
                sprites.judgment_edge.draw(layout, z=z.tuple, a=a)
            case StageBorderStyle.DISABLED:
                pass
            case _:
                assert_never(style)

    def draw_gradient(sprites: JudgmentSpriteSet, z: ZIndexes, a: float):
        bottom_l = place(perspective_rect(l_jl, lane, 1 + nh, 1 + nh - nh / f, travel))
        bottom_r = place(perspective_rect(r_jl, lane, 1 + nh, 1 + nh - nh / f, travel))
        top_l = place(perspective_rect(l_jl, lane, 1 - nh, 1 - nh + nh / f, travel))
        top_r = place(perspective_rect(r_jl, lane, 1 - nh, 1 - nh + nh / f, travel))
        grad_a = a * (1 - fw)
        edge_a = a * fw
        if grad_a > 0:
            sprites.judgment_gradient.draw(bottom_l, z=z.tuple, a=grad_a)
            sprites.judgment_gradient.draw(bottom_r, z=z.tuple, a=grad_a)
            sprites.judgment_gradient.draw(top_l, z=z.tuple, a=grad_a)
            sprites.judgment_gradient.draw(top_r, z=z.tuple, a=grad_a)
        if edge_a > 0:
            sprites.judgment_edge.draw(bottom_l, z=z.tuple, a=edge_a)
            sprites.judgment_edge.draw(bottom_r, z=z.tuple, a=edge_a)
            sprites.judgment_edge.draw(top_l, z=z.tuple, a=edge_a)
            sprites.judgment_edge.draw(top_r, z=z.tuple, a=edge_a)

    def draw_single_line(sprites: JudgmentSpriteSet, z: ZIndexes, a: float):
        half_thick = nh / f / 2
        layout = place(perspective_rect(l_jl, r_jl, 1 - half_thick, 1 + half_thick, travel))
        sprites.judgment_edge.draw(layout, z=z.tuple, a=a)

    la = lane_alpha * (1 - fw)
    if la > 0:
        ActiveSkin.lane_background.draw(place(layout_stage_lane_by_edges(l, r)), z=z_bg0.tuple, a=la)

        p_left = left_border_style.progress
        if left_border_style.start == left_border_style.end:
            draw_left_border(left_border_style.start, z_lane0, la)
        else:
            draw_left_border(left_border_style.start, z_lane0, la * (1 - p_left))
            draw_left_border(left_border_style.end, z_lane1, la * p_left)

        p_right = right_border_style.progress
        if right_border_style.start == right_border_style.end:
            draw_right_border(right_border_style.start, z_lane0, la)
        else:
            draw_right_border(right_border_style.start, z_lane0, la * (1 - p_right))
            draw_right_border(right_border_style.end, z_lane1, la * p_right)

        la_div = la * division_line_alpha
        if la_div > 0:
            p_div = division.progress
            if division.start == division.end:
                draw_dividers(division.start.size, division.start.parity, pivot_lane, z_lane0, la_div)
            else:
                if 1 - p_div > 0:
                    draw_dividers(division.start.size, division.start.parity, pivot_lane, z_lane0, la_div * (1 - p_div))
                if p_div > 0:
                    draw_dividers(division.end.size, division.end.parity, pivot_lane, z_lane1, la_div * p_div)

    ja = judge_line_alpha
    ja_bar = ja * w_default
    ja_dec = ja_bar * (1 - fw)
    ja_single = ja * w_single_line

    if ja_bar > 0:
        bg_layout = place(perspective_rect(l_jl, r_jl, 1 - nh, 1 + nh, travel))
        if sprites_same:
            sprites_a.judgment_background.draw(bg_layout, z=z_bg1_a.tuple, a=ja_bar)
        else:
            sprites_a.judgment_background.draw(bg_layout, z=z_bg1_a.tuple, a=ja_bar * (1 - p_sprites))
            sprites_b.judgment_background.draw(bg_layout, z=z_bg1_b.tuple, a=ja_bar * p_sprites)

    p_left = left_border_style.progress
    p_right = right_border_style.progress
    p_div = division.progress

    start_has_half_offset = division.start.parity == DivisionParity.ODD and division.start.size % 2 == 1
    end_has_half_offset = division.end.parity == DivisionParity.ODD and division.end.size % 2 == 1
    judgment_dividers_same = start_has_half_offset == end_has_half_offset

    if ja_dec > 0:
        if judgment_dividers_same and sprites_same:
            draw_judgment_dividers(sprites_a, start_has_half_offset, pivot_lane, z_a0, z_a1, ja_dec)
        elif judgment_dividers_same:
            draw_judgment_dividers(sprites_a, start_has_half_offset, pivot_lane, z_a0, z_a1, ja_dec * (1 - p_sprites))
            draw_judgment_dividers(sprites_b, start_has_half_offset, pivot_lane, z_b0, z_b1, ja_dec * p_sprites)
        elif sprites_same:
            draw_judgment_dividers(sprites_a, start_has_half_offset, pivot_lane, z_a0, z_a1, ja_dec * (1 - p_div))
            draw_judgment_dividers(sprites_a, end_has_half_offset, pivot_lane, z_a2, z_a3, ja_dec * p_div)
        else:
            alpha_aa = (1 - p_sprites) * (1 - p_div)
            alpha_ab = (1 - p_sprites) * p_div
            alpha_ba = p_sprites * (1 - p_div)
            alpha_bb = p_sprites * p_div
            if alpha_aa > 0:
                draw_judgment_dividers(sprites_a, start_has_half_offset, pivot_lane, z_a0, z_a1, ja_dec * alpha_aa)
            if alpha_ab > 0:
                draw_judgment_dividers(sprites_a, end_has_half_offset, pivot_lane, z_a2, z_a3, ja_dec * alpha_ab)
            if alpha_ba > 0:
                draw_judgment_dividers(sprites_b, start_has_half_offset, pivot_lane, z_b0, z_b1, ja_dec * alpha_ba)
            if alpha_bb > 0:
                draw_judgment_dividers(sprites_b, end_has_half_offset, pivot_lane, z_b2, z_b3, ja_dec * alpha_bb)

    if ja_bar > 0:
        if sprites_same:
            draw_gradient(sprites_a, z_a4, ja_bar)
        else:
            draw_gradient(sprites_a, z_a4, ja_bar * (1 - p_sprites))
            draw_gradient(sprites_b, z_b4, ja_bar * p_sprites)

    if ja_dec > 0:
        if sprites_same and left_border_style.start == left_border_style.end:
            draw_left_judgment_border(sprites_a, left_border_style.start, z_a0, ja_dec)
        else:
            alpha_aa = (1 - p_sprites) * (1 - p_left)
            alpha_ab = (1 - p_sprites) * p_left
            alpha_ba = p_sprites * (1 - p_left)
            alpha_bb = p_sprites * p_left
            if alpha_aa > 0:
                draw_left_judgment_border(sprites_a, left_border_style.start, z_a0, ja_dec * alpha_aa)
            if alpha_ab > 0:
                draw_left_judgment_border(sprites_a, left_border_style.end, z_a2, ja_dec * alpha_ab)
            if alpha_ba > 0:
                draw_left_judgment_border(sprites_b, left_border_style.start, z_b0, ja_dec * alpha_ba)
            if alpha_bb > 0:
                draw_left_judgment_border(sprites_b, left_border_style.end, z_b2, ja_dec * alpha_bb)

        if sprites_same and right_border_style.start == right_border_style.end:
            draw_right_judgment_border(sprites_a, right_border_style.start, z_a0, ja_dec)
        else:
            alpha_aa = (1 - p_sprites) * (1 - p_right)
            alpha_ab = (1 - p_sprites) * p_right
            alpha_ba = p_sprites * (1 - p_right)
            alpha_bb = p_sprites * p_right
            if alpha_aa > 0:
                draw_right_judgment_border(sprites_a, right_border_style.start, z_a0, ja_dec * alpha_aa)
            if alpha_ab > 0:
                draw_right_judgment_border(sprites_a, right_border_style.end, z_a2, ja_dec * alpha_ab)
            if alpha_ba > 0:
                draw_right_judgment_border(sprites_b, right_border_style.start, z_b0, ja_dec * alpha_ba)
            if alpha_bb > 0:
                draw_right_judgment_border(sprites_b, right_border_style.end, z_b2, ja_dec * alpha_bb)

    if ja_single > 0:
        if sprites_same:
            draw_single_line(sprites_a, z_single_a, ja_single)
        else:
            draw_single_line(sprites_a, z_single_a, ja_single * (1 - p_sprites))
            draw_single_line(sprites_b, z_single_b, ja_single * p_sprites)

    draw_per_stage_cover(l, r, lane_alpha, alpha, order, transform)


def draw_fallback_stage(
    lane: float,
    width: float,
    division_size: int,
    parity: DivisionParity,
    pivot: float,
    order: int,
    lane_alpha: float = 1,
    judge_line_alpha: float = 1,
    y_offset: float = 0,
    alpha: float = 1,
    judge_line_style: Transition[JudgeLineStyle] | JudgeLineStyle = JudgeLineStyle.DEFAULT,
    full_width: float = 0,
    *,
    transform: AffineTransform2d,
):
    def place(q: QuadLike) -> QuadLike:
        return transform.transform_quad(q)

    judge_line_style = normalize_transition(judge_line_style)
    w_default = judge_line_style_weight(judge_line_style, JudgeLineStyle.DEFAULT)
    w_single_line = judge_line_style_weight(judge_line_style, JudgeLineStyle.SINGLE_LINE)
    travel = approach(1 - y_offset)
    nh = DynamicLayout.note_h
    l = lane - width
    r = lane + width
    fw = clamp(full_width, 0, 1)
    half_jl = lerp(width, FULL_WIDTH_HALF_EXTENT, fw)
    l_jl = lane - half_jl
    r_jl = lane + half_jl
    z_lo = get_z_alt(LAYER_STAGE)
    z_mid = get_z_alt(LAYER_STAGE, 1)
    z_hi = get_z_alt(LAYER_STAGE, 2)
    z_single = get_z_alt(LAYER_STAGE, 3)
    la = lane_alpha * (1 - fw)
    ja = judge_line_alpha
    if la > 0:
        # Artificially thicken the top so it renders better
        layout_b = layout_stage_lane_by_edges(l - 0.25, l)
        layout_t = layout_stage_lane_by_edges(tilt_widened_edge(l - 0.25, l - 1), l)
        ActiveSkin.stage_left_border.draw(
            place(Quad(bl=layout_b.bl, tl=layout_t.tl, tr=layout_t.tr, br=layout_b.br)), z=z_mid.tuple, a=la
        )
        layout_b = layout_stage_lane_by_edges(r, r + 0.25)
        layout_t = layout_stage_lane_by_edges(r, tilt_widened_edge(r + 0.25, r + 1))
        ActiveSkin.stage_right_border.draw(
            place(Quad(bl=layout_b.bl, tl=layout_t.tl, tr=layout_t.tr, br=layout_b.br)), z=z_mid.tuple, a=la
        )

        eps = 0.001
        parity_offset = division_size / 2 if parity == DivisionParity.ODD else 0
        shifted_pivot = pivot + parity_offset
        prev = l
        if division_size > 0:
            k_start = floor((l - shifted_pivot + eps) / division_size) + 1
            k_end = ceil((r - shifted_pivot - eps) / division_size) - 1
            for k in range(k_start, k_end + 1):
                pos = shifted_pivot + k * division_size
                ActiveSkin.lane.draw(place(layout_stage_lane_by_edges(prev, pos)), a=la, z=z_lo.tuple)
                prev = pos
        ActiveSkin.lane.draw(place(layout_stage_lane_by_edges(prev, r)), a=la, z=z_lo.tuple)

    if ja * w_default > 0:
        layout = place(perspective_rect(l_jl, r_jl, t=1 - nh, b=1 + nh, travel=travel))
        ActiveSkin.judgment_line.draw(layout, z=z_hi.tuple, a=ja * w_default)
    if ja * w_single_line > 0:
        half_thick = nh / JUDGE_LINE_BORDER_FACTOR / 2
        layout = place(perspective_rect(l_jl, r_jl, t=1 - half_thick, b=1 + half_thick, travel=travel))
        ActiveSkin.judgment_line.draw(layout, z=z_single.tuple, a=ja * w_single_line)

    draw_per_stage_cover(l, r, lane_alpha, alpha, order, transform)


def draw_per_stage_cover(
    l: float,
    r: float,
    lane_alpha: float,
    alpha: float,
    order: int,
    transform: AffineTransform2d,
):
    if not LevelConfig.dynamic_stages:
        return
    ca = lane_alpha
    if ca <= 0:
        return

    def place(q: QuadLike) -> QuadLike:
        return transform.transform_quad(q)

    z_cover = get_z_alt(LAYER_COVER)
    z_line = get_z_alt(LAYER_COVER, 1)
    z_hidden = get_z_alt(LAYER_COVER, 2)
    if Options.stage_cover > 0:
        match Options.stage_cover_mode:
            case StageCoverMode.STAGE:
                layout = layout_stage_cover(l, r)
                ActiveSkin.cover.draw(place(layout), z=z_cover.tuple, a=Options.stage_cover_alpha * ca * alpha)
            case StageCoverMode.STAGE_AND_LINE:
                cover_layout, line_layout = layout_stage_cover_and_line(l, r)
                ActiveSkin.cover.draw(place(cover_layout), z=z_cover.tuple, a=Options.stage_cover_alpha * ca * alpha)
                ActiveSkin.guide_neutral.draw(place(line_layout), z=z_line.tuple, a=0.75 * ca * alpha)
            case StageCoverMode.FULL_WIDTH:
                pass
            case _:
                assert_never(Options.stage_cover_mode)
    if Options.hidden > 0:
        layout = layout_hidden_cover(l, r)
        ActiveSkin.cover.draw(place(layout), z=z_hidden.tuple, a=ca * alpha)


def draw_stage_cover(alpha):
    if Options.stage_cover > 0:
        match Options.stage_cover_mode:
            case StageCoverMode.STAGE:
                if not LevelConfig.dynamic_stages:
                    layout = layout_stage_cover()
                    ActiveSkin.cover.draw(layout, z=get_z(LAYER_COVER).tuple, a=Options.stage_cover_alpha * alpha)
            case StageCoverMode.STAGE_AND_LINE:
                if not LevelConfig.dynamic_stages:
                    cover_layout, line_layout = layout_stage_cover_and_line()
                    ActiveSkin.cover.draw(cover_layout, z=get_z(LAYER_COVER).tuple, a=Options.stage_cover_alpha * alpha)
                    ActiveSkin.guide_neutral.draw(line_layout, z=get_z(LAYER_COVER, etc=1).tuple, a=0.75 * alpha)
            case StageCoverMode.FULL_WIDTH:
                layout = layout_full_width_stage_cover()
                ActiveSkin.cover.draw(layout, z=get_z(LAYER_COVER).tuple, a=Options.stage_cover_alpha * alpha)
            case _:
                assert_never(Options.stage_cover_mode)
    if Options.hidden > 0 and not LevelConfig.dynamic_stages:
        layout = layout_hidden_cover()
        ActiveSkin.cover.draw(layout, z=get_z(LAYER_COVER).tuple, a=alpha)


def draw_background_cover(background_cover):
    if Options.background_alpha != 1:
        ActiveSkin.background.draw(
            background_cover, z=get_z_alt(LAYER_BACKGROUND_COVER).tuple, a=1 - Options.background_alpha
        )


def draw_dead(life, dead_time, background_cover, dead_effect_quads):
    if life == 0:
        if not ActiveSkin.dead_effect.is_available:
            ActiveSkin.background.draw(background_cover, z=get_z_alt(LAYER_BACKGROUND).tuple, a=0.3)
        else:
            a = unlerp_clamped(0, 0.25, time() - dead_time)

            for k in range(len(dead_effect_quads)):
                ActiveSkin.dead_effect.draw(quad=dead_effect_quads[k], z=get_z_alt(LAYER_BACKGROUND).tuple, a=a)


def draw_auto_play(ui_layout):
    if time() < 0:
        return
    if Options.custom_tag and is_watch() and not is_replay() and Options.hide_ui < 2:
        layout = ui_layout.custom_tag
        a = 0.8 * (cos(time() * pi) + 1) / 2
        ActiveSkin.auto_live.draw(layout, z=get_z_alt(LAYER_JUDGMENT).tuple, a=a)


def draw_life_bar(
    life,
    last_time,
    ui_layout,
    alpha,
):
    if Options.hide_ui >= 2:
        return
    alpha = alpha * (1.0 - SkillHide.secondary_hidden)
    if alpha <= 0:
        return
    if not ActiveSkin.ui_number.available:
        return
    if not Options.custom_life_bar:
        return
    if not ActiveSkin.life.bar.available:
        return
    draw_life_number(life, get_z_alt(LAYER_JUDGMENT, 4).tuple, alpha)
    bar_layout = ui_layout.life_bar
    if is_multiplayer():
        ActiveSkin.life.bar.get_sprite(LifeBarType.DISABLE, life).draw(
            bar_layout, z=get_z_alt(LAYER_JUDGMENT, 3).tuple, a=alpha
        )
    elif last_time < time() and is_play():
        ActiveSkin.life.bar.get_sprite(LifeBarType.SKIP, life).draw(
            bar_layout, z=get_z_alt(LAYER_JUDGMENT, 3).tuple, a=alpha
        )
    else:
        ActiveSkin.life.bar.get_sprite(LifeBarType.PAUSE, life).draw(
            bar_layout, z=get_z_alt(LAYER_JUDGMENT, 3).tuple, a=alpha
        )
    ActiveSkin.life.bar.get_sprite(LifeBarType.BACKGROUND, life).draw(bar_layout, z=LAYER_JUDGMENT, a=alpha)
    gauge_layout = layout_life_gauge(life)
    ActiveSkin.life.gauge.get_sprite(life).draw(gauge_layout, get_z_alt(LAYER_JUDGMENT, 1).tuple, alpha)
    if life > 0:
        edge_layout = layout_life_gauge(life, True)
        ActiveSkin.life.gauge.get_sprite(life, True).draw(edge_layout, get_z_alt(LAYER_JUDGMENT, 2).tuple, alpha)


def draw_score_bar(
    score,
    note_score,
    note_time,
    ui_layout,
    alpha,
):
    if Options.hide_ui >= 2:
        return
    alpha = alpha * (1.0 - SkillHide.primary_hidden)
    if alpha <= 0:
        return
    if not ActiveSkin.ui_number.available:
        return
    if not Options.custom_score_bar:
        return
    if not ActiveSkin.score.available:
        return
    draw_score_bar_number(score, get_z_alt(LAYER_JUDGMENT, 4).tuple, alpha)
    draw_score_bar_raw_number(
        number=note_score, z=get_z_alt(LAYER_JUDGMENT, 4).tuple, time=time() - note_time, alpha=alpha
    )
    bar_layout = ui_layout.score_bar
    ActiveSkin.score.bar.draw(bar_layout, z=get_z_alt(LAYER_JUDGMENT, 2).tuple, a=alpha)
    ActiveSkin.score.panel.draw(bar_layout, z=get_z_alt(LAYER_JUDGMENT, 4).tuple, a=alpha)
    rank = get_score_rank(score)
    if score > 0:
        gauge = get_gauge_progress(score)
        ActiveSkin.score.gauge.normal.draw(ui_layout.score_gauge, z=get_z_alt(LAYER_JUDGMENT).tuple, a=alpha)

        gauge_mask_layout = layout_score_gauge(gauge, ScoreGaugeType.MASK)
        ActiveSkin.score.gauge.mask.draw(gauge_mask_layout, z=get_z_alt(LAYER_JUDGMENT, 1).tuple, a=alpha)
    else:
        ActiveSkin.score.gauge.cover.draw(ui_layout.score_gauge, z=get_z_alt(LAYER_JUDGMENT).tuple, a=alpha)
    if LevelConfig.ui_version == Version.v3 or rank != ScoreRankType.D:
        ActiveSkin.score.rank.get_sprite(rank).draw(ui_layout.score_rank, z=get_z_alt(LAYER_JUDGMENT, 4).tuple, a=alpha)
    if LevelConfig.ui_version == Version.v3:
        ActiveSkin.score.rank_text.get_sprite(rank).draw(
            ui_layout.score_rank_text, z=get_z_alt(LAYER_JUDGMENT, 4).tuple, a=alpha
        )


def get_gauge_progress(score):
    xp = (0, 20000, 400000, 620000, 840000, 1000000)
    fp = (
        0,
        0.45,
        0.6,
        0.75,
        0.9,
        1.0,
    )

    return interp(xp, fp, score)


def get_score_rank(score):
    if score >= 840000:
        return ScoreRankType.S
    elif score >= 620000:
        return ScoreRankType.A
    elif score >= 400000:
        return ScoreRankType.B
    elif score >= 20000:
        return ScoreRankType.C
    else:
        return ScoreRankType.D


def play_lane_hit_effects(lane: float, sfx: bool = True, *, transform: AffineTransform2d):
    if sfx or not Options.prevent_empty_lane_sfx:
        play_lane_sfx(lane)
    play_lane_particle(lane, transform)


def play_lane_sfx(lane: float):
    if Options.sfx_enabled:
        Effects.stage.play(SFX_DISTANCE)


def schedule_lane_sfx(lane: float, target_time: float):
    if Options.sfx_enabled:
        Effects.stage.schedule(target_time, SFX_DISTANCE)


def play_lane_particle(lane: float, transform: AffineTransform2d):
    if Options.lane_effect_enabled:
        layout = transform.transform_quad(layout_particle_lane(lane, 0.5))
        ActiveParticles.lane.spawn(layout, duration=0.3 / Options.effect_animation_speed)
