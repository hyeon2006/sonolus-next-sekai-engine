from __future__ import annotations

from sonolus.script.archetype import EntityRef, WatchArchetype, callback, entity_data, entity_memory, imported
from sonolus.script.interval import Interval, lerp
from sonolus.script.particle import ParticleHandle
from sonolus.script.runtime import delta_time, is_replay, is_skip, time

from sekai.debug import DISABLE_NOTES
from sekai.lib import archetype_names
from sekai.lib.connector import (
    CONNECTOR_LENIENCY,
    CONNECTOR_PARTICLE_ACTIVE_DELAY,
    CONNECTOR_SLOT_SPAWN_PERIOD,
    CONNECTOR_THROUGH_JUDGE_LINE_DESPAWN_DELAY,
    CONNECTOR_TRAIL_SPAWN_PERIOD,
    ActiveConnectorInfo,
    ConnectorKind,
    ConnectorVisualState,
    destroy_looped_particle,
    draw_connector,
    draw_connector_slot_glow_effect,
    get_connector_fractions,
    get_connector_interp_frac,
    should_show_connector_hitbox,
    spawn_connector_slot_particles,
    spawn_linear_connector_trail_particle,
    update_circular_connector_particle,
    update_linear_connector_particle,
)
from sekai.lib.ease import EaseType, safe_unlerp_clamped
from sekai.lib.layout import StageTransform, blend_stage_transform
from sekai.lib.note import draw_connector_hitbox_overlay, draw_slide_note_head, get_attach_params
from sekai.lib.options import Options
from sekai.lib.stage import VisualMask, get_stage_props, masked_note_extents_by_limits
from sekai.lib.streams import Streams
from sekai.lib.timescale import (
    group_hide_notes,
    group_scaled_time_to_first_time,
    group_time_to_scaled_time,
    update_timescale_group,
)
from sekai.watch import note


def legacy_note_duration() -> float:
    return lerp(0.35, 4, safe_unlerp_clamped(12, 1, Options.note_speed) ** 1.31)


