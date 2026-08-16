from enum import IntEnum
from math import ceil, cos, pi, sin
from typing import Literal, assert_never

from sonolus.script.archetype import EntityRef
from sonolus.script.easing import ease_out_cubic
from sonolus.script.effect import Effect, LoopedEffectHandle
from sonolus.script.globals import level_memory
from sonolus.script.interval import clamp, lerp, remap_clamped, unlerp_clamped
from sonolus.script.particle import Particle, ParticleHandle
from sonolus.script.quad import Quad, QuadLike
from sonolus.script.record import Record
from sonolus.script.runtime import offset_adjusted_time, screen, time
from sonolus.script.sprite import Sprite
from sonolus.script.timing import beat_to_time

from sekai.lib.ease import EaseType, ease
from sekai.lib.effect import Effects
from sekai.lib.layer import (
    LAYER_ACTIVE_SLIDE_CONNECTOR_BOTTOM,
    LAYER_ACTIVE_SLIDE_CONNECTOR_OVER,
    LAYER_ACTIVE_SLIDE_CONNECTOR_TOP,
    LAYER_ACTIVE_SLIDE_CONNECTOR_UNDER,
    LAYER_GUIDE_CONNECTOR_BOTTOM,
    LAYER_GUIDE_CONNECTOR_OVER,
    LAYER_GUIDE_CONNECTOR_TOP,
    LAYER_GUIDE_CONNECTOR_UNDER,
    LAYER_SLOT_GLOW_EFFECT,
    ZIndexes,
    get_z,
)
from sekai.lib.layout import (
    AffineTransform2d,
    DynamicLayout,
    StageTransform,
    approach,
    blend_stage_transform,
    get_alpha,
    iter_slot_lanes,
    layout_circular_effect,
    layout_linear_effect,
    layout_slide_connector_segment,
    layout_slot_glow_effect,
    pre_rotation_vec_at,
    quad_touches_screen,
    st_slide_connector_segment,
    stage_transform_is_identity,
)
from sekai.lib.level_config import LevelConfig
from sekai.lib.options import Options, Version
from sekai.lib.particle import ActiveParticles
from sekai.lib.skin import ActiveConnectorSpriteSet, ActiveSkin
from sekai.lib.timescale import iter_timescale_changes_in_group_from_time

CONNECTOR_TRAIL_SPAWN_PERIOD = 0.1
CONNECTOR_SLOT_SPAWN_PERIOD = 0.2
CONNECTOR_THROUGH_JUDGE_LINE_DESPAWN_DELAY = 5.0
CONNECTOR_LENIENCY = 1
CONNECTOR_PARTICLE_ACTIVE_DELAY = 0.05


class ConnectorKind(IntEnum):
    NONE = 0

    ACTIVE_NORMAL = 1
    ACTIVE_CRITICAL = 2
    DAMAGE = 3
    ACTIVE_FAKE_NORMAL = 51
    ACTIVE_FAKE_CRITICAL = 52
    FAKE_DAMAGE = 53

    GUIDE_NEUTRAL = 101
    GUIDE_RED = 102
    GUIDE_GREEN = 103
    GUIDE_BLUE = 104
    GUIDE_YELLOW = 105
    GUIDE_PURPLE = 106
    GUIDE_CYAN = 107
    GUIDE_BLACK = 108


class ConnectorLayer(IntEnum):
    TOP = 0
    BOTTOM = 1
    UNDER = 2
    OVER = 3


class SegmentPresentation(IntEnum):
    DEFAULT = 0
    FULL_SCREEN = 1


ActiveConnectorKind = Literal[
    ConnectorKind.ACTIVE_NORMAL,
    ConnectorKind.ACTIVE_CRITICAL,
    ConnectorKind.ACTIVE_FAKE_NORMAL,
    ConnectorKind.ACTIVE_FAKE_CRITICAL,
]

GuideConnectorKind = Literal[
    ConnectorKind.GUIDE_NEUTRAL,
    ConnectorKind.GUIDE_RED,
    ConnectorKind.GUIDE_GREEN,
    ConnectorKind.GUIDE_BLUE,
    ConnectorKind.GUIDE_YELLOW,
    ConnectorKind.GUIDE_PURPLE,
    ConnectorKind.GUIDE_CYAN,
    ConnectorKind.GUIDE_BLACK,
]


class ConnectorVisualState(IntEnum):
    WAITING = 0
    INACTIVE = 1
    ACTIVE = 2


CONNECTOR_SFX_ACTIVE_TIME_INIT = -1e8
CONNECTOR_SFX_INACTIVE_TIME_INIT = 1e8


class ConnectorSfxTimes(Record):
    active_time: float
    inactive_time: float


@level_memory
class ConnectorSfxState:
    normal_active_time: float
    normal_inactive_time: float
    critical_active_time: float
    critical_inactive_time: float


def is_fake_active_connector(kind: ConnectorKind) -> bool:
    return kind in {ConnectorKind.ACTIVE_FAKE_NORMAL, ConnectorKind.ACTIVE_FAKE_CRITICAL}


def is_fake_connector(kind: ConnectorKind) -> bool:
    return is_fake_active_connector(kind) or kind == ConnectorKind.FAKE_DAMAGE


def should_show_connector_hitbox(kind: ConnectorKind) -> bool:
    # DAMAGE is input-tracked but excluded: its region is already visualized by the tick
    # hitboxes, which follow the head and would coincide with a connector-level overlay.
    return kind in {ConnectorKind.ACTIVE_NORMAL, ConnectorKind.ACTIVE_CRITICAL}


