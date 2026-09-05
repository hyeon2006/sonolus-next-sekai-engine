from math import ceil
from typing import assert_never

from sonolus.script.archetype import EntityRef, PreviewArchetype, callback, entity_data, imported
from sonolus.script.array import Dim
from sonolus.script.containers import VarArray
from sonolus.script.interval import clamp, lerp
from sonolus.script.record import Record
from sonolus.script.sprite import Sprite

from sekai.lib import archetype_names
from sekai.lib.connector import (
    CONNECTOR_ZERO_SIZE_FALLBACK,
    ConnectorKind,
    ConnectorLayer,
    get_active_connector_sprites,
    get_connector_alpha_option,
    get_connector_fractions,
    get_connector_quality_option,
    get_connector_z,
    get_damage_connector_sprite,
    get_guide_connector_sprite,
    masked_connector_extents_by_limits,
)
from sekai.lib.ease import EaseType, safe_unlerp_clamped
from sekai.lib.layout import get_alpha
from sekai.lib.level_config import LevelConfig
from sekai.lib.stage import interpolate_visual_masks
from sekai.preview import note
from sekai.preview.layout import (
    get_adjusted_time,
    layout_preview_slide_connector_segment,
    preview_axis_to_y,
    preview_column_secs,
    time_to_preview_col,
)


class PreviewConnector(PreviewArchetype):
    name = archetype_names.CONNECTOR

    head_ref: EntityRef[note.PreviewBaseNote] = imported(name="head")
    tail_ref: EntityRef[note.PreviewBaseNote] = imported(name="tail")
    segment_head_ref: EntityRef[note.PreviewBaseNote] = imported(name="segmentHead")
    segment_tail_ref: EntityRef[note.PreviewBaseNote] = imported(name="segmentTail")

    kind: ConnectorKind = entity_data()
    ease_type: EaseType = entity_data()

    @callback(order=1)  # After note preprocessing is done
    def preprocess(self):
        head = self.head
        self.kind = self.segment_head.segment_kind
        self.ease_type = head.connector_ease

    def render(self):
        head = self.head
        tail = self.tail
        draw_connector(
            kind=self.kind,
            ease_type=self.ease_type,
            head_ref=self.head_ref,
            head_size=head.size,
            head_target_time=head.target_time,
            head_preview_axis=head.preview_axis,
            head_ease_frac=head.head_ease_frac,
            tail_ref=self.tail_ref,
            tail_size=tail.size,
            tail_target_time=tail.target_time,
            tail_preview_axis=tail.preview_axis,
            tail_ease_frac=tail.tail_ease_frac,
            segment_head_target_time=self.segment_head.target_time,
            segment_head_lane=self.segment_head.lane,
            segment_head_alpha=self.segment_head.segment_alpha,
            segment_tail_target_time=self.segment_tail.target_time,
            segment_tail_alpha=self.segment_tail.segment_alpha,
            layer=self.segment_head.segment_layer,
        )

    @property
    def head(self):
        return self.head_ref.get()

    @property
    def tail(self):
        return self.tail_ref.get()

    @property
    def segment_head(self):
        return self.segment_head_ref.get()

    @property
    def segment_tail(self):
        return self.segment_tail_ref.get()


class PreviewConnectorSample(Record):
    raw_lane: float
    raw_size: float
    lane: float
    size: float
    masked_size: float
    mask_left: float
    mask_right: float
    mask_enabled: bool


