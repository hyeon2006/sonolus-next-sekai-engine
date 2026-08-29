from __future__ import annotations

from enum import IntEnum
from math import atan, ceil, cos, floor, log, pi, sin
from typing import Protocol, assert_never, cast

from sonolus.script.archetype import EntityRef, get_archetype_by_name
from sonolus.script.debug import static_error
from sonolus.script.globals import level_data, level_memory
from sonolus.script.interval import clamp, lerp, remap, unlerp
from sonolus.script.num import Num
from sonolus.script.quad import Quad, QuadLike, Rect
from sonolus.script.record import Record
from sonolus.script.runtime import aspect_ratio, background, is_play, is_watch, screen, set_background, time
from sonolus.script.values import swap
from sonolus.script.vec import Vec2

from sekai.lib import archetype_names
from sekai.lib.baseevent import get_event_as, query_event_list
from sekai.lib.ease import EaseType, ease
from sekai.lib.level_config import LevelConfig
from sekai.lib.options import Options, StageCoverNoteSpeedCompensation
from sekai.lib.timescale import CompositeTime

LANE_T = 47 / 850
LANE_B = 1176 / 850

NOTE_H = 75 / 850 / 2
NOTE_EDGE_W = 0.25
NOTE_SLIM_EDGE_W = 0.125

TARGET_ASPECT_RATIO = 16 / 9

TEST_ASPECT_SCALE = 0.5

FIELD_T_FACTOR = 0.5 + 1.15875 * (47 / 1176)
FIELD_B_FACTOR = 0.5 - 1.15875 * (803 / 1176)
FIELD_W_FACTOR = (1.15875 * (1420 / 1176)) / TARGET_ASPECT_RATIO / 12

# Value between 0 and 1 where smaller values mean a 'harsher' approach with more acceleration.
APPROACH_SCALE = 1.06**-45

# Value above 1 where we cut off drawing sprites. Doesn't really matter as long as it's high enough,
# such that something like a flick arrow below the judge line isn't obviously suddenly cut off.
DEFAULT_APPROACH_CUTOFF = 5

# Avoid numerical instability at low tilt in the approach curve
APPROACH_TILT_LERP_MIN = 0.05

# Stage width at 0 tilt
STAGE_WIDTH_MID = (APPROACH_SCALE + 1) / 2

# As tilt decreases, the perspective vanishing point (where the width factor reaches 0) recedes
# upward and the stage top is extended toward it. This floors the effective tilt used for that
# extent so it stays finite (instead of diverging) as tilt approaches 0.
STAGE_TILT_VANISH_MIN = 0.2


class FlickDirection(IntEnum):
    UP_OMNI = 0
    UP_LEFT = 1
    UP_RIGHT = 2
    DOWN_OMNI = 3
    DOWN_LEFT = 4
    DOWN_RIGHT = 5


class ZoomVerticalAlign(IntEnum):
    DEFAULT = 0
    CENTER = 1


class StageTransformAnchor(IntEnum):
    DEFAULT = 0
    CENTER = 1


@level_data
class Layout:
    field_w: float
    field_h: float
    approach_start: float
    cover_depth: float
    cutoff_depth: float
    flick_speed_threshold: float
    initial_background: Quad


@level_memory
class DynamicLayout:
    t: float
    w_scale: float
    h_scale: float
    x_translate: float
    rotate: float
    stage_tilt: float
    size_zoom: float
    note_h: float
    scaled_note_h: float
    progress_start: float
    progress_cutoff: float
    width_offset: float
    lane_t: float
    lane_b: float
    stage_lane_t: float
    stage_lane_b: float


class CameraInfo(Record):
    lane: float
    size: float
    zoom: float
    zoom_target_lane: float  # lane-space, for the preview timeline marker only
    zoom_target: Vec2  # screen-space zoom target
    zoom_anchor: Vec2  # screen-space anchor (encodes the vertical align)
    rotate: float
    stage_tilt: float


class AffineTransform2d(Record):
    a00: float
    a01: float
    a02: float
    a10: float
    a11: float
    a12: float

    def apply(self, p: Vec2) -> Vec2:
        return Vec2(
            self.a00 * p.x + self.a01 * p.y + self.a02,
            self.a10 * p.x + self.a11 * p.y + self.a12,
        )

    def apply_inverse(self, p: Vec2) -> Vec2:
        det = self.a00 * self.a11 - self.a01 * self.a10
        dx = p.x - self.a02
        dy = p.y - self.a12
        return Vec2(
            (self.a11 * dx - self.a01 * dy) / det,
            (self.a00 * dy - self.a10 * dx) / det,
        )

    def transform_quad(self, q: QuadLike) -> Quad:
        return Quad(
            bl=self.apply(q.bl),
            br=self.apply(q.br),
            tl=self.apply(q.tl),
            tr=self.apply(q.tr),
        )


IDENTITY_AFFINE_TRANSFORM = AffineTransform2d(a00=1.0, a01=0.0, a02=0.0, a10=0.0, a11=1.0, a12=0.0)


class StageTransform(Record):
    """A per-stage rigid post-map in camera screen space.

    Rotate by `sr` about pivot `(px, py)` then translate `(tx, ty)`.
    """

    sr: float
    px: float
    py: float
    tx: float
    ty: float

    def transform(self) -> AffineTransform2d:
        cs = cos(self.sr)
        sn = sin(self.sr)
        return AffineTransform2d(
            a00=cs,
            a01=sn,
            a02=self.px * (1 - cs) - sn * self.py + self.tx,
            a10=-sn,
            a11=cs,
            a12=self.py * (1 - cs) + sn * self.px + self.ty,
        )


def identity_stage_transform() -> StageTransform:
    return StageTransform(sr=0.0, px=0.0, py=0.0, tx=0.0, ty=0.0)


def stage_transform_is_identity(st: StageTransform) -> bool:
    return st.sr == 0.0 and st.tx == 0.0 and st.ty == 0.0


def stage_rotation_pivot(camera: LayoutTransform, judge_depth: float) -> Vec2:
    basis_depth = lerp(judge_depth, 0.0, camera.stage_tilt)
    return Vec2(
        camera.x_translate,
        basis_depth * camera.h_scale + camera.t,
    ).rotate(-camera.rotate)