def get_connector_input_leniency(kind: ConnectorKind) -> float:
    if kind == ConnectorKind.DAMAGE:
        return 0.0
    return CONNECTOR_LENIENCY


def get_active_connector_sprites(kind: ActiveConnectorKind) -> ActiveConnectorSpriteSet:
    result = +ActiveConnectorSpriteSet
    match kind:
        case ConnectorKind.ACTIVE_NORMAL | ConnectorKind.ACTIVE_FAKE_NORMAL:
            result @= ActiveSkin.active_slide_connector
        case ConnectorKind.ACTIVE_CRITICAL | ConnectorKind.ACTIVE_FAKE_CRITICAL:
            result @= ActiveSkin.critical_active_slide_connector
        case _:
            assert_never(kind)
    return result


def get_guide_connector_sprite(kind: GuideConnectorKind) -> Sprite:
    result = +Sprite
    match kind:
        case ConnectorKind.GUIDE_NEUTRAL:
            result @= ActiveSkin.guide_neutral
        case ConnectorKind.GUIDE_RED:
            result @= ActiveSkin.guide_red
        case ConnectorKind.GUIDE_GREEN:
            result @= ActiveSkin.guide_green
        case ConnectorKind.GUIDE_BLUE:
            result @= ActiveSkin.guide_blue
        case ConnectorKind.GUIDE_YELLOW:
            result @= ActiveSkin.guide_yellow
        case ConnectorKind.GUIDE_PURPLE:
            result @= ActiveSkin.guide_purple
        case ConnectorKind.GUIDE_CYAN:
            result @= ActiveSkin.guide_cyan
        case ConnectorKind.GUIDE_BLACK:
            result @= ActiveSkin.guide_black
        case _:
            assert_never(kind)
    return result


def get_damage_connector_sprite() -> Sprite:
    result = +Sprite
    result @= ActiveSkin.damage_slide_connector
    return result


def get_damage_connector_active_sprite() -> Sprite:
    result = +Sprite
    result @= ActiveSkin.damage_slide_connector_active
    return result


def get_connector_z(
    kind: ConnectorKind, target_time: float, lane: float, active: bool, layer: ConnectorLayer
) -> ZIndexes:
    result = +ZIndexes
    match kind:
        case (
            ConnectorKind.ACTIVE_NORMAL
            | ConnectorKind.ACTIVE_FAKE_NORMAL
            | ConnectorKind.ACTIVE_CRITICAL
            | ConnectorKind.ACTIVE_FAKE_CRITICAL
        ):
            match layer:
                case ConnectorLayer.TOP:
                    result @= get_z(
                        LAYER_ACTIVE_SLIDE_CONNECTOR_TOP,
                        time=target_time,
                        lane=lane,
                        etc=get_active_connector_z_offset(kind, active),
                        invert_time=True,
                    )
                case ConnectorLayer.BOTTOM:
                    result @= get_z(
                        LAYER_ACTIVE_SLIDE_CONNECTOR_BOTTOM,
                        time=target_time,
                        lane=lane,
                        etc=get_active_connector_z_offset(kind, active),
                        invert_time=True,
                    )
                case ConnectorLayer.UNDER:
                    result @= get_z(
                        LAYER_ACTIVE_SLIDE_CONNECTOR_UNDER,
                        time=target_time,
                        lane=lane,
                        etc=get_active_connector_z_offset(kind, active),
                        invert_time=True,
                    )
                case ConnectorLayer.OVER:
                    result @= get_z(
                        LAYER_ACTIVE_SLIDE_CONNECTOR_OVER,
                        time=target_time,
                        lane=lane,
                        etc=get_active_connector_z_offset(kind, active),
                        invert_time=True,
                    )
                case _:
                    assert_never(layer)
        case (
            ConnectorKind.GUIDE_NEUTRAL
            | ConnectorKind.GUIDE_RED
            | ConnectorKind.GUIDE_GREEN
            | ConnectorKind.GUIDE_BLUE
            | ConnectorKind.GUIDE_YELLOW
            | ConnectorKind.GUIDE_PURPLE
            | ConnectorKind.GUIDE_CYAN
            | ConnectorKind.GUIDE_BLACK
        ):
            result @= get_guide_connector_layer_z(layer, target_time, lane, kind - ConnectorKind.GUIDE_NEUTRAL)
        case ConnectorKind.DAMAGE | ConnectorKind.FAKE_DAMAGE:
            result @= get_guide_connector_layer_z(layer, target_time, lane, get_active_connector_z_offset(kind, active))
        case ConnectorKind.NONE:
            pass
        case _:
            assert_never(kind)
    return result


def get_guide_connector_layer_z(layer: ConnectorLayer, target_time: float, lane: float, etc: int) -> ZIndexes:
    result = +ZIndexes
    match layer:
        case ConnectorLayer.TOP:
            result @= get_z(
                LAYER_GUIDE_CONNECTOR_TOP,
                time=target_time,
                lane=lane,
                etc=etc,
                invert_time=True,
            )
        case ConnectorLayer.BOTTOM:
            result @= get_z(
                LAYER_GUIDE_CONNECTOR_BOTTOM,
                time=target_time,
                lane=lane,
                etc=etc,
                invert_time=True,
            )
        case ConnectorLayer.UNDER:
            result @= get_z(
                LAYER_GUIDE_CONNECTOR_UNDER,
                time=target_time,
                lane=lane,
                etc=etc,
                invert_time=True,
            )
        case ConnectorLayer.OVER:
            result @= get_z(
                LAYER_GUIDE_CONNECTOR_OVER,
                time=target_time,
                lane=lane,
                etc=etc,
                invert_time=True,
            )
        case _:
            assert_never(layer)
    return result