def draw_connector(
    kind: ConnectorKind,
    ease_type: EaseType,
    head_ref: EntityRef[note.PreviewBaseNote],
    head_size: float,
    head_target_time: float,
    head_preview_axis: float,
    head_ease_frac: float,
    tail_ref: EntityRef[note.PreviewBaseNote],
    tail_size: float,
    tail_target_time: float,
    tail_preview_axis: float,
    tail_ease_frac: float,
    segment_head_target_time: float,
    segment_head_lane: float,
    segment_head_alpha: float,
    segment_tail_target_time: float,
    segment_tail_alpha: float,
    layer: ConnectorLayer,
):
    if head_target_time == tail_target_time:
        return

    if ease_type == EaseType.NONE:
        tail_size = head_size

    normal_sprite = Sprite(-1)
    match kind:
        case (
            ConnectorKind.ACTIVE_NORMAL
            | ConnectorKind.ACTIVE_CRITICAL
            | ConnectorKind.ACTIVE_FAKE_NORMAL
            | ConnectorKind.ACTIVE_FAKE_CRITICAL
        ):
            sprites = get_active_connector_sprites(kind)
            normal_sprite @= sprites.connection.normal
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
            normal_sprite @= get_guide_connector_sprite(kind)
        case ConnectorKind.DAMAGE | ConnectorKind.FAKE_DAMAGE:
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
        case (
            ConnectorKind.GUIDE_NEUTRAL
            | ConnectorKind.GUIDE_RED
            | ConnectorKind.GUIDE_GREEN
            | ConnectorKind.GUIDE_BLUE
            | ConnectorKind.GUIDE_YELLOW
            | ConnectorKind.GUIDE_PURPLE
            | ConnectorKind.GUIDE_CYAN
            | ConnectorKind.GUIDE_BLACK
            | ConnectorKind.DAMAGE
            | ConnectorKind.FAKE_DAMAGE
        ):
            pass
        case _:
            assert_never(kind)

    head_alpha = lerp(
        segment_head_alpha,
        segment_tail_alpha,
        safe_unlerp_clamped(segment_head_target_time, segment_tail_target_time, head_target_time),
    )
    tail_alpha = lerp(
        segment_head_alpha,
        segment_tail_alpha,
        safe_unlerp_clamped(segment_head_target_time, segment_tail_target_time, tail_target_time),
    )

    match ease_type:
        case EaseType.NONE | EaseType.LINEAR if head_alpha == tail_alpha and not LevelConfig.dynamic_stages:
            quality_dist_scale = 0
        case _:
            quality_dist_scale = 100 * abs(tail_target_time - head_target_time) / preview_column_secs()
    quality_alpha_scale = 30 * abs(head_alpha - tail_alpha)
    segment_count = max(1, ceil(get_connector_quality_option(kind) * max(quality_dist_scale, quality_alpha_scale)))

    head = head_ref.get()
    tail = tail_ref.get()

    # The note at the head uses the left limit, but the connector occupies the interval after it.
    # Start from the right limit so a style change at the head is not smeared across the first slice.
    last_sample = connector_sample_at(
        head,
        tail,
        ease_type,
        head_size,
        head_target_time,
        head_ease_frac,
        tail_size,
        tail_target_time,
        tail_ease_frac,
        head_target_time,
        left_limit=False,
    )
    last_alpha = head_alpha
    last_target_time = head_target_time
    last_axis = head_preview_axis

    for i in range(1, segment_count + 1):
        interval_end_time = lerp(head_target_time, tail_target_time, i / segment_count)
        while last_target_time < interval_end_time:
            # End a slice on the left side of every stage event, then restart at the same time on its right side.
            next_event_time = min(
                head.next_visual_mask_event_time(last_target_time),
                tail.next_visual_mask_event_time(last_target_time),
            )
            at_event = next_event_time <= interval_end_time
            next_target_time = min(interval_end_time, next_event_time)
            next_sample = connector_sample_at(
                head,
                tail,
                ease_type,
                head_size,
                head_target_time,
                head_ease_frac,
                tail_size,
                tail_target_time,
                tail_ease_frac,
                next_target_time,
                left_limit=at_event,
            )
            next_alpha = lerp(
                head_alpha,
                tail_alpha,
                safe_unlerp_clamped(head_target_time, tail_target_time, next_target_time),
            )
            next_axis = lerp(
                head_preview_axis,
                tail_preview_axis,
                safe_unlerp_clamped(head_target_time, tail_target_time, next_target_time),
            )
            a = clamp(
                get_alpha((last_target_time + next_target_time) / 2)
                * (last_alpha + next_alpha)
                / 2
                * get_connector_alpha_option(kind),
                0,
                1,
            )
            draw_preview_connector_sample_span(
                normal_sprite,
                kind,
                layer,
                segment_head_target_time,
                segment_head_lane,
                last_sample,
                next_sample,
                last_target_time,
                next_target_time,
                last_axis,
                next_axis,
                a,
            )

            last_sample @= next_sample
            last_alpha = next_alpha
            last_target_time = next_target_time
            last_axis = next_axis
            if at_event and last_target_time < tail_target_time:
                last_sample @= connector_sample_at(
                    head,
                    tail,
                    ease_type,
                    head_size,
                    head_target_time,
                    head_ease_frac,
                    tail_size,
                    tail_target_time,
                    tail_ease_frac,
                    last_target_time,
                    left_limit=False,
                )