def compute_stage_transform(
    camera: LayoutTransform,
    stage_rotate: float,
    x_lane_translate: float,
    y_lane_translate: float,
    mask_lane: float,
    center_weight: float = 0.0,
) -> StageTransform:
    travel = approach_at_tilt(1.0, camera.stage_tilt)
    width = width_factor_at_tilt(travel, camera.stage_tilt)
    judge_center = Vec2(
        mask_lane * width * camera.w_scale + camera.x_translate,
        travel * camera.h_scale + camera.t,
    ).rotate(-camera.rotate)
    base_t = Layout.field_h * FIELD_T_FACTOR
    base_h = Layout.field_h * FIELD_B_FACTOR - base_t
    center_judge_y = camera.h_scale * (travel + base_t / base_h)
    offset = Vec2(
        x_lane_translate * camera.w_scale,
        y_lane_translate * camera.w_scale - center_weight * center_judge_y,
    ).rotate(-camera.rotate)
    pivot = stage_rotation_pivot(camera, travel)
    cs = cos(stage_rotate)
    sn = sin(stage_rotate)
    dx = judge_center.x - pivot.x
    dy = judge_center.y - pivot.y
    tx = offset.x + (1 - cs) * dx - sn * dy
    ty = offset.y + (1 - cs) * dy + sn * dx
    return StageTransform(sr=stage_rotate, px=pivot.x, py=pivot.y, tx=tx, ty=ty)


def blend_stage_transform(a: StageTransform, b: StageTransform, frac: float) -> StageTransform:
    return StageTransform(
        sr=lerp(a.sr, b.sr, frac),
        px=lerp(a.px, b.px, frac),
        py=lerp(a.py, b.py, frac),
        tx=lerp(a.tx, b.tx, frac),
        ty=lerp(a.ty, b.ty, frac),
    )


def stage_aspect_ratio_locked() -> bool:
    return Options.lock_stage_aspect_ratio or LevelConfig.has_stage_transforms


def stage_cover_amount() -> float:
    if LevelConfig.has_stage_transforms:
        return 0.0
    return Options.stage_cover


def hidden_amount() -> float:
    if LevelConfig.has_stage_transforms:
        return 0.0
    return Options.hidden


def init_layout():
    if stage_aspect_ratio_locked():
        if aspect_ratio() > TARGET_ASPECT_RATIO:
            field_w = screen().h * TARGET_ASPECT_RATIO
            field_h = screen().h
        else:
            field_w = screen().w
            field_h = screen().w / TARGET_ASPECT_RATIO
    else:
        field_w = screen().w
        field_h = screen().h

    Layout.field_w = field_w
    Layout.field_h = field_h

    Layout.approach_start = 0.0

    # Fixed approach-curve depths for the cover/spawn and far cutoff boundaries. These are
    # tilt-independent (they pin screen positions); refresh_layout() converts them to the
    # equivalent progress bounds under the current tilt each frame.
    cover = stage_cover_amount()
    hidden = hidden_amount()
    if cover:
        Layout.cover_depth = lerp(APPROACH_SCALE, 1.0, cover)
    else:
        Layout.cover_depth = APPROACH_SCALE
    if hidden:
        Layout.cutoff_depth = lerp(1.0, APPROACH_SCALE, hidden)
    else:
        Layout.cutoff_depth = DEFAULT_APPROACH_CUTOFF

    if cover and Options.stage_cover_scroll_speed_compensation != StageCoverNoteSpeedCompensation.OFF:
        target_travel = lerp(APPROACH_SCALE, 1.0, cover)
        candidate = inverse_approach_untilted(target_travel)
        Layout.approach_start = clamp(candidate, 0, 0.99)

    bg = background()
    if is_play() or is_watch():
        background_zoom = background_camera_zoom(bg)
    else:
        background_zoom = 1.0
    Layout.initial_background = bg.scale_centered(Vec2(background_zoom, background_zoom))

    refresh_layout()

    Layout.flick_speed_threshold = 2 * DynamicLayout.w_scale


class CameraChangeLike(Protocol):
    time: float
    lane: float
    size: float
    zoom: float
    zoom_target_lane: float
    zoom_target_y: float
    zoom_vertical_align: ZoomVerticalAlign
    rotate: float
    stage_tilt: float
    ease: EaseType
    next_ref: EntityRef
    prev_ref: EntityRef

    @classmethod
    def at(cls, index: int) -> CameraChangeLike: ...

    @property
    def index(self) -> int: ...


class InitializationLike(Protocol):
    first_camera_ref: EntityRef

    @classmethod
    def at(cls, index: int) -> InitializationLike: ...


def _camera_change_archetype() -> type[CameraChangeLike]:
    return cast(type[CameraChangeLike], get_archetype_by_name(archetype_names.CAMERA_CHANGE))


def _initialization_archetype() -> type[InitializationLike]:
    return cast(type[InitializationLike], get_archetype_by_name(archetype_names.INITIALIZATION))


def max_camera_abs_rotation() -> float:
    result = 0.0
    first_camera_ref = _initialization_archetype().at(0).first_camera_ref
    if first_camera_ref.index <= 0:
        return result
    camera_archetype = _camera_change_archetype()
    ref = +first_camera_ref
    while ref.index > 0:
        camera = get_event_as(ref, camera_archetype)
        result = max(result, abs(camera.rotate))
        ref.index = camera.next_ref.index
    return result


def background_camera_zoom(bg: QuadLike) -> float:
    first_camera_ref = _initialization_archetype().at(0).first_camera_ref
    if first_camera_ref.index <= 0:
        return 1.0
    a = aspect_ratio()
    b = 1.0
    bw = abs(bg.br.x - bg.bl.x) / 2
    bh = abs(bg.tl.y - bg.bl.y) / 2

    theta = min(max_camera_abs_rotation(), pi / 2)
    diag = (a * a + b * b) ** 0.5
    cover_x = diag if theta >= atan(b / a) else a * cos(theta) + b * sin(theta)
    cover_y = diag if theta >= atan(a / b) else a * sin(theta) + b * cos(theta)

    raised_target = camera_zoom_target_at(0.0, 6.0, 0.0, 0.5, 0.0)
    raised_anchor = camera_zoom_anchor(ZoomVerticalAlign.CENTER)
    lane_target = camera_zoom_target_at(0.0, 6.0, 1.0, 0.0, 1.0)
    lane_anchor = camera_zoom_anchor(ZoomVerticalAlign.DEFAULT)
    margin_x = max(abs(raised_target.x - raised_anchor.x), abs(lane_target.x - lane_anchor.x))
    margin_y = max(abs(raised_target.y - raised_anchor.y), abs(lane_target.y - lane_anchor.y))

    return max((cover_x + margin_x) / bw, (cover_y + margin_y) / bh, 1.0)