def get_active_connector_z_offset(
    kind: ActiveConnectorKind | Literal[ConnectorKind.DAMAGE, ConnectorKind.FAKE_DAMAGE], active: bool
) -> int:
    match kind:
        case ConnectorKind.ACTIVE_NORMAL | ConnectorKind.ACTIVE_FAKE_NORMAL:
            return 3 - active
        case ConnectorKind.ACTIVE_CRITICAL | ConnectorKind.ACTIVE_FAKE_CRITICAL:
            return 1 - active
        case ConnectorKind.DAMAGE | ConnectorKind.FAKE_DAMAGE:
            return 9 - active
        case _:
            assert_never(kind)


def get_connector_alpha_option(kind: ConnectorKind) -> float:
    match kind:
        case (
            ConnectorKind.ACTIVE_NORMAL
            | ConnectorKind.ACTIVE_FAKE_NORMAL
            | ConnectorKind.ACTIVE_CRITICAL
            | ConnectorKind.ACTIVE_FAKE_CRITICAL
        ):
            return Options.slide_alpha
        case ConnectorKind.DAMAGE | ConnectorKind.FAKE_DAMAGE:
            return Options.slide_alpha
        case (
            ConnectorKind.GUIDE_NEUTRAL
            | ConnectorKind.GUIDE_RED
            | ConnectorKind.GUIDE_GREEN
            | ConnectorKind.GUIDE_BLUE
            | ConnectorKind.GUIDE_YELLOW
            | ConnectorKind.GUIDE_PURPLE
            | ConnectorKind.GUIDE_CYAN
            | ConnectorKind.GUIDE_BLACK
        ):
            return Options.guide_alpha
        case ConnectorKind.NONE:
            return 0.0
        case _:
            assert_never(kind)


def get_connector_quality_option(kind: ConnectorKind) -> float:
    match kind:
        case (
            ConnectorKind.ACTIVE_NORMAL
            | ConnectorKind.ACTIVE_FAKE_NORMAL
            | ConnectorKind.ACTIVE_CRITICAL
            | ConnectorKind.ACTIVE_FAKE_CRITICAL
        ):
            return Options.slide_quality
        case ConnectorKind.DAMAGE | ConnectorKind.FAKE_DAMAGE:
            return Options.slide_quality
        case (
            ConnectorKind.GUIDE_NEUTRAL
            | ConnectorKind.GUIDE_RED
            | ConnectorKind.GUIDE_GREEN
            | ConnectorKind.GUIDE_BLUE
            | ConnectorKind.GUIDE_YELLOW
            | ConnectorKind.GUIDE_PURPLE
            | ConnectorKind.GUIDE_CYAN
            | ConnectorKind.GUIDE_BLACK
        ):
            return Options.guide_quality
        case ConnectorKind.NONE:
            return 0
        case _:
            assert_never(kind)