def connector_sample_at(
    head: note.PreviewBaseNote,
    tail: note.PreviewBaseNote,
    ease_type: EaseType,
    head_size: float,
    head_target_time: float,
    head_ease_frac: float,
    tail_size: float,
    tail_target_time: float,
    tail_ease_frac: float,
    target_time: float,
    *,
    left_limit: bool,
) -> PreviewConnectorSample:
    result = +PreviewConnectorSample
    _, interp_frac = get_connector_fractions(
        ease_type,
        head_target_time,
        head_ease_frac,
        tail_target_time,
        tail_ease_frac,
        target_time,
    )
    head_lane = head.visual_lane_at(target_time, left_limit=left_limit)
    tail_lane = head_lane if ease_type == EaseType.NONE else tail.visual_lane_at(target_time, left_limit=left_limit)
    result.raw_lane = lerp(head_lane, tail_lane, interp_frac)
    result.raw_size = lerp(head_size, tail_size, interp_frac)
    mask = interpolate_visual_masks(
        head.visual_mask_at(target_time, left_limit=left_limit),
        tail.visual_mask_at(target_time, left_limit=left_limit),
        interp_frac,
    )
    result.lane = result.raw_lane
    result.size = max(result.raw_size, CONNECTOR_ZERO_SIZE_FALLBACK)
    result.masked_size = result.raw_size
    result.mask_left = mask.left
    result.mask_right = mask.right
    result.mask_enabled = mask.enabled
    if mask.enabled:
        result.lane, result.size, result.masked_size = masked_connector_extents_by_limits(
            result.raw_lane, result.raw_size, mask.left, mask.right
        )
    return result


def draw_preview_connector_sample_span(
    sprite: Sprite,
    kind: ConnectorKind,
    layer: ConnectorLayer,
    segment_head_target_time: float,
    segment_head_lane: float,
    start: PreviewConnectorSample,
    end: PreviewConnectorSample,
    start_time: float,
    end_time: float,
    start_axis: float,
    end_axis: float,
    alpha: float,
):
    if start.mask_enabled and end.mask_enabled:
        draw_masked_preview_connector_sample_span(
            sprite,
            kind,
            layer,
            segment_head_target_time,
            segment_head_lane,
            start,
            end,
            start_time,
            end_time,
            start_axis,
            end_axis,
            alpha,
        )
    else:
        draw_preview_connector_piece(
            sprite,
            kind,
            layer,
            segment_head_target_time,
            segment_head_lane,
            start.lane,
            start.size,
            start_time,
            end.lane,
            end.size,
            end_time,
            start_axis,
            end_axis,
            alpha,
        )