def get_camera_info(target_time: float | None = None, left_limit: bool = False) -> CameraInfo:
    result = +CameraInfo
    first_camera_ref = _initialization_archetype().at(0).first_camera_ref
    if first_camera_ref.index <= 0:
        result @= CameraInfo(
            lane=0.0,
            size=6.0,
            zoom=1.0,
            zoom_target_lane=0.0,
            zoom_target=Vec2(0.0, 0.0),
            zoom_anchor=Vec2(0.0, 0.0),
            rotate=0.0,
            stage_tilt=1.0,
        )
        return result
    t = time() if target_time is None else target_time
    camera_a_ref, camera_b_ref = query_event_list(first_camera_ref, t, lambda e: e.time)
    camera_archetype = _camera_change_archetype()
    if left_limit and camera_a_ref.index > 0:
        camera_curr = get_event_as(camera_a_ref, camera_archetype)
        if camera_curr.time == t:
            camera_probe_ref = +camera_curr.prev_ref
            while camera_probe_ref.index > 0:
                if get_event_as(camera_probe_ref, camera_archetype).time != t:
                    break
                camera_a_ref.index = camera_probe_ref.index
                camera_probe_ref.index = get_event_as(camera_probe_ref, camera_archetype).prev_ref.index
            camera_b_ref.index = camera_a_ref.index
            camera_a_ref.index = camera_probe_ref.index
    if camera_a_ref.index > 0:
        camera_a = get_event_as(camera_a_ref, camera_archetype)
        if camera_b_ref.index > 0:
            camera_b = get_event_as(camera_b_ref, camera_archetype)
            if camera_b.time > camera_a.time:
                p = ease(camera_a.ease, unlerp(camera_a.time, camera_b.time, t))
                ta = camera_zoom_target_at(
                    camera_a.lane, camera_a.size, camera_a.zoom_target_lane, camera_a.zoom_target_y, camera_a.stage_tilt
                )
                tb = camera_zoom_target_at(
                    camera_b.lane, camera_b.size, camera_b.zoom_target_lane, camera_b.zoom_target_y, camera_b.stage_tilt
                )
                aa = camera_zoom_anchor(camera_a.zoom_vertical_align)
                ab = camera_zoom_anchor(camera_b.zoom_vertical_align)
                result @= CameraInfo(
                    lane=lerp(camera_a.lane, camera_b.lane, p),
                    size=lerp(camera_a.size, camera_b.size, p),
                    zoom=lerp(camera_a.zoom, camera_b.zoom, p),
                    zoom_target_lane=lerp(camera_a.zoom_target_lane, camera_b.zoom_target_lane, p),
                    zoom_target=Vec2(lerp(ta.x, tb.x, p), lerp(ta.y, tb.y, p)),
                    zoom_anchor=Vec2(lerp(aa.x, ab.x, p), lerp(aa.y, ab.y, p)),
                    rotate=lerp(camera_a.rotate, camera_b.rotate, p),
                    stage_tilt=lerp(camera_a.stage_tilt, camera_b.stage_tilt, p),
                )
                return result
        result @= CameraInfo(
            lane=camera_a.lane,
            size=camera_a.size,
            zoom=camera_a.zoom,
            zoom_target_lane=camera_a.zoom_target_lane,
            zoom_target=camera_zoom_target_at(
                camera_a.lane, camera_a.size, camera_a.zoom_target_lane, camera_a.zoom_target_y, camera_a.stage_tilt
            ),
            zoom_anchor=camera_zoom_anchor(camera_a.zoom_vertical_align),
            rotate=camera_a.rotate,
            stage_tilt=camera_a.stage_tilt,
        )
        return result
    if camera_b_ref.index > 0:
        camera_b = get_event_as(camera_b_ref, camera_archetype)
        result @= CameraInfo(
            lane=camera_b.lane,
            size=camera_b.size,
            zoom=camera_b.zoom,
            zoom_target_lane=camera_b.zoom_target_lane,
            zoom_target=camera_zoom_target_at(
                camera_b.lane, camera_b.size, camera_b.zoom_target_lane, camera_b.zoom_target_y, camera_b.stage_tilt
            ),
            zoom_anchor=camera_zoom_anchor(camera_b.zoom_vertical_align),
            rotate=camera_b.rotate,
            stage_tilt=camera_b.stage_tilt,
        )
        return result
    result @= CameraInfo(
        lane=0.0,
        size=6.0,
        zoom=1.0,
        zoom_target_lane=0.0,
        zoom_target=Vec2(0.0, 0.0),
        zoom_anchor=Vec2(0.0, 0.0),
        rotate=0.0,
        stage_tilt=1.0,
    )
    return result


def get_next_camera_event_time(t: float) -> float:
    result = 1e8
    first_camera_ref = _initialization_archetype().at(0).first_camera_ref
    if first_camera_ref.index > 0:
        _, b_ref = query_event_list(first_camera_ref, t, lambda e: e.time)
        if b_ref.index > 0:
            result = min(result, get_event_as(b_ref, _camera_change_archetype()).time)
    return result


def test_aspect_active() -> bool:
    return Options.test_aspect_ratio and (is_watch() or (is_play() and Options.allow_debug_options_in_play_mode))


def refresh_layout():
    camera = +CameraInfo
    if is_play() or is_watch():
        camera @= get_camera_info()
    else:
        camera @= CameraInfo(
            lane=0.0,
            size=6.0,
            zoom=1.0,
            zoom_target_lane=0.0,
            zoom_target=Vec2(0.0, 0.0),
            zoom_anchor=Vec2(0.0, 0.0),
            rotate=0.0,
            stage_tilt=1.0,
        )

    base = base_layout_transform(camera)
    DynamicLayout.t = base.t
    DynamicLayout.w_scale = base.w_scale
    DynamicLayout.h_scale = base.h_scale
    DynamicLayout.x_translate = base.x_translate
    DynamicLayout.rotate = base.rotate
    DynamicLayout.stage_tilt = base.stage_tilt
    DynamicLayout.size_zoom = base.size_zoom
    tilt = current_stage_tilt()

    DynamicLayout.width_offset = (1 - tilt) * STAGE_WIDTH_MID
    vanish_tilt = max(tilt, STAGE_TILT_VANISH_MIN)
    vanish_ext = (1 - vanish_tilt) * STAGE_WIDTH_MID / vanish_tilt
    DynamicLayout.lane_t = LANE_T - vanish_ext
    DynamicLayout.lane_b = LANE_B + vanish_ext
    if LevelConfig.dynamic_stages:
        DynamicLayout.stage_lane_t = LANE_T - vanish_ext * 0.9
        DynamicLayout.stage_lane_b = LANE_B + vanish_ext + 3
    else:
        DynamicLayout.stage_lane_t = LANE_T - vanish_ext
        DynamicLayout.stage_lane_b = LANE_B + vanish_ext

    base_note_h = NOTE_H * (0.6 * base.size_zoom + 0.4)
    flat_note_h = STAGE_WIDTH_MID * DynamicLayout.w_scale / (2 * abs(DynamicLayout.h_scale))
    DynamicLayout.note_h = lerp(flat_note_h, base_note_h, tilt)

    if is_play() or is_watch():
        apply_camera_zoom(base, camera.zoom, camera.zoom_target, camera.zoom_anchor, camera.rotate)

    if test_aspect_active():
        DynamicLayout.t = DynamicLayout.t * TEST_ASPECT_SCALE
        DynamicLayout.w_scale = DynamicLayout.w_scale * TEST_ASPECT_SCALE
        DynamicLayout.h_scale = DynamicLayout.h_scale * TEST_ASPECT_SCALE
        DynamicLayout.x_translate = DynamicLayout.x_translate * TEST_ASPECT_SCALE
        set_background(background().scale(Vec2(TEST_ASPECT_SCALE, TEST_ASPECT_SCALE)))

    DynamicLayout.scaled_note_h = DynamicLayout.note_h * DynamicLayout.h_scale

    if stage_cover_amount():
        DynamicLayout.progress_start = inverse_approach_tilt(Layout.cover_depth)
    else:
        DynamicLayout.progress_start = inverse_approach_tilt(Layout.cover_depth - vanish_ext)
    DynamicLayout.progress_cutoff = inverse_approach_tilt(Layout.cutoff_depth)