def draw_connector(
    kind: ConnectorKind,
    visual_state: ConnectorVisualState,
    ease_type: EaseType,
    head_lane: float,
    head_size: float,
    head_visual_progress: float,
    head_target_time: float,
    head_ease_frac: float,
    tail_lane: float,
    tail_size: float,
    tail_visual_progress: float,
    tail_target_time: float,
    tail_ease_frac: float,
    segment_head_target_time: float,
    segment_head_lane: float,
    segment_head_alpha: float,
    segment_tail_target_time: float,
    segment_tail_alpha: float,
    layer: ConnectorLayer,
    presentation: SegmentPresentation,
    bypass_tail_target_time_check: bool,
    head_transform: StageTransform | None,
    tail_transform: StageTransform | None,
    head_note_alpha: float,
    tail_note_alpha: float,
):
    match presentation:
        case SegmentPresentation.DEFAULT:
            if (
                (
                    head_visual_progress < DynamicLayout.progress_start
                    and tail_visual_progress < DynamicLayout.progress_start
                )
                or (
                    head_visual_progress > DynamicLayout.progress_cutoff
                    and tail_visual_progress > DynamicLayout.progress_cutoff
                )
                or head_visual_progress == tail_visual_progress
            ):
                return
        case SegmentPresentation.FULL_SCREEN:
            if head_target_time == tail_target_time or not (
                min(head_target_time, tail_target_time) <= time() <= max(head_target_time, tail_target_time)
            ):
                return
        case _:
            assert_never(presentation)

    if Options.disable_fake_notes and is_fake_connector(kind):
        return

    if head_note_alpha <= 0 and tail_note_alpha <= 0:
        return

    if ease_type == EaseType.NONE:
        tail_lane = head_lane
        tail_size = head_size

    normal_sprite = Sprite(-1)
    active_sprite = Sprite(-1)
    match kind:
        case (
            ConnectorKind.ACTIVE_NORMAL
            | ConnectorKind.ACTIVE_CRITICAL
            | ConnectorKind.ACTIVE_FAKE_NORMAL
            | ConnectorKind.ACTIVE_FAKE_CRITICAL
        ):
            sprites = get_active_connector_sprites(kind)
            normal_sprite @= sprites.connection.normal
            active_sprite @= sprites.connection.active
        case (
            ConnectorKind.GUIDE_NEUTRAL
            | ConnectorKind.GUIDE_RED
            | ConnectorKind.GUIDE_GREEN
            | ConnectorKind.GUIDE_BLUE
            | ConnectorKind.GUIDE_YELLOW
            | ConnectorKind.GUIDE_PURPLE
            | ConnectorKind.GUIDE_CYAN
            | ConnectorKind.GUIDE_BLACK
        ):
            sprites = get_guide_connector_sprite(kind)
            normal_sprite @= sprites
        case ConnectorKind.DAMAGE:
            normal_sprite @= get_damage_connector_sprite()
            active_sprite @= get_damage_connector_active_sprite()
        case ConnectorKind.FAKE_DAMAGE:
            normal_sprite @= get_damage_connector_sprite()
        case ConnectorKind.NONE:
            return
        case _:
            assert_never(kind)

    match kind:
        case ConnectorKind.ACTIVE_NORMAL | ConnectorKind.ACTIVE_CRITICAL:
            segment_head_alpha = 1.0
            segment_tail_alpha = 1.0
        case ConnectorKind.ACTIVE_FAKE_NORMAL | ConnectorKind.ACTIVE_FAKE_CRITICAL:
            segment_head_alpha = 1.0
            segment_tail_alpha = 1.0
            if visual_state == ConnectorVisualState.INACTIVE:
                visual_state = ConnectorVisualState.ACTIVE
        case (
            ConnectorKind.GUIDE_NEUTRAL
            | ConnectorKind.GUIDE_RED
            | ConnectorKind.GUIDE_GREEN
            | ConnectorKind.GUIDE_BLUE
            | ConnectorKind.GUIDE_YELLOW
            | ConnectorKind.GUIDE_PURPLE
            | ConnectorKind.GUIDE_CYAN
            | ConnectorKind.GUIDE_BLACK
            | ConnectorKind.FAKE_DAMAGE
        ):
            visual_state = ConnectorVisualState.WAITING
        case ConnectorKind.DAMAGE:
            pass
        case _:
            assert_never(kind)

    head_alpha = (
        remap_clamped(
            segment_head_target_time, segment_tail_target_time, segment_head_alpha, segment_tail_alpha, head_target_time
        )
        * head_note_alpha
    )
    tail_alpha = (
        remap_clamped(
            segment_head_target_time, segment_tail_target_time, segment_head_alpha, segment_tail_alpha, tail_target_time
        )
        * tail_note_alpha
    )

    if time() >= tail_target_time and not bypass_tail_target_time_check:
        return

    z_normal = get_connector_z(kind, segment_head_target_time, segment_head_lane, active=False, layer=layer)
    z_active = +ZIndexes
    if visual_state == ConnectorVisualState.ACTIVE and active_sprite.is_available:
        z_active @= get_connector_z(kind, segment_head_target_time, segment_head_lane, active=True, layer=layer)
    else:
        z_active @= z_normal

    match presentation:
        case SegmentPresentation.DEFAULT:
            draw_connector_default(
                kind=kind,
                visual_state=visual_state,
                ease_type=ease_type,
                normal_sprite=normal_sprite,
                active_sprite=active_sprite,
                segment_head_target_time=segment_head_target_time,
                z_normal=z_normal,
                z_active=z_active,
                head_lane=head_lane,
                head_size=head_size,
                head_visual_progress=head_visual_progress,
                head_target_time=head_target_time,
                head_ease_frac=head_ease_frac,
                head_alpha=head_alpha,
                tail_lane=tail_lane,
                tail_size=tail_size,
                tail_visual_progress=tail_visual_progress,
                tail_target_time=tail_target_time,
                tail_ease_frac=tail_ease_frac,
                tail_alpha=tail_alpha,
                head_transform=head_transform,
                tail_transform=tail_transform,
            )
        case SegmentPresentation.FULL_SCREEN:
            draw_connector_full_screen(
                kind=kind,
                visual_state=visual_state,
                normal_sprite=normal_sprite,
                active_sprite=active_sprite,
                z_normal=z_normal,
                z_active=z_active,
                head_target_time=head_target_time,
                head_alpha=head_alpha,
                tail_target_time=tail_target_time,
                tail_alpha=tail_alpha,
            )
        case _:
            assert_never(presentation)