def draw_masked_preview_connector_sample_span(
    sprite: Sprite,
    kind: ConnectorKind,
    layer: ConnectorLayer,
    segment_head_target_time: float,
    segment_head_lane: float,
    start: PreviewConnectorSample,
    end: PreviewConnectorSample,
    start_time: float,
    end_time: float,
    start_axis: float,
    end_axis: float,
    alpha: float,
):
    # Split wherever a raw connector edge crosses a moving mask edge. This preserves a visible interior even when
    # both ends of the original sample are fully outside opposite sides of the mask.
    split_fracs = VarArray[float, Dim[5]].new()
    split_fracs.append(1.0)
    append_connector_mask_crossing(
        split_fracs,
        start.raw_lane - start.raw_size - start.mask_left,
        end.raw_lane - end.raw_size - end.mask_left,
    )
    append_connector_mask_crossing(
        split_fracs,
        start.raw_lane - start.raw_size - start.mask_right,
        end.raw_lane - end.raw_size - end.mask_right,
    )
    append_connector_mask_crossing(
        split_fracs,
        start.raw_lane + start.raw_size - start.mask_left,
        end.raw_lane + end.raw_size - end.mask_left,
    )
    append_connector_mask_crossing(
        split_fracs,
        start.raw_lane + start.raw_size - start.mask_right,
        end.raw_lane + end.raw_size - end.mask_right,
    )
    split_fracs.sort()

    sub_start_frac = 0.0
    sub_start_lane = start.lane
    sub_start_size = start.size
    sub_start_masked_size = start.masked_size
    sub_start_axis = start_axis
    for sub_end_frac in split_fracs:
        if sub_end_frac <= sub_start_frac:
            continue
        sub_end_raw_lane = lerp(start.raw_lane, end.raw_lane, sub_end_frac)
        sub_end_raw_size = lerp(start.raw_size, end.raw_size, sub_end_frac)
        sub_end_mask_left = lerp(start.mask_left, end.mask_left, sub_end_frac)
        sub_end_mask_right = lerp(start.mask_right, end.mask_right, sub_end_frac)
        sub_end_axis = lerp(start_axis, end_axis, sub_end_frac)
        sub_end_lane, sub_end_size, sub_end_masked_size = masked_connector_extents_by_limits(
            sub_end_raw_lane,
            sub_end_raw_size,
            sub_end_mask_left,
            sub_end_mask_right,
        )
        if sub_start_masked_size > 0 or sub_end_masked_size > 0:
            draw_preview_connector_piece(
                sprite,
                kind,
                layer,
                segment_head_target_time,
                segment_head_lane,
                sub_start_lane,
                sub_start_size,
                lerp(start_time, end_time, sub_start_frac),
                sub_end_lane,
                sub_end_size,
                lerp(start_time, end_time, sub_end_frac),
                sub_start_axis,
                sub_end_axis,
                alpha,
            )
        sub_start_frac = sub_end_frac
        sub_start_lane = sub_end_lane
        sub_start_size = sub_end_size
        sub_start_masked_size = sub_end_masked_size
        sub_start_axis = sub_end_axis


def append_connector_mask_crossing(split_fracs: VarArray[float, Dim[5]], start_delta: float, end_delta: float):
    if min(start_delta, end_delta) < 0 < max(start_delta, end_delta):
        split_fracs.append(-start_delta / (end_delta - start_delta))


def draw_preview_connector_piece(
    sprite: Sprite,
    kind: ConnectorKind,
    layer: ConnectorLayer,
    segment_head_target_time: float,
    segment_head_lane: float,
    start_lane: float,
    start_size: float,
    start_time: float,
    end_lane: float,
    end_size: float,
    end_time: float,
    start_axis: float,
    end_axis: float,
    alpha: float,
):
    start_col = time_to_preview_col(start_time)
    end_col = time_to_preview_col(end_time)
    for col in range(start_col, end_col + 1):
        z = get_connector_z(
            kind, get_adjusted_time(segment_head_target_time, col), segment_head_lane, active=False, layer=layer
        )
        start_y = preview_axis_to_y(start_axis, col)
        end_y = preview_axis_to_y(end_axis, col)
        for layout in layout_preview_slide_connector_segment(
            start_lane=start_lane,
            start_size=start_size,
            start_y=start_y,
            end_lane=end_lane,
            end_size=end_size,
            end_y=end_y,
            col=col,
        ):
            sprite.draw(layout, z=z.tuple, a=alpha)