def camera_zoom_target_at(lane: float, size: float, target_lane: float, target_y: float, tilt: float) -> Vec2:
    size_zoom = 6.0 / size
    w = Layout.field_w * FIELD_W_FACTOR * size_zoom
    t_top = Layout.field_h * FIELD_T_FACTOR
    b = Layout.field_h * FIELD_B_FACTOR
    travel = approach_at_tilt(1 - target_y, tilt)
    target_total_lane = lane + target_lane
    return Vec2(target_total_lane * width_factor_at_tilt(travel, tilt) * w - lane * w, travel * (b - t_top) + t_top)


def camera_zoom_anchor(align: ZoomVerticalAlign) -> Vec2:
    if align == ZoomVerticalAlign.CENTER:
        anchor_y = 0.0
    else:
        anchor_y = Layout.field_h * FIELD_B_FACTOR
    return Vec2(0.0, anchor_y)


def apply_camera_zoom(transform: LayoutTransform, zoom: float, target: Vec2, anchor: Vec2, rotate: float = 0.0):
    zoomed = zoomed_layout_transform(transform, zoom, target, anchor, rotate)
    DynamicLayout.t = zoomed.t
    DynamicLayout.w_scale = zoomed.w_scale
    DynamicLayout.h_scale = zoomed.h_scale
    DynamicLayout.x_translate = zoomed.x_translate
    DynamicLayout.rotate = zoomed.rotate
    bg = Layout.initial_background
    rot = -rotate
    set_background(
        Quad(
            bl=Vec2(zoom * (bg.bl.x - target.x) + anchor.x, zoom * (bg.bl.y - target.y) + anchor.y).rotate(rot),
            br=Vec2(zoom * (bg.br.x - target.x) + anchor.x, zoom * (bg.br.y - target.y) + anchor.y).rotate(rot),
            tl=Vec2(zoom * (bg.tl.x - target.x) + anchor.x, zoom * (bg.tl.y - target.y) + anchor.y).rotate(rot),
            tr=Vec2(zoom * (bg.tr.x - target.x) + anchor.x, zoom * (bg.tr.y - target.y) + anchor.y).rotate(rot),
        )
    )


def current_stage_tilt() -> float:
    if is_play() or is_watch():
        return DynamicLayout.stage_tilt
    return 1.0


def approach_curve_base(x: float) -> float:
    if Options.alternative_approach_curve:
        d_0 = 1 / APPROACH_SCALE
        d_1 = 2.5
        v_1 = (d_0 - d_1) / d_1**2
        d = 1 / lerp(d_0, d_1, x) if x < 1 else 1 / d_1 + v_1 * (x - 1)
        return remap(1 / d_0, 1 / d_1, APPROACH_SCALE, 1, d)
    return APPROACH_SCALE ** (1 - x)


def inverse_approach_curve_base(approach_value: float) -> float:
    if Options.alternative_approach_curve:
        d_0 = 1 / APPROACH_SCALE
        d_1 = 2.5
        v_1 = (d_0 - d_1) / d_1**2
        d = remap(APPROACH_SCALE, 1, 1 / d_0, 1 / d_1, approach_value)
        if d <= 1 / d_1:
            raw = (1 / d - d_0) / (d_1 - d_0)
        else:
            raw = 1 + (d - 1 / d_1) / v_1
    else:
        raw = 1 - log(approach_value) / log(APPROACH_SCALE)
    return raw


def approach_slice_window(tilt: float, spawn_depth: float) -> tuple[float, float]:
    w_judge = width_factor_at_tilt(1.0, tilt)
    spawn_fraction = tilt * (1.0 - spawn_depth) / w_judge
    slice_spawn = 1.0 - spawn_fraction
    return inverse_approach_curve_base(slice_spawn), slice_spawn


def approach_slice(progress: float, tilt: float, spawn_depth: float) -> float:
    start, slice_spawn = approach_slice_window(tilt, spawn_depth)
    travel = approach_curve_base(lerp(start, 1.0, progress))
    return remap(slice_spawn, 1.0, spawn_depth, 1.0, travel)


def inverse_approach_slice(travel: float, tilt: float, spawn_depth: float) -> float:
    start, slice_spawn = approach_slice_window(tilt, spawn_depth)
    raw = remap(spawn_depth, 1.0, slice_spawn, 1.0, travel)
    return unlerp(start, 1.0, inverse_approach_curve_base(raw))


def approach_at_tilt(progress: float, tilt: float) -> float:
    if tilt >= 1.0:
        return approach_curve_base(lerp(Layout.approach_start, 1.0, progress))
    spawn_depth = approach_curve_base(Layout.approach_start)
    if tilt <= 0.0:
        return lerp(spawn_depth, 1.0, progress)
    if tilt < APPROACH_TILT_LERP_MIN:
        linear = lerp(spawn_depth, 1.0, progress)
        slice_at_floor = approach_slice(progress, APPROACH_TILT_LERP_MIN, spawn_depth)
        return lerp(linear, slice_at_floor, tilt / APPROACH_TILT_LERP_MIN)
    return approach_slice(progress, tilt, spawn_depth)


def approach(progress: float) -> float:
    return approach_at_tilt(progress, current_stage_tilt())