def draw_connector_default(
    kind: ConnectorKind,
    visual_state: ConnectorVisualState,
    ease_type: EaseType,
    normal_sprite: Sprite,
    active_sprite: Sprite,
    segment_head_target_time: float,
    z_normal: ZIndexes,
    z_active: ZIndexes,
    head_lane: float,
    head_size: float,
    head_visual_progress: float,
    head_target_time: float,
    head_ease_frac: float,
    head_alpha: float,
    tail_lane: float,
    tail_size: float,
    tail_visual_progress: float,
    tail_target_time: float,
    tail_ease_frac: float,
    tail_alpha: float,
    head_transform: StageTransform | None = None,
    tail_transform: StageTransform | None = None,
):
    start_visual_progress = clamp(head_visual_progress, DynamicLayout.progress_start, DynamicLayout.progress_cutoff)
    end_visual_progress = clamp(tail_visual_progress, DynamicLayout.progress_start, DynamicLayout.progress_cutoff)
    start_frac = unlerp_clamped(head_visual_progress, tail_visual_progress, start_visual_progress)
    end_frac = unlerp_clamped(head_visual_progress, tail_visual_progress, end_visual_progress)
    start_ease_frac = lerp(head_ease_frac, tail_ease_frac, start_frac)
    end_ease_frac = lerp(head_ease_frac, tail_ease_frac, end_frac)
    eased_head_ease_frac = ease(ease_type, head_ease_frac)
    eased_tail_ease_frac = ease(ease_type, tail_ease_frac)
    start_interp_frac = unlerp_clamped(eased_head_ease_frac, eased_tail_ease_frac, ease(ease_type, start_ease_frac))
    end_interp_frac = unlerp_clamped(eased_head_ease_frac, eased_tail_ease_frac, ease(ease_type, end_ease_frac))
    start_travel = approach(start_visual_progress)
    end_travel = approach(end_visual_progress)
    start_lane = lerp(head_lane, tail_lane, start_interp_frac)
    end_lane = lerp(head_lane, tail_lane, end_interp_frac)
    start_size = max(1e-3, lerp(head_size, tail_size, start_interp_frac))  # Lightweight rendering needs >0 size.
    end_size = max(1e-3, lerp(head_size, tail_size, end_interp_frac))  # Lightweight rendering needs >0 size.
    start_alpha = lerp(head_alpha, tail_alpha, start_frac)
    end_alpha = lerp(head_alpha, tail_alpha, end_frac)
    start_pos_y = pre_rotation_vec_at(start_lane, start_travel).y
    end_pos_y = pre_rotation_vec_at(end_lane, end_travel).y

    alpha_option = get_connector_alpha_option(kind)
    delta_alpha = min(abs(start_alpha - end_alpha) * alpha_option, 1.0)
    scale = max(delta_alpha**0.8 * 3, delta_alpha**0.5 * abs(start_pos_y - end_pos_y) * 3) if delta_alpha else 0.0
    match ease_type:
        case EaseType.NONE:
            pass
        case _:
            left_start_lane = start_lane - start_size
            left_end_lane = end_lane - end_size
            right_start_lane = start_lane + start_size
            right_end_lane = end_lane + end_size
            if abs(start_size - end_size) < 0.1:
                ref_start_lane = start_lane
                ref_end_lane = end_lane
                ref_head_lane = head_lane
                ref_tail_lane = tail_lane
            elif abs(left_start_lane - left_end_lane) > abs(right_start_lane - right_end_lane):
                ref_start_lane = left_start_lane
                ref_end_lane = left_end_lane
                ref_head_lane = head_lane - head_size
                ref_tail_lane = tail_lane - tail_size
            else:
                ref_start_lane = right_start_lane
                ref_end_lane = right_end_lane
                ref_head_lane = head_lane + head_size
                ref_tail_lane = tail_lane + tail_size
            if ref_head_lane != ref_tail_lane:
                start_ref = pre_rotation_vec_at(ref_start_lane, start_travel)
                end_ref = pre_rotation_vec_at(ref_end_lane, end_travel)
                max_offset = 0.0
                for r in (0.25, 0.5, 0.75):
                    ease_frac = lerp(start_ease_frac, end_ease_frac, r)
                    interp_frac = unlerp_clamped(eased_head_ease_frac, eased_tail_ease_frac, ease(ease_type, ease_frac))
                    visual_progress = lerp(start_visual_progress, end_visual_progress, r)
                    travel = approach(visual_progress)
                    lane = lerp(ref_head_lane, ref_tail_lane, interp_frac)
                    pos = pre_rotation_vec_at(lane, travel)
                    ref_pos = lerp(start_ref, end_ref, unlerp_clamped(start_travel, end_travel, travel))
                    max_offset = max(max_offset, abs(pos.x - ref_pos.x))
                scale = max(scale, max_offset**0.5 * 2.5)
    quality = get_connector_quality_option(kind)
    segment_count = max(1, ceil(scale * quality * 10))

    has_transform = (
        head_transform is not None
        and tail_transform is not None
        and not (stage_transform_is_identity(head_transform) and stage_transform_is_identity(tail_transform))
    )
    if has_transform and head_transform != tail_transform:
        segment_count = max(segment_count, ceil(15 * quality))

    last_travel = start_travel
    last_lane = start_lane
    last_size = start_size
    last_alpha = start_alpha
    last_target_time = lerp(head_target_time, tail_target_time, start_frac)
    last_interp_frac = start_interp_frac

    anim_factor1, anim_factor2 = (1, 1)
    if visual_state == ConnectorVisualState.ACTIVE and active_sprite.is_available and Options.connector_animation:
        anim_factor1, anim_factor2 = get_cross_fate_opacities(1.0, time() - segment_head_target_time, 0.5)

    layout = +Quad
    for i in range(1, segment_count + 1):
        segment_frac = i / segment_count
        next_frac = lerp(start_frac, end_frac, segment_frac)
        next_ease_frac = lerp(start_ease_frac, end_ease_frac, segment_frac)
        next_interp_frac = unlerp_clamped(eased_head_ease_frac, eased_tail_ease_frac, ease(ease_type, next_ease_frac))
        next_visual_progress = lerp(start_visual_progress, end_visual_progress, segment_frac)
        next_travel = approach(next_visual_progress)
        next_lane = lerp(head_lane, tail_lane, next_interp_frac)
        next_size = max(1e-3, lerp(head_size, tail_size, next_interp_frac))
        next_alpha = lerp(head_alpha, tail_alpha, next_frac)
        next_target_time = lerp(head_target_time, tail_target_time, next_frac)

        base_a = clamp(
            get_alpha((last_target_time + next_target_time) / 2) * (last_alpha + next_alpha) / 2 * alpha_option,
            0,
            1,
        )

        if has_transform:
            # Satisfy pyright
            assert head_transform is not None
            assert tail_transform is not None
            layout @= st_slide_connector_segment(
                start_lane=last_lane,
                start_size=last_size,
                start_travel=last_travel,
                end_lane=next_lane,
                end_size=next_size,
                end_travel=next_travel,
                start_transform=blend_stage_transform(head_transform, tail_transform, last_interp_frac).transform(),
                end_transform=blend_stage_transform(head_transform, tail_transform, next_interp_frac).transform(),
            )
        else:
            layout @= layout_slide_connector_segment(
                start_lane=last_lane,
                start_size=last_size,
                start_travel=last_travel,
                end_lane=next_lane,
                end_size=next_size,
                end_travel=next_travel,
            )

        if visual_state == ConnectorVisualState.ACTIVE and active_sprite.is_available:
            if Options.connector_animation:
                normal_sprite.draw(layout, z=z_normal.tuple, a=base_a * anim_factor1)
                active_sprite.draw(layout, z=z_active.tuple, a=base_a * anim_factor2)
            else:
                normal_sprite.draw(layout, z=z_normal.tuple, a=base_a)
        else:
            normal_sprite.draw(
                layout, z=z_normal.tuple, a=base_a * (1 if visual_state != ConnectorVisualState.INACTIVE else 0.5)
            )

        last_travel = next_travel
        last_lane = next_lane
        last_size = next_size
        last_alpha = next_alpha
        last_target_time = next_target_time
        last_interp_frac = next_interp_frac