class WatchConnector(WatchArchetype):
    name = archetype_names.CONNECTOR

    head_ref: EntityRef[note.WatchBaseNote] = imported(name="head")
    tail_ref: EntityRef[note.WatchBaseNote] = imported(name="tail")
    segment_head_ref: EntityRef[note.WatchBaseNote] = imported(name="segmentHead")
    segment_tail_ref: EntityRef[note.WatchBaseNote] = imported(name="segmentTail")
    active_head_ref: EntityRef[note.WatchBaseNote] = imported(name="activeHead")
    active_tail_ref: EntityRef[note.WatchBaseNote] = imported(name="activeTail")
    legacy_hidden_pop: bool = imported(name="legacyHiddenPop")

    kind: ConnectorKind = entity_data()
    ease_type: EaseType = entity_data()
    start_time: float = entity_data()
    end_time: float = entity_data()
    visual_active_interval: Interval = entity_data()
    # Temporary linked-list pointers used only during preprocess to sort connectors by their
    # activation / deactivation times for the auto-SFX sweep (see schedule_auto_connector_sfx_kind).
    # entity_data (not entity_memory) so they can be written cross-entity from preprocess.
    sfx_act_next: EntityRef[WatchConnector] = entity_data()
    sfx_deact_next: EntityRef[WatchConnector] = entity_data()

    @callback(order=1)
    def preprocess(self):
        if DISABLE_NOTES:
            return
        head = self.head
        tail = self.tail
        self.kind = self.segment_head.segment_kind
        self.ease_type = head.connector_ease
        self.visual_active_interval.start = min(head.target_time, tail.target_time)
        self.visual_active_interval.end = max(head.target_time, tail.target_time)
        if self.legacy_hidden_pop:
            head_scaled_time = group_time_to_scaled_time(
                self.segment_head.timescale_group,
                self.segment_head.target_time,
            ).total
            self.visual_active_interval.start = group_scaled_time_to_first_time(
                self.segment_head.timescale_group,
                head_scaled_time - legacy_note_duration(),
            )
            self.visual_active_interval.end = tail.target_time
            self.start_time = self.visual_active_interval.start
            self.end_time = self.visual_active_interval.end
        else:
            self.start_time = min(
                self.visual_active_interval.start,
                head.start_time,
                tail.start_time,
            )
            self.end_time = self.visual_active_interval.end
        if self.segment_head.segment_through_judge_line:
            self.end_time += CONNECTOR_THROUGH_JUDGE_LINE_DESPAWN_DELAY

        head.extend_stage_windows(self.start_time - 1.0, self.end_time + 1.0)
        tail.extend_stage_windows(self.start_time - 1.0, self.end_time + 1.0)

        if self.head_ref.index == self.active_head_ref.index:
            # This is the first connector, so spawn the WatchSlideManager.
            WatchSlideManager.spawn(active_head_ref=self.active_head_ref, active_tail_ref=self.active_tail_ref)

    def spawn_time(self) -> float:
        if DISABLE_NOTES:
            return 1e8
        return self.start_time

    def despawn_time(self) -> float:
        return self.end_time

    @callback(order=-1)
    def update_sequential(self):
        update_timescale_group(self.head.timescale_group)
        update_timescale_group(self.tail.timescale_group)
        update_timescale_group(self.segment_head.timescale_group)

        current_time = time()

        if self.active_head_ref.index > 0 and current_time in self.visual_active_interval:
            visual_lane, visual_size = self.current_visual_head_extents(current_time)
            head = self.head
            tail = self.tail
            self.active_connector_info.visual_lane = visual_lane
            self.active_connector_info.visual_size = visual_size
            self.active_connector_info.visual_y_offset = lerp(
                head.visual_y_offset,
                tail.visual_y_offset,
                safe_unlerp_clamped(head.target_time, tail.target_time, current_time),
            )
            self.active_connector_info.connector_kind = self.kind
        if group_hide_notes(self.segment_head.timescale_group) and self.active_head_ref.index > 0:
            self.active_connector_info.connector_kind = ConnectorKind.NONE

    def update_parallel(self):
        self.draw_hitbox()
        current_time = time()
        if current_time < self.visual_active_interval.end or self.segment_head.segment_through_judge_line:
            head = self.head
            tail = self.tail
            segment_head = self.segment_head
            segment_tail = self.segment_tail
            if self.active_head_ref.index > 0:
                if is_replay():
                    visual_state = Streams.connector_visual_states[self.index].get_previous_inclusive(current_time)
                elif self.kind == ConnectorKind.DAMAGE:
                    # Autoplay never touches damage connectors.
                    visual_state = ConnectorVisualState.WAITING
                elif current_time < self.active_head.target_time:
                    visual_state = ConnectorVisualState.WAITING
                else:
                    visual_state = ConnectorVisualState.ACTIVE
            else:
                visual_state = ConnectorVisualState.WAITING
            if group_hide_notes(segment_head.timescale_group):
                return
            if self.active_tail_ref.index > 0 and current_time >= self.active_tail.despawn_time():
                return
            head_transform = +StageTransform
            tail_transform = +StageTransform
            tail_transform @= tail.visual_stage_transform()
            head_mask = +VisualMask
            head_mask @= head.visual_mask
            tail_mask = tail.visual_mask
            if current_time >= head.target_time and not segment_head.segment_through_judge_line:
                head_frac = safe_unlerp_clamped(head.target_time, tail.target_time, current_time)
                head_visual_progress = 1.0 - lerp(head.visual_y_offset, tail.visual_y_offset, head_frac)
                head_target_time = current_time
                head_note_alpha = lerp(head.visual_note_alpha, tail.visual_note_alpha, head_frac)
                if self.ease_type == EaseType.NONE:
                    head_lane = head.visual_lane
                    head_size = head.size
                    head_ease_frac = head.head_ease_frac
                    head_transform @= head.visual_stage_transform()
                else:
                    head_ease_frac = lerp(head.head_ease_frac, tail.tail_ease_frac, head_frac)
                    head_interp_frac = get_connector_interp_frac(
                        self.ease_type,
                        head.head_ease_frac,
                        tail.tail_ease_frac,
                        head_ease_frac,
                        head_frac,
                    )
                    head_lane = lerp(head.visual_lane, tail.visual_lane, head_interp_frac)
                    head_size = lerp(head.size, tail.size, head_interp_frac)
                    if head_mask.enabled and tail_mask.enabled:
                        head_mask.left = lerp(head_mask.left, tail_mask.left, head_interp_frac)
                        head_mask.right = lerp(head_mask.right, tail_mask.right, head_interp_frac)
                    # Head has crossed the judge line, so its transform is the connector's blend at that point.
                    head_transform @= blend_stage_transform(
                        head.visual_stage_transform(), tail.visual_stage_transform(), head_interp_frac
                    )
            else:
                head_lane = head.visual_lane
                head_size = head.size
                head_visual_progress = head.visual_progress
                head_target_time = head.target_time
                head_ease_frac = head.head_ease_frac
                head_note_alpha = head.visual_note_alpha
                head_transform @= head.visual_stage_transform()
            draw_connector(
                kind=self.kind,
                visual_state=visual_state,
                ease_type=self.ease_type,
                head_lane=head_lane,
                head_size=head_size,
                head_visual_progress=head_visual_progress,
                head_target_time=head_target_time,
                head_ease_frac=head_ease_frac,
                tail_lane=tail.visual_lane,
                tail_size=tail.size,
                tail_visual_progress=tail.visual_progress,
                tail_target_time=tail.target_time,
                tail_ease_frac=tail.tail_ease_frac,
                segment_head_target_time=segment_head.target_time,
                segment_head_lane=segment_head.lane,
                segment_head_alpha=segment_head.segment_alpha,
                segment_tail_target_time=segment_tail.target_time,
                segment_tail_alpha=segment_tail.segment_alpha,
                layer=segment_head.segment_layer,
                presentation=segment_head.segment_presentation,
                bypass_tail_target_time_check=segment_head.segment_through_judge_line,
                head_transform=head_transform,
                tail_transform=tail_transform,
                head_note_alpha=head_note_alpha,
                tail_note_alpha=tail.visual_note_alpha,
                head_mask=head_mask,
                tail_mask=tail_mask,
            )

    def draw_hitbox(self):
        if not Options.show_hitboxes:
            return
        if self.active_head_ref.index <= 0 or not should_show_connector_hitbox(self.kind):
            return
        if time() in self.visual_active_interval:
            bounds = note.compute_slide_input_bounds(
                self.ease_type,
                self.head,
                self.tail,
                time(),
                CONNECTOR_LENIENCY,
            )
            draw_connector_hitbox_overlay(bounds, 0.6)

    def get_attached_params(self, target_time: float) -> tuple[float, float]:
        head = self.head_ref.get().effective_attach_head
        tail = self.tail_ref.get().effective_attach_tail
        if head.stage_ref.index > 0 and head.stage_ref.index == tail.stage_ref.index:
            stage = head.stage_ref.get()
            if target_time == time():
                pivot_lane = stage.props.pivot_lane
            else:
                pivot_lane = get_stage_props(stage, target_time).pivot_lane
            head_lane = pivot_lane + head.rel_lane
            tail_lane = pivot_lane + tail.rel_lane
        else:
            head_lane = head._basic_visual_lane_at(target_time)
            tail_lane = tail._basic_visual_lane_at(target_time)
        return get_attach_params(
            ease_type=self.ease_type,
            head_lane=head_lane,
            head_size=head.size,
            head_target_time=head.target_time,
            tail_lane=tail_lane,
            tail_size=tail.size,
            tail_target_time=tail.target_time,
            target_time=target_time,
        )

    def current_visual_head_extents(self, target_time: float) -> tuple[float, float]:
        head = self.head
        tail = self.tail
        result_lane, result_size = self.get_attached_params(target_time)
        head_mask = head.visual_mask
        tail_mask = tail.visual_mask
        mask_left = head_mask.left
        mask_right = head_mask.right
        if self.ease_type != EaseType.NONE:
            _, interp_frac = get_connector_fractions(
                self.ease_type,
                head.target_time,
                head.head_ease_frac,
                tail.target_time,
                tail.tail_ease_frac,
                target_time,
            )
            mask_left = lerp(head_mask.left, tail_mask.left, interp_frac)
            mask_right = lerp(head_mask.right, tail_mask.right, interp_frac)
        return masked_note_extents_by_limits(
            result_lane,
            result_size,
            mask_left,
            mask_right,
            head_mask.enabled and tail_mask.enabled,
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

    @property
    def active_head(self):
        return self.active_head_ref.get()

    @property
    def active_tail(self):
        return self.active_tail_ref.get()

    @property
    def active_connector_info(self) -> ActiveConnectorInfo:
        return self.active_head_ref.get().active_connector_info


class WatchSlideManager(WatchArchetype):
    name = archetype_names.SLIDE_MANAGER

    active_head_ref: EntityRef[note.WatchBaseNote] = entity_memory()
    active_tail_ref: EntityRef[note.WatchBaseNote] = entity_memory()

    last_kind: ConnectorKind = entity_memory()
    circular_particle: ParticleHandle = entity_memory()
    linear_particle: ParticleHandle = entity_memory()
    next_trail_spawn_time: float = entity_memory()
    next_slot_spawn_time: float = entity_memory()
    seg_cursor_ref: EntityRef[note.WatchBaseNote] = entity_memory()

    def initialize(self):
        self.next_trail_spawn_time = -1e8
        self.next_slot_spawn_time = -1e8

    def spawn_time(self) -> float:
        return self.active_head.target_time

    def despawn_time(self) -> float:
        return self.active_tail.despawn_time()

    def update_parallel(self):
        current_time = time()
        skipping = is_skip()
        if skipping:
            destroy_looped_particle(self.circular_particle)
            destroy_looped_particle(self.linear_particle)
            self.next_trail_spawn_time = current_time + CONNECTOR_TRAIL_SPAWN_PERIOD / Options.effect_animation_speed
            self.next_slot_spawn_time = current_time + CONNECTOR_SLOT_SPAWN_PERIOD / Options.effect_animation_speed
        if current_time < self.active_head.target_time:
            return
        info = self.active_head.active_connector_info
        segment_transform, segment_note_alpha = self.active_segment_transform_and_note_alpha()
        head_transform = segment_transform.transform()
        connector_kind = (
            Streams.connector_effect_kinds[self.active_head.index].get_previous_inclusive(current_time)
            if is_replay()
            else info.connector_kind
        )
        if not is_replay() and current_time < self.active_head.target_time + CONNECTOR_PARTICLE_ACTIVE_DELAY:
            connector_kind = ConnectorKind.NONE
        match connector_kind:
            case (
                ConnectorKind.ACTIVE_NORMAL
                | ConnectorKind.ACTIVE_CRITICAL
                | ConnectorKind.ACTIVE_FAKE_NORMAL
                | ConnectorKind.ACTIVE_FAKE_CRITICAL
            ):
                replace = connector_kind != self.last_kind
                self.last_kind = connector_kind
                if not skipping:
                    update_circular_connector_particle(
                        self.circular_particle,
                        connector_kind,
                        info.visual_lane,
                        replace,
                        info.visual_y_offset,
                        transform=head_transform,
                    )
                    update_linear_connector_particle(
                        self.linear_particle,
                        connector_kind,
                        info.visual_lane,
                        replace,
                        info.visual_y_offset,
                        transform=head_transform,
                    )
                    trail_period = CONNECTOR_TRAIL_SPAWN_PERIOD / Options.effect_animation_speed
                    if current_time >= self.next_trail_spawn_time:
                        self.next_trail_spawn_time = max(
                            self.next_trail_spawn_time + trail_period,
                            current_time + trail_period / 2,
                        )
                        spawn_linear_connector_trail_particle(
                            connector_kind, info.visual_lane, info.visual_y_offset, transform=head_transform
                        )
                    if info.visual_size > 0:
                        slot_period = CONNECTOR_SLOT_SPAWN_PERIOD / Options.effect_animation_speed
                        if current_time >= self.next_slot_spawn_time:
                            self.next_slot_spawn_time = max(
                                self.next_slot_spawn_time + slot_period,
                                current_time + slot_period / 2,
                            )
                            spawn_connector_slot_particles(
                                connector_kind,
                                info.visual_lane,
                                info.visual_size,
                                info.visual_y_offset,
                                transform=head_transform,
                            )
                        draw_connector_slot_glow_effect(
                            connector_kind,
                            self.active_head.target_time,
                            info.visual_lane,
                            info.visual_size,
                            info.visual_y_offset,
                            transform=head_transform,
                        )
                else:
                    destroy_looped_particle(self.circular_particle)
                    destroy_looped_particle(self.linear_particle)
            case _:
                destroy_looped_particle(self.circular_particle)
                destroy_looped_particle(self.linear_particle)

        if current_time + delta_time() > self.active_tail.despawn_time():
            return
        match info.connector_kind:
            case (
                ConnectorKind.ACTIVE_NORMAL
                | ConnectorKind.ACTIVE_CRITICAL
                | ConnectorKind.ACTIVE_FAKE_NORMAL
                | ConnectorKind.ACTIVE_FAKE_CRITICAL
                | ConnectorKind.DAMAGE
            ) if info.visual_size > 0:
                draw_slide_note_head(
                    self.active_head.kind,
                    info.connector_kind,
                    info.visual_lane,
                    info.visual_size,
                    self.active_head.target_time,
                    1.0 - info.visual_y_offset,
                    transform=head_transform,
                    note_alpha=segment_note_alpha,
                )
            case _:
                pass

    def terminate(self):
        destroy_looped_particle(self.circular_particle)
        destroy_looped_particle(self.linear_particle)

    def active_segment_transform_and_note_alpha(self) -> tuple[StageTransform, float]:
        result = +StageTransform
        head_ref = +self.active_head_ref
        if self.seg_cursor_ref.index > 0 and self.seg_cursor_ref.get().target_time <= time():
            head_ref.index = self.seg_cursor_ref.index
        next_ref = +head_ref.get().next_ref
        while next_ref.index > 0 and time() >= next_ref.get().target_time:
            head_ref.index = next_ref.index
            next_ref.index = head_ref.get().next_ref.index
        self.seg_cursor_ref.index = head_ref.index
        seg_head = head_ref.get()
        note_alpha = seg_head.visual_note_alpha
        if next_ref.index > 0:
            seg_tail = next_ref.get()
            frac, transform_frac = get_connector_fractions(
                seg_head.connector_ease,
                seg_head.target_time,
                seg_head.head_ease_frac,
                seg_tail.target_time,
                seg_tail.tail_ease_frac,
                time(),
            )
            result @= blend_stage_transform(
                seg_head.visual_stage_transform(),
                seg_tail.visual_stage_transform(),
                transform_frac,
            )
            note_alpha = lerp(seg_head.visual_note_alpha, seg_tail.visual_note_alpha, frac)
        else:
            result @= seg_head.visual_stage_transform()
        return result, note_alpha

    @property
    def active_head(self) -> note.WatchBaseNote:
        return self.active_head_ref.get()

    @property
    def active_tail(self) -> note.WatchBaseNote:
        return self.active_tail_ref.get()


WATCH_CONNECTOR_ARCHETYPES = (
    WatchConnector,
    WatchSlideManager,
)