def inverse_approach_untilted(approach_value: float) -> float:
    return unlerp(Layout.approach_start, 1.0, inverse_approach_curve_base(approach_value))


def inverse_approach_tilt(approach_value: float) -> float:
    tilt = current_stage_tilt()
    if tilt >= 1.0:
        return inverse_approach_untilted(approach_value)
    spawn_depth = approach_curve_base(Layout.approach_start)
    if tilt < APPROACH_TILT_LERP_MIN:
        lo = -8.0
        hi = 8.0
        for _ in range(20):
            mid = (lo + hi) / 2
            too_low = approach_at_tilt(mid, tilt) < approach_value
            lo = mid if too_low else lo
            hi = hi if too_low else mid
        return (lo + hi) / 2
    return inverse_approach_slice(approach_value, tilt, spawn_depth)


def progress_to(
    to_time: float | CompositeTime,
    now: float | CompositeTime,
    force_speed: float = 0,
) -> float:
    p = preempt_time(force_speed)
    match (to_time, now):
        case (CompositeTime(), CompositeTime()):
            return ((now.base - to_time.base) + now.delta - to_time.delta + p) / p
        case (Num(), Num()):
            return unlerp(to_time - p, to_time, now)
        case _:
            static_error("Unexpected types for progress_to")


def preempt_time(force_speed: float = 0) -> float:
    if force_speed > 0:
        return lerp(0.35, 4, unlerp(12, 1, force_speed) ** 1.31)
    raw = lerp(0.35, 4, unlerp(12, 1, Options.note_speed) ** 1.31)
    if Options.stage_cover_scroll_speed_compensation == StageCoverNoteSpeedCompensation.FIXED_ONLY:
        return raw * (1 - Layout.approach_start)
    return raw


def get_alpha(target_time: float, now: float | None = None) -> float:
    return 1.0


def width_factor_at_tilt(depth: float, tilt: float) -> float:
    return tilt * depth + (1 - tilt) * STAGE_WIDTH_MID


def tilt_width_factor(depth: float) -> float:
    return current_stage_tilt() * depth + DynamicLayout.width_offset


def tilt_depth(line_y: float, travel: float) -> float:
    return travel + (line_y - 1.0) * lerp(1.0, travel, current_stage_tilt())


def tilt_widened_edge(bottom_edge: float, top_edge: float) -> float:
    return lerp(bottom_edge, top_edge, current_stage_tilt())


def transform_vec(v: Vec2) -> Vec2:
    return Vec2(
        v.x * DynamicLayout.w_scale + DynamicLayout.x_translate,
        v.y * DynamicLayout.h_scale + DynamicLayout.t,
    ).rotate(-DynamicLayout.rotate)


def transform_quad(q: QuadLike) -> Quad:
    return Quad(
        bl=transform_vec(q.bl),
        br=transform_vec(q.br),
        tl=transform_vec(q.tl),
        tr=transform_vec(q.tr),
    )


def transformed_vec_at(lane: float, travel: float = 1.0) -> Vec2:
    return transform_vec(Vec2(lane * tilt_width_factor(travel), travel))


def pre_rotation_vec_at(lane: float, travel: float = 1.0) -> Vec2:
    return Vec2(
        lane * tilt_width_factor(travel) * DynamicLayout.w_scale + DynamicLayout.x_translate,
        travel * DynamicLayout.h_scale + DynamicLayout.t,
    )


def touch_to_lane(pos: Vec2, transform: AffineTransform2d) -> float:
    unrotated = transform.apply_inverse(pos).rotate(DynamicLayout.rotate)
    y_raw = (unrotated.y - DynamicLayout.t) / DynamicLayout.h_scale
    x_raw = (unrotated.x - DynamicLayout.x_translate) / DynamicLayout.w_scale
    width = tilt_width_factor(y_raw)
    if -1e-6 < width < 1e-6:
        width = 1e-6 if width >= 0 else -1e-6
    return x_raw / width


def perspective_vec(x: float, y: float, travel: float = 1.0) -> Vec2:
    return transform_vec(Vec2(x * tilt_width_factor(y * travel), y * travel))


def perspective_rect(l: float, r: float, t: float, b: float, travel: float = 1.0) -> Quad:
    depth_b = tilt_depth(b, travel)
    depth_t = tilt_depth(t, travel)
    wb = tilt_width_factor(depth_b)
    wt = tilt_width_factor(depth_t)
    return transform_quad(
        Quad(
            bl=Vec2(l * wb, depth_b),
            br=Vec2(r * wb, depth_b),
            tl=Vec2(l * wt, depth_t),
            tr=Vec2(r * wt, depth_t),
        )
    )


def layout_sekai_stage() -> Quad:
    w = (2048 / 1420) * 12 / 2
    h = 1176 / 850
    rect = Rect(l=-w, r=w, t=LANE_T, b=LANE_T + h)
    return transform_quad(rect)


def layout_stage_lane_by_edges(l: float, r: float, y_offset: float = 0.0) -> Quad:
    return perspective_rect(
        l=l, r=r, t=DynamicLayout.stage_lane_t, b=DynamicLayout.stage_lane_b, travel=approach(1 - y_offset)
    )


def layout_particle_lane(lane: float, size: float, y_offset: float = 0.0) -> Quad:
    return perspective_rect(
        l=lane - size, r=lane + size, t=DynamicLayout.lane_t, b=DynamicLayout.lane_b, travel=approach(1 - y_offset)
    )


def layout_stage_cover(l: float = -6, r: float = 6) -> Quad:
    b = lerp(APPROACH_SCALE, 1.0, stage_cover_amount())
    return perspective_rect(
        l=l,
        r=r,
        t=DynamicLayout.lane_t,
        b=b,
    )


def layout_stage_cover_and_line(l: float = -6, r: float = 6) -> tuple[Quad, Quad]:
    b = lerp(APPROACH_SCALE, 1.0, stage_cover_amount())
    cover_b = b + 0.002
    return perspective_rect(
        l=l,
        r=r,
        t=DynamicLayout.lane_t,
        b=cover_b,
    ), perspective_rect(
        l=l,
        r=r,
        t=cover_b,
        b=b,
    )


def layout_full_width_stage_cover() -> Quad:
    pre_b = lerp(APPROACH_SCALE, 1.0, stage_cover_amount()) * DynamicLayout.h_scale + DynamicLayout.t
    big = 20.0
    rot = -DynamicLayout.rotate
    return Quad(
        bl=Vec2(-big, pre_b).rotate(rot),
        br=Vec2(big, pre_b).rotate(rot),
        tl=Vec2(-big, big).rotate(rot),
        tr=Vec2(big, big).rotate(rot),
    )