def get_cross_fate_opacities(a, t, period):
    phase = (t % period) / period * 2 * pi
    rate = 0.5 - cos(phase) * 0.5

    opacity1 = a * (1 - rate)
    opacity2 = a * rate

    return opacity1, opacity2


def draw_connector_full_screen(
    kind: ConnectorKind,
    visual_state: ConnectorVisualState,
    normal_sprite: Sprite,
    active_sprite: Sprite,
    z_normal: ZIndexes,
    z_active: ZIndexes,
    head_target_time: float,
    head_alpha: float,
    tail_target_time: float,
    tail_alpha: float,
):
    judge_frac = unlerp_clamped(head_target_time, tail_target_time, time())
    judge_alpha = lerp(head_alpha, tail_alpha, judge_frac)
    base_a = clamp(get_alpha(time()) * judge_alpha * get_connector_alpha_option(kind), 0, 1)
    draw_connector_quad(screen(), visual_state, normal_sprite, active_sprite, z_normal, z_active, base_a)


def draw_connector_quad(
    layout: QuadLike,
    visual_state: ConnectorVisualState,
    normal_sprite: Sprite,
    active_sprite: Sprite,
    z_normal: ZIndexes,
    z_active: ZIndexes,
    base_a: float,
):
    if visual_state == ConnectorVisualState.ACTIVE and active_sprite.is_available:
        if Options.connector_animation:
            a_modifier = (cos(2 * pi * time()) + 1) / 2
            normal_sprite.draw(layout, z=z_normal.tuple, a=base_a * ease_out_cubic(a_modifier))
            active_sprite.draw(layout, z=z_active.tuple, a=base_a * ease_out_cubic(1 - a_modifier))
        else:
            active_sprite.draw(layout, z=z_active.tuple, a=base_a)
    else:
        normal_sprite.draw(
            layout, z=z_normal.tuple, a=base_a * (1 if visual_state != ConnectorVisualState.INACTIVE else 0.5)
        )


class ActiveConnectorInfo(Record):
    visual_lane: float
    visual_size: float
    visual_y_offset: float
    input_bounds: Quad
    is_active: bool
    active_start_time: float
    connector_kind: ConnectorKind


def inactive_connector_sfx_times() -> ConnectorSfxTimes:
    return ConnectorSfxTimes(
        active_time=CONNECTOR_SFX_ACTIVE_TIME_INIT,
        inactive_time=CONNECTOR_SFX_INACTIVE_TIME_INIT,
    )


def init_connector_sfx_times():
    ConnectorSfxState.normal_active_time = CONNECTOR_SFX_ACTIVE_TIME_INIT
    ConnectorSfxState.normal_inactive_time = CONNECTOR_SFX_INACTIVE_TIME_INIT
    ConnectorSfxState.critical_active_time = CONNECTOR_SFX_ACTIVE_TIME_INIT
    ConnectorSfxState.critical_inactive_time = CONNECTOR_SFX_INACTIVE_TIME_INIT


def activate_connector_sfx(
    kind: ActiveConnectorKind,
    event_time: float,
    active_head_target_time: float,
    active_tail_target_time: float,
) -> ConnectorSfxTimes:
    sfx_time = clamp(event_time, active_head_target_time, active_tail_target_time)
    result = +ConnectorSfxTimes
    match kind:
        case ConnectorKind.ACTIVE_NORMAL | ConnectorKind.ACTIVE_FAKE_NORMAL:
            if ConnectorSfxState.normal_inactive_time == CONNECTOR_SFX_INACTIVE_TIME_INIT:
                ConnectorSfxState.normal_inactive_time = sfx_time
            ConnectorSfxState.normal_active_time = sfx_time
            result.active_time = ConnectorSfxState.normal_active_time
            result.inactive_time = ConnectorSfxState.normal_inactive_time
        case ConnectorKind.ACTIVE_CRITICAL | ConnectorKind.ACTIVE_FAKE_CRITICAL:
            if ConnectorSfxState.critical_inactive_time == CONNECTOR_SFX_INACTIVE_TIME_INIT:
                ConnectorSfxState.critical_inactive_time = sfx_time
            ConnectorSfxState.critical_active_time = sfx_time
            result.active_time = ConnectorSfxState.critical_active_time
            result.inactive_time = ConnectorSfxState.critical_inactive_time
        case _:
            assert_never(kind)
    return result


def deactivate_connector_sfx(
    kind: ActiveConnectorKind,
    event_time: float,
    active_head_target_time: float,
    active_tail_target_time: float,
) -> ConnectorSfxTimes:
    sfx_time = clamp(event_time, active_head_target_time, active_tail_target_time)
    result = +ConnectorSfxTimes
    match kind:
        case ConnectorKind.ACTIVE_NORMAL | ConnectorKind.ACTIVE_FAKE_NORMAL:
            ConnectorSfxState.normal_inactive_time = sfx_time
            result.active_time = ConnectorSfxState.normal_active_time
            result.inactive_time = ConnectorSfxState.normal_inactive_time
        case ConnectorKind.ACTIVE_CRITICAL | ConnectorKind.ACTIVE_FAKE_CRITICAL:
            ConnectorSfxState.critical_inactive_time = sfx_time
            result.active_time = ConnectorSfxState.critical_active_time
            result.inactive_time = ConnectorSfxState.critical_inactive_time
        case _:
            assert_never(kind)
    return result


def connector_sfx_is_active(times: ConnectorSfxTimes) -> bool:
    return times.active_time >= times.inactive_time


def connector_sfx_matches_kind(kind: ConnectorKind, sfx_kind: ActiveConnectorKind) -> bool:
    match sfx_kind:
        case ConnectorKind.ACTIVE_NORMAL | ConnectorKind.ACTIVE_FAKE_NORMAL:
            return kind in {ConnectorKind.ACTIVE_NORMAL, ConnectorKind.ACTIVE_FAKE_NORMAL}
        case ConnectorKind.ACTIVE_CRITICAL | ConnectorKind.ACTIVE_FAKE_CRITICAL:
            return kind in {ConnectorKind.ACTIVE_CRITICAL, ConnectorKind.ACTIVE_FAKE_CRITICAL}
        case _:
            assert_never(sfx_kind)


def normal_connector_sfx_is_active() -> bool:
    return (
        ConnectorSfxState.normal_active_time >= ConnectorSfxState.normal_inactive_time
        and offset_adjusted_time() >= ConnectorSfxState.normal_active_time
    )


def critical_connector_sfx_is_active() -> bool:
    return (
        ConnectorSfxState.critical_active_time >= ConnectorSfxState.critical_inactive_time
        and offset_adjusted_time() >= ConnectorSfxState.critical_active_time
    )


def update_circular_connector_particle(
    handle: ParticleHandle,
    kind: ActiveConnectorKind,
    lane: float,
    replace: bool,
    y_offset: float = 0.0,
    *,
    transform: AffineTransform2d,
):
    if not Options.note_effect_enabled:
        return
    layout = transform.transform_quad(layout_circular_effect(lane, w=3.5, h=2.1, y_offset=y_offset))
    if replace or handle.id == 0:
        particle = +Particle(-1)
        match kind:
            case ConnectorKind.ACTIVE_NORMAL | ConnectorKind.ACTIVE_FAKE_NORMAL:
                particle @= ActiveParticles.normal_slide_connector.circular
            case ConnectorKind.ACTIVE_CRITICAL | ConnectorKind.ACTIVE_FAKE_CRITICAL:
                particle @= ActiveParticles.critical_slide_connector.circular
            case _:
                assert_never(kind)
        replace_looped_particle(handle, particle, layout, duration=1 / Options.effect_animation_speed)
    else:
        update_looped_particle(handle, layout)


def update_linear_connector_particle(
    handle: ParticleHandle,
    kind: ActiveConnectorKind,
    lane: float,
    replace: bool,
    y_offset: float = 0.0,
    *,
    transform: AffineTransform2d,
):
    if not Options.note_effect_enabled:
        return
    layout = transform.transform_quad(layout_linear_effect(lane, shear=0, y_offset=y_offset))
    particle = +Particle
    if replace or handle.id == 0:
        match kind:
            case ConnectorKind.ACTIVE_NORMAL | ConnectorKind.ACTIVE_FAKE_NORMAL:
                particle @= ActiveParticles.normal_slide_connector.linear
            case ConnectorKind.ACTIVE_CRITICAL | ConnectorKind.ACTIVE_FAKE_CRITICAL:
                particle @= ActiveParticles.critical_slide_connector.linear
            case _:
                assert_never(kind)
        replace_looped_particle(handle, particle, layout, duration=1 / Options.effect_animation_speed)
    else:
        update_looped_particle(handle, layout)


def spawn_linear_connector_trail_particle(
    kind: ActiveConnectorKind,
    lane: float,
    y_offset: float = 0.0,
    *,
    transform: AffineTransform2d,
):
    if not Options.note_effect_enabled:
        return
    layout = transform.transform_quad(layout_linear_effect(lane, shear=0, y_offset=y_offset))
    particle = +Particle
    match kind:
        case ConnectorKind.ACTIVE_NORMAL | ConnectorKind.ACTIVE_FAKE_NORMAL:
            particle @= ActiveParticles.normal_slide_connector.trail_linear
        case ConnectorKind.ACTIVE_CRITICAL | ConnectorKind.ACTIVE_FAKE_CRITICAL:
            particle @= ActiveParticles.critical_slide_connector.trail_linear
        case _:
            assert_never(kind)
    particle.spawn(layout, duration=0.5 / Options.effect_animation_speed)


def spawn_connector_slot_particles(
    kind: ActiveConnectorKind,
    lane: float,
    size: float,
    y_offset: float = 0.0,
    *,
    transform: AffineTransform2d,
):
    if not Options.note_effect_enabled:
        return
    particle = +Particle
    match kind:
        case ConnectorKind.ACTIVE_NORMAL | ConnectorKind.ACTIVE_FAKE_NORMAL:
            particle @= ActiveParticles.normal_slide_connector.slot_linear
        case ConnectorKind.ACTIVE_CRITICAL | ConnectorKind.ACTIVE_FAKE_CRITICAL:
            particle @= ActiveParticles.critical_slide_connector.slot_linear
        case _:
            assert_never(kind)
    for slot_lane in iter_slot_lanes(lane, size):
        layout = transform.transform_quad(layout_linear_effect(slot_lane, shear=0, y_offset=y_offset))
        if not quad_touches_screen(layout):
            continue
        particle.spawn(layout, duration=0.5 / Options.effect_animation_speed)