def layout_hidden_cover(l: float = -6, r: float = 6) -> Quad:
    b = 1 - DynamicLayout.note_h
    t = min(b, max(lerp(1.0, APPROACH_SCALE, hidden_amount()), lerp(APPROACH_SCALE, 1.0, stage_cover_amount())))
    return perspective_rect(
        l=l,
        r=r,
        t=t,
        b=b,
    )


def layout_fallback_judge_line() -> Quad:
    nh = DynamicLayout.note_h
    return perspective_rect(l=-6, r=6, t=1 - nh, b=1 + nh)


def layout_note_body_by_edges(l: float, r: float, h: float, travel: float):
    return perspective_rect(l=l, r=r, t=1 - h, b=1 + h, travel=travel)


def layout_note_body_slices_by_edges(
    l: float, r: float, h: float, edge_w: float, travel: float
) -> tuple[Quad, Quad, Quad]:
    m = (l + r) / 2
    if r < l:
        # Make the note 0 width; shouldn't normally happen, but in case, we want to handle it gracefully
        l = r = m
    ml = min(l + edge_w, m)
    mr = max(r - edge_w, m)
    return (
        layout_note_body_by_edges(l=l, r=ml, h=h, travel=travel),
        layout_note_body_by_edges(l=ml, r=mr, h=h, travel=travel),
        layout_note_body_by_edges(l=mr, r=r, h=h, travel=travel),
    )


def layout_regular_note_body(lane: float, size: float, travel: float) -> tuple[Quad, Quad, Quad]:
    return layout_note_body_slices_by_edges(
        l=lane - size + Options.note_margin,
        r=lane + size - Options.note_margin,
        h=DynamicLayout.note_h,
        edge_w=NOTE_EDGE_W,
        travel=travel,
    )


def layout_regular_note_body_fallback(lane: float, size: float, travel: float) -> Quad:
    return layout_note_body_by_edges(
        l=lane - size + Options.note_margin,
        r=lane + size - Options.note_margin,
        h=DynamicLayout.note_h,
        travel=travel,
    )


def layout_slim_note_body(lane: float, size: float, travel: float) -> tuple[Quad, Quad, Quad]:
    return layout_note_body_slices_by_edges(
        l=lane - size + Options.note_margin,
        r=lane + size - Options.note_margin,
        h=DynamicLayout.note_h,  # Height is handled by the sprite rather than being changed here
        edge_w=NOTE_SLIM_EDGE_W,
        travel=travel,
    )


def layout_slim_note_body_fallback(lane: float, size: float, travel: float) -> Quad:
    return layout_note_body_by_edges(
        l=lane - size + Options.note_margin,
        r=lane + size - Options.note_margin,
        h=DynamicLayout.note_h / 2,  # For fallback, we need to halve the height manually engine-side
        travel=travel,
    )


def layout_tick(lane: float, travel: float) -> Quad:
    center = transformed_vec_at(lane, travel)
    h = -DynamicLayout.scaled_note_h * tilt_width_factor(travel)
    rot = -DynamicLayout.rotate
    dx = Vec2(h, 0).rotate(rot)
    dy = Vec2(0, h).rotate(rot)
    return Quad(
        bl=center - dx - dy,
        tl=center - dx + dy,
        tr=center + dx + dy,
        br=center + dx - dy,
    )


def layout_flick_arrow(
    lane: float, size: float, direction: FlickDirection, travel: float, animation_progress: float
) -> Quad:
    match direction:
        case FlickDirection.UP_OMNI:
            is_down = False
            reverse = False
            animation_top_x_offset = 0
        case FlickDirection.DOWN_OMNI:
            is_down = True
            reverse = False
            animation_top_x_offset = 0
        case FlickDirection.UP_LEFT:
            is_down = False
            reverse = False
            animation_top_x_offset = -1
        case FlickDirection.UP_RIGHT:
            is_down = False
            reverse = True
            animation_top_x_offset = 1
        case FlickDirection.DOWN_LEFT:
            is_down = True
            reverse = False
            animation_top_x_offset = 1
        case FlickDirection.DOWN_RIGHT:
            is_down = True
            reverse = True
            animation_top_x_offset = -1
        case _:
            assert_never(direction)
    w = clamp(size, 0, 3) / 2
    base_bl = transformed_vec_at(lane - w, travel)
    base_br = transformed_vec_at(lane + w, travel)
    up = (base_br - base_bl).rotate(pi / 2)
    base_tl = base_bl + up
    base_tr = base_br + up
    offset_scale = animation_progress if not is_down else 1 - animation_progress
    offset = (
        Vec2(animation_top_x_offset * DynamicLayout.w_scale, 2 * DynamicLayout.w_scale).rotate(-DynamicLayout.rotate)
        * offset_scale
        * tilt_width_factor(travel)
    )
    result = Quad(
        bl=base_bl,
        br=base_br,
        tl=base_tl,
        tr=base_tr,
    ).translate(offset)
    if reverse:
        swap(result.bl, result.br)
        swap(result.tl, result.tr)
    return result


def layout_flick_arrow_fallback(
    lane: float, size: float, direction: FlickDirection, travel: float, animation_progress: float
) -> Quad:
    match direction:
        case FlickDirection.UP_OMNI:
            rotation = 0
            animation_top_x_offset = 0
            is_down = False
        case FlickDirection.DOWN_OMNI:
            rotation = pi
            animation_top_x_offset = 0
            is_down = True
        case FlickDirection.UP_LEFT:
            rotation = pi / 6
            animation_top_x_offset = -1
            is_down = False
        case FlickDirection.UP_RIGHT:
            rotation = -pi / 6
            animation_top_x_offset = 1
            is_down = False
        case FlickDirection.DOWN_LEFT:
            rotation = pi * 5 / 6
            animation_top_x_offset = 1
            is_down = True
            lane -= 0.25  # Note: backwards from the regular skin due to how the sprites are designed
        case FlickDirection.DOWN_RIGHT:
            rotation = -pi * 5 / 6
            animation_top_x_offset = -1
            is_down = True
            lane += 0.25
        case _:
            assert_never(direction)

    w = clamp(size / 2, 1, 2)
    offset_scale = animation_progress if not is_down else 1 - animation_progress
    width = tilt_width_factor(travel)
    offset = Vec2(animation_top_x_offset * DynamicLayout.w_scale, 2 * DynamicLayout.w_scale) * offset_scale * width
    return (
        Rect(l=-1, r=1, t=1, b=-1)
        .as_quad()
        .rotate(rotation)
        .scale(Vec2(w, w) * DynamicLayout.w_scale * width)
        .translate(offset)
        .rotate(-DynamicLayout.rotate)
        .translate(transformed_vec_at(lane, travel))
    )