def draw_connector_slot_glow_effect(
    kind: ActiveConnectorKind,
    start_time: float,
    lane: float,
    size: float,
    y_offset: float = 0.0,
    *,
    transform: AffineTransform2d,
):
    if not Options.slot_effect_enabled:
        return
    sprite = +Sprite
    match kind:
        case ConnectorKind.ACTIVE_NORMAL | ConnectorKind.ACTIVE_FAKE_NORMAL:
            sprite @= ActiveSkin.active_slide_connector.slot_glow
        case ConnectorKind.ACTIVE_CRITICAL | ConnectorKind.ACTIVE_FAKE_CRITICAL:
            sprite @= ActiveSkin.critical_active_slide_connector.slot_glow
        case _:
            assert_never(kind)
    height = (
        0.85 + (1.2 - 0.85) * ((cos((time() - start_time) * 8 * pi) + 1) / 2)  # min + (max - min) * osc
        if LevelConfig.ui_version == Version.v3
        else 0.2 + (1.2 - 0.2) * ((sin((time() - start_time) * 2.5 * pi) + 1) / 2)
    )
    ex = 0.035 * abs(2 * size) + 0.08 if LevelConfig.ui_version == Version.v3 else 0
    layout = transform.transform_quad(layout_slot_glow_effect(lane, size + ex, height, y_offset=y_offset))
    if not quad_touches_screen(layout):
        return
    z = get_z(LAYER_SLOT_GLOW_EFFECT, start_time, lane, invert_time=True)
    a = remap_clamped(start_time, start_time + 0.25, 0.0, 0.25, time())
    lightweight = 0.25 if ActiveParticles.lightweight.is_available else 1
    sprite.draw(layout, z=z.tuple, a=a * lightweight)


def update_connector_sfx(
    handle: LoopedEffectHandle,
    kind: ActiveConnectorKind,
    replace: bool,
):
    if not Options.sfx_enabled:
        return
    if Options.auto_sfx:
        return
    effect = +Effect
    match kind:
        case ConnectorKind.ACTIVE_NORMAL | ConnectorKind.ACTIVE_FAKE_NORMAL:
            effect @= Effects.normal_hold
        case ConnectorKind.ACTIVE_CRITICAL | ConnectorKind.ACTIVE_FAKE_CRITICAL:
            effect @= Effects.critical_hold
        case _:
            assert_never(kind)
    if replace:
        replace_looped_sfx(handle, effect)
    elif handle.id == 0:
        handle @= effect.loop()


def schedule_connector_sfx(
    kind: ActiveConnectorKind,
    timescale_group: int | EntityRef,
    start_time: float,
    end_time: float,
):
    if not Options.sfx_enabled:
        return
    effect = +Effect
    match kind:
        case ConnectorKind.ACTIVE_NORMAL | ConnectorKind.ACTIVE_FAKE_NORMAL:
            effect @= Effects.normal_hold
        case ConnectorKind.ACTIVE_CRITICAL | ConnectorKind.ACTIVE_FAKE_CRITICAL:
            effect @= Effects.critical_hold
        case _:
            assert_never(kind)
    last_start_time = start_time
    hide = False
    for group in iter_timescale_changes_in_group_from_time(timescale_group, start_time):
        group_time = beat_to_time(group.beat)
        if group_time <= start_time:
            hide = group.hide_notes
            continue
        if group_time >= end_time:
            break
        if hide and not group.hide_notes:
            last_start_time = group_time
        elif not hide and group.hide_notes and group_time > last_start_time:
            schedule_looped_sfx(effect, last_start_time, group_time)
        hide = group.hide_notes
    if not hide and end_time > last_start_time:
        schedule_looped_sfx(effect, last_start_time, end_time)


def schedule_connector_sfx_between(
    kind: ActiveConnectorKind,
    start_time: float,
    end_time: float,
):
    if not Options.sfx_enabled:
        return
    if end_time <= start_time:
        return
    effect = +Effect
    match kind:
        case ConnectorKind.ACTIVE_NORMAL | ConnectorKind.ACTIVE_FAKE_NORMAL:
            effect @= Effects.normal_hold
        case ConnectorKind.ACTIVE_CRITICAL | ConnectorKind.ACTIVE_FAKE_CRITICAL:
            effect @= Effects.critical_hold
        case _:
            assert_never(kind)
    schedule_looped_sfx(effect, start_time, end_time)


def replace_looped_particle(handle: ParticleHandle, particle: Particle, layout: QuadLike, duration: float):
    if handle.id != 0:
        handle.destroy()
    handle @= particle.spawn(layout, duration / Options.effect_animation_speed, loop=True)


def update_looped_particle(handle: ParticleHandle, layout: QuadLike):
    if handle.id != 0:
        handle.move(layout)


def destroy_looped_particle(handle: ParticleHandle):
    if handle.id != 0:
        handle.destroy()
        handle.id = 0


def replace_looped_sfx(handle: LoopedEffectHandle, effect: Effect):
    if handle.id != 0:
        handle.stop()
    handle @= effect.loop()


def destroy_looped_sfx(handle: LoopedEffectHandle):
    if handle.id != 0:
        handle.stop()
        handle.id = 0


def schedule_looped_sfx(effect: Effect, start_time: float, end_time: float):
    effect.schedule_loop(start_time).stop(end_time)