def layout_slot_effect(lane: float, y_offset: float = 0.0) -> Quad:
    travel = approach(1 - y_offset)
    nh = DynamicLayout.note_h
    return perspective_rect(
        l=lane - 0.5,
        r=lane + 0.5,
        b=1 + nh,
        t=1 - nh,
        travel=travel,
    )


def layout_slot_glow_effect(lane: float, size: float, height: float, y_offset: float = 0.0) -> Quad:
    s = 1 + 0.25 * Options.slot_effect_size
    travel = approach(1 - y_offset)
    h = 4.25 * DynamicLayout.w_scale * Options.slot_effect_size * tilt_width_factor(travel)
    up = Vec2(0, h).rotate(-DynamicLayout.rotate)
    l_min = transformed_vec_at(lane - size, travel)
    r_min = transformed_vec_at(lane + size, travel)
    l_max = transformed_vec_at((lane - size) * s, travel) + up
    r_max = transformed_vec_at((lane + size) * s, travel) + up
    return Quad(
        bl=l_min,
        br=r_min,
        tl=lerp(l_min, l_max, height),
        tr=lerp(r_min, r_max, height),
    )


def layout_linear_effect(lane: float, shear: float, y_offset: float = 0.0) -> Quad:
    w = Options.note_effect_size
    travel = approach(1 - y_offset)
    bl = transformed_vec_at(lane - w, travel)
    br = transformed_vec_at(lane + w, travel)
    up = (br - bl).rotate(pi / 2) + (shear + 0.125 * lane) * (br - bl) / 2
    return Quad(
        bl=bl,
        br=br,
        tl=bl + up,
        tr=br + up,
    )


def layout_rotated_linear_effect(lane: float, shear: float, y_offset: float = 0.0) -> Quad:
    w = Options.note_effect_size
    travel = approach(1 - y_offset)
    bl = transformed_vec_at(lane - w, travel)
    br = transformed_vec_at(lane + w, travel)
    up = (br - bl).orthogonal()
    return Quad(
        bl=bl,
        br=br,
        tl=bl + up,
        tr=br + up,
    ).rotate_about(atan(-(shear + 0.125 * lane) / 2), pivot=(bl + br) / 2)


def layout_circular_effect(lane: float, w: float, h: float, y_offset: float = 0.0) -> Quad:
    travel = approach(1 - y_offset)
    width = tilt_width_factor(travel)
    w *= Options.note_effect_size * width
    h *= Options.note_effect_size * DynamicLayout.w_scale / DynamicLayout.h_scale
    t = travel + h * width
    b = travel - h * width
    wb = tilt_width_factor(b)
    wt = tilt_width_factor(t)
    return transform_quad(
        Quad(
            bl=Vec2(lane * wb - w, b),
            br=Vec2(lane * wb + w, b),
            tl=Vec2(lane * wt - w, t),
            tr=Vec2(lane * wt + w, t),
        )
    )


def layout_tick_effect(lane: float, y_offset: float = 0.0) -> Quad:
    travel = approach(1 - y_offset)
    w = 4 * DynamicLayout.w_scale * Options.note_effect_size * tilt_width_factor(travel)
    center = transformed_vec_at(lane, travel)
    rot = -DynamicLayout.rotate
    dx = Vec2(w, 0).rotate(rot)
    dy = Vec2(0, w).rotate(rot)
    return Quad(
        bl=center - dx - dy,
        tl=center - dx + dy,
        tr=center + dx + dy,
        br=center + dx - dy,
    )


def layout_slide_connector_segment(
    start_lane: float,
    start_size: float,
    start_travel: float,
    end_lane: float,
    end_size: float,
    end_travel: float,
) -> Quad:
    if start_travel < end_travel:
        start_lane, end_lane = end_lane, start_lane
        start_size, end_size = end_size, start_size
        start_travel, end_travel = end_travel, start_travel
    return Quad(
        bl=perspective_vec(start_lane - start_size, 1, start_travel),
        br=perspective_vec(start_lane + start_size, 1, start_travel),
        tl=perspective_vec(end_lane - end_size, 1, end_travel),
        tr=perspective_vec(end_lane + end_size, 1, end_travel),
    )


def st_slide_connector_segment(
    start_lane: float,
    start_size: float,
    start_travel: float,
    end_lane: float,
    end_size: float,
    end_travel: float,
    start_transform: AffineTransform2d,
    end_transform: AffineTransform2d,
) -> Quad:
    result = +Quad
    if start_travel >= end_travel:
        result @= Quad(
            bl=start_transform.apply(perspective_vec(start_lane - start_size, 1, start_travel)),
            br=start_transform.apply(perspective_vec(start_lane + start_size, 1, start_travel)),
            tl=end_transform.apply(perspective_vec(end_lane - end_size, 1, end_travel)),
            tr=end_transform.apply(perspective_vec(end_lane + end_size, 1, end_travel)),
        )
    else:
        result @= Quad(
            bl=end_transform.apply(perspective_vec(end_lane - end_size, 1, end_travel)),
            br=end_transform.apply(perspective_vec(end_lane + end_size, 1, end_travel)),
            tl=start_transform.apply(perspective_vec(start_lane - start_size, 1, start_travel)),
            tr=start_transform.apply(perspective_vec(start_lane + start_size, 1, start_travel)),
        )
    return result


def layout_sim_line(
    left_lane: float,
    left_travel: float,
    right_lane: float,
    right_travel: float,
    left_transform: AffineTransform2d,
    right_transform: AffineTransform2d,
) -> Quad:
    ml = +Vec2
    mr = +Vec2
    if left_lane <= right_lane:
        ml @= left_transform.apply(perspective_vec(left_lane, 1, left_travel))
        mr @= right_transform.apply(perspective_vec(right_lane, 1, right_travel))
        ml_travel = left_travel
        mr_travel = right_travel
    else:
        ml @= right_transform.apply(perspective_vec(right_lane, 1, right_travel))
        mr @= left_transform.apply(perspective_vec(left_lane, 1, left_travel))
        ml_travel = right_travel
        mr_travel = left_travel
    ort = (mr - ml).orthogonal().normalize_or_zero()
    ml_h = DynamicLayout.scaled_note_h * tilt_width_factor(ml_travel)
    mr_h = DynamicLayout.scaled_note_h * tilt_width_factor(mr_travel)
    return Quad(
        bl=ml + ort * ml_h,
        br=mr + ort * mr_h,
        tl=ml - ort * ml_h,
        tr=mr - ort * mr_h,
    )


class HitboxTarget(Record):
    l: Vec2
    r: Vec2


class Hitbox(Record):
    target: HitboxTarget
    bounds: Quad


class LayoutTransform(Record):
    t: float
    w_scale: float
    h_scale: float
    x_translate: float
    rotate: float
    stage_tilt: float
    size_zoom: float


def current_layout_transform() -> LayoutTransform:
    return LayoutTransform(
        t=DynamicLayout.t,
        w_scale=DynamicLayout.w_scale,
        h_scale=DynamicLayout.h_scale,
        x_translate=DynamicLayout.x_translate,
        rotate=DynamicLayout.rotate,
        stage_tilt=DynamicLayout.stage_tilt,
        size_zoom=DynamicLayout.size_zoom,
    )


def base_layout_transform(camera: CameraInfo) -> LayoutTransform:
    size_zoom = 6.0 / camera.size
    t = Layout.field_h * FIELD_T_FACTOR
    w = Layout.field_w * FIELD_W_FACTOR * size_zoom
    return LayoutTransform(
        t=t,
        w_scale=w,
        h_scale=Layout.field_h * FIELD_B_FACTOR - t,
        x_translate=-camera.lane * w,
        rotate=0.0,
        stage_tilt=clamp(camera.stage_tilt, 0.0, 1.0),
        size_zoom=size_zoom,
    )


def zoomed_layout_transform(
    transform: LayoutTransform, zoom: float, target: Vec2, anchor: Vec2, rotate: float
) -> LayoutTransform:
    return LayoutTransform(
        t=zoom * (transform.t - target.y) + anchor.y,
        w_scale=zoom * transform.w_scale,
        h_scale=zoom * transform.h_scale,
        x_translate=zoom * (transform.x_translate - target.x) + anchor.x,
        rotate=rotate,
        stage_tilt=transform.stage_tilt,
        size_zoom=transform.size_zoom,
    )


def apply_test_aspect(transform: LayoutTransform) -> LayoutTransform:
    result = +LayoutTransform
    if test_aspect_active():
        result @= LayoutTransform(
            t=transform.t * TEST_ASPECT_SCALE,
            w_scale=transform.w_scale * TEST_ASPECT_SCALE,
            h_scale=transform.h_scale * TEST_ASPECT_SCALE,
            x_translate=transform.x_translate * TEST_ASPECT_SCALE,
            rotate=transform.rotate,
            stage_tilt=transform.stage_tilt,
            size_zoom=transform.size_zoom,
        )
    else:
        result @= transform
    return result


def layout_transform_at_camera(camera: CameraInfo) -> LayoutTransform:
    return zoomed_layout_transform(
        base_layout_transform(camera),
        camera.zoom,
        camera.zoom_target,
        camera.zoom_anchor,
        camera.rotate,
    )


def compute_hitbox(
    transform: LayoutTransform,
    lane: float,
    size: float,
    leniency: float,
    y_offset: float = 0.0,
    *,
    stage_transform: AffineTransform2d,
) -> Hitbox:
    tilt = transform.stage_tilt
    travel = approach_at_tilt(1 - y_offset, tilt)
    width_factor = width_factor_at_tilt(travel, tilt)
    l_x = (lane - size) * width_factor * transform.w_scale + transform.x_translate
    r_x = (lane + size) * width_factor * transform.w_scale + transform.x_translate
    note_y = travel * transform.h_scale + transform.t
    # We intentionally don't adjust for tilt to give the same screen-space leniency at low tilt
    lane_w = transform.w_scale
    # Dividing out size_zoom keeps the vertical extent constant in screen space regardless of camera size
    vertical_lane_w = lane_w / transform.size_zoom
    vertical_half_lanes = 2.5 if LevelConfig.dynamic_stages else 5.0
    if (
        Options.stage_cover_scroll_speed_compensation != StageCoverNoteSpeedCompensation.OFF
        and LevelConfig.dynamic_stages
    ):
        cover_travel = lerp(APPROACH_SCALE, 1.0, stage_cover_amount())
        vertical_half_lanes *= clamp((1 - cover_travel) / (1 - APPROACH_SCALE), 0, 1)
    vertical_extent = vertical_half_lanes * vertical_lane_w
    rot = -transform.rotate
    bl_x = l_x - leniency * lane_w
    br_x = r_x + leniency * lane_w
    b_y = note_y - vertical_extent
    t_y = note_y + vertical_extent
    target_l = stage_transform.apply(Vec2(l_x, note_y).rotate(rot))
    target_r = stage_transform.apply(Vec2(r_x, note_y).rotate(rot))
    bound_bl = stage_transform.apply(Vec2(bl_x, b_y).rotate(rot))
    bound_br = stage_transform.apply(Vec2(br_x, b_y).rotate(rot))
    bound_tl = stage_transform.apply(Vec2(bl_x, t_y).rotate(rot))
    bound_tr = stage_transform.apply(Vec2(br_x, t_y).rotate(rot))
    return Hitbox(
        target=HitboxTarget(l=target_l, r=target_r),
        bounds=Quad(bl=bound_bl, br=bound_br, tl=bound_tl, tr=bound_tr),
    )


def camera_layout_transform_at_time(target_time: float, left_limit: bool = False) -> LayoutTransform:
    return apply_test_aspect(layout_transform_at_camera(get_camera_info(target_time, left_limit=left_limit)))


def compute_hitbox_at_time(
    lane: float,
    size: float,
    leniency: float,
    target_time: float,
    y_offset: float = 0.0,
    *,
    stage_transform: AffineTransform2d,
    left_limit: bool = False,
) -> Hitbox:
    return compute_hitbox(
        camera_layout_transform_at_time(target_time, left_limit=left_limit),
        lane,
        size,
        leniency,
        y_offset,
        stage_transform=stage_transform,
    )


def segment_closeness_score(p: Vec2, seg: HitboxTarget) -> float:
    d = seg.r - seg.l
    length_squared = d.dot(d)
    if length_squared == 0:
        return -(p - seg.l).magnitude
    t = clamp((p - seg.l).dot(d) / length_squared, 0.0, 1.0)
    return -(p - (seg.l + d * t)).magnitude


def layout_lane_area(l: float, r: float) -> Quad:
    return perspective_rect(l, r, LANE_T, LANE_B)


def iter_slot_lanes(lane: float, size: float, pivot_lane: float = 0.0, half_offset: bool = False):
    e = 1e-6
    offset = 0.0 if half_offset else 0.5
    shift = pivot_lane + offset - 0.5
    shifted_lane = lane - shift
    for i in range(floor(shifted_lane - size + e), ceil(shifted_lane + size - e)):
        yield i + 0.5 + shift
