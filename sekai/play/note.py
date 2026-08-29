from __future__ import annotations

from math import pi
from typing import assert_never, cast

from sonolus.script.archetype import (
    AnyArchetype,
    EntityRef,
    PlayArchetype,
    StandardImport,
    entity_data,
    entity_memory,
    exported,
    imported,
    shared_memory,
)
from sonolus.script.array import Dim
from sonolus.script.bucket import Bucket, Judgment
from sonolus.script.containers import VarArray
from sonolus.script.globals import level_memory
from sonolus.script.interval import Interval, lerp
from sonolus.script.quad import Quad
from sonolus.script.runtime import Touch, delta_time, input_offset, offset_adjusted_time, time
from sonolus.script.timing import beat_to_time

from sekai.debug import DISABLE_NOTES
from sekai.lib import archetype_names
from sekai.lib.buckets import WINDOW_SCALE, SekaiWindow
from sekai.lib.connector import (
    ActiveConnectorInfo,
    ConnectorKind,
    ConnectorLayer,
    SegmentPresentation,
    get_connector_fractions,
)
from sekai.lib.ease import EaseType
from sekai.lib.layout import (
    IDENTITY_AFFINE_TRANSFORM,
    DynamicLayout,
    FlickDirection,
    Hitbox,
    Layout,
    StageTransform,
    blend_stage_transform,
    camera_layout_transform_at_time,
    compute_hitbox,
    compute_hitbox_at_time,
    compute_stage_transform,
    identity_stage_transform,
    progress_to,
)
from sekai.lib.note import (
    NoteEffectKind,
    NoteKind,
    damage_tick_input_start_beat,
    draw_hitbox_overlay,
    draw_note,
    get_attach_eased_frac,
    get_attach_frac,
    get_attach_params,
    get_leniency,
    get_note_bucket,
    get_note_effect_kind,
    get_note_haptic_feedback,
    get_note_window,
    get_visual_spawn_time,
    has_release_input,
    has_tap_input,
    hitbox_draw_alpha,
    hitbox_draw_start,
    is_head,
    map_note_kind,
    mirror_flick_direction,
    play_note_hit_effects,
    schedule_note_auto_sfx,
)
from sekai.lib.options import Options
from sekai.lib.stage import (
    DivisionParity,
    JudgeLineStyle,
    VisualMask,
    get_stage_props,
    interpolate_visual_masks,
    masked_note_extents_by_limits,
    resolve_judge_line_style,
)
from sekai.lib.timescale import (
    CompositeTime,
    group_force_note_speed,
    group_hide_notes,
    group_scaled_time,
    group_time_to_scaled_time,
    update_timescale_group,
)
from sekai.play import input_manager
from sekai.play.common import PlayLevelMemory
from sekai.play.dynamic_stage import DynamicStage

DEFAULT_BEST_TOUCH_TIME = -1e8


class BaseNote(PlayArchetype):
    beat: StandardImport.BEAT
    timescale_group: StandardImport.TIMESCALE_GROUP
    stage_ref: EntityRef[DynamicStage] = imported(name="stage")
    lane: float = imported()
    size: float = imported()
    direction: FlickDirection = imported()
    active_head_ref: EntityRef[BaseNote] = imported(name="activeHead")
    is_attached: bool = imported(name="isAttached")
    connector_ease: EaseType = imported(name="connectorEase")
    is_separator: bool = imported(name="isSeparator")
    segment_kind: ConnectorKind = imported(name="segmentKind")
    segment_alpha: float = imported(name="segmentAlpha")
    segment_layer: ConnectorLayer = imported(name="segmentLayer")
    segment_through_judge_line: bool = imported(name="segmentThroughJudgeLine")
    segment_presentation: SegmentPresentation = imported(name="segmentPresentation")
    attach_head_ref: EntityRef[BaseNote] = imported(name="attachHead")
    attach_tail_ref: EntityRef[BaseNote] = imported(name="attachTail")
    next_ref: EntityRef[BaseNote] = imported(name="next")
    prev_ref: EntityRef[BaseNote] = imported(name="prev")
    effect_kind: NoteEffectKind = imported(name="effectKind")

    kind: NoteKind = entity_data()
    data_init_done: bool = entity_data()
    rel_lane: float = entity_data()
    target_time: float = entity_data()
    visual_start_time: float = entity_data()
    start_time: float = entity_data()
    target_scaled_time: CompositeTime = entity_data()
    target_y_offset: float = entity_data()
    attach_eased_frac: float = entity_data()

    input_interval: Interval = shared_memory()
    unadjusted_input_interval: Interval = shared_memory()

    # The id of the tap that activated this note, for tap notes and flicks or released the note, for release notes.
    # This is set by the input manager rather than the note itself.
    captured_touch_id: int = shared_memory()
    captured_touch_time: float = shared_memory()

    active_connector_info: ActiveConnectorInfo = shared_memory()

    # For trace early touches
    best_touch_time: float = entity_memory()
    best_touch_matches_direction: bool = entity_memory()

    should_play_hit_effects: bool = entity_memory()

    hitbox: Hitbox = shared_memory()

    end_time: float = exported()
    played_hit_effects: bool = exported()

    @property
    def judgment_window(self) -> SekaiWindow:
        return get_note_window(self.kind)

    def init_data(self):
        if self.data_init_done:
            return

        self.kind = map_note_kind(cast(NoteKind, self.key))
        self.effect_kind = get_note_effect_kind(self.kind, self.effect_kind)

        self.data_init_done = True

        if Options.mirror:
            self.lane *= -1
            self.direction = mirror_flick_direction(self.direction)

        self.target_time = beat_to_time(self.beat)
        window = get_note_window(self.kind)
        self.input_interval = window.bad + self.target_time + input_offset()
        self.unadjusted_input_interval = window.bad + self.target_time

        if self.kind == NoteKind.HIDE_DAMAGE_TICK:
            window_start_beat = damage_tick_input_start_beat(self.beat)
            if self.active_head_ref.index > 0:
                window_start_beat = max(window_start_beat, self.active_head_ref.get().beat)
            window_start_time = beat_to_time(window_start_beat)
            self.input_interval = Interval(window_start_time, self.target_time) + input_offset()
            self.unadjusted_input_interval = Interval(window_start_time, self.target_time)

        if not self.is_attached:
            self.target_scaled_time = group_time_to_scaled_time(self.timescale_group, self.target_time)
            self.visual_start_time = get_visual_spawn_time(self.timescale_group, self.target_scaled_time)
            self.start_time = min(self.visual_start_time, self.input_interval.start)

        if self.stage_ref.index > 0:
            stage_props = get_stage_props(self.stage_ref.get(), self.target_time)
            self.rel_lane = self.lane
            self.lane += stage_props.pivot_lane
            self.target_y_offset = self._basic_y_offset_at(self.target_time, left_limit=True)

        if self.next_ref.index > 0:
            self.next_ref.get().prev_ref = self.ref()

    def preprocess(self):
        if DISABLE_NOTES:
            return
        self.init_data()

        self.result.bucket = get_note_bucket(self.kind)

        self.best_touch_time = DEFAULT_BEST_TOUCH_TIME
        self.active_connector_info.last_active_time = DEFAULT_BEST_TOUCH_TIME

        if self.is_attached:
            attach_head = self.attach_head_ref.get()
            attach_tail = self.attach_tail_ref.get()
            attach_head.init_data()
            attach_tail.init_data()
            self.connector_ease = attach_head.connector_ease
            self.attach_eased_frac = get_attach_eased_frac(
                self.connector_ease, attach_head.target_time, attach_tail.target_time, self.target_time
            )
            lane, size = get_attach_params(
                ease_type=attach_head.connector_ease,
                head_lane=attach_head._basic_visual_lane_at(self.target_time),
                head_size=attach_head.size,
                head_target_time=attach_head.target_time,
                tail_lane=attach_tail._basic_visual_lane_at(self.target_time),
                tail_size=attach_tail.size,
                tail_target_time=attach_tail.target_time,
                target_time=self.target_time,
            )
            self.lane = lane
            self.size = size
            self.visual_start_time = min(attach_head.visual_start_time, attach_tail.visual_start_time)
            self.start_time = min(self.visual_start_time, self.input_interval.start)
            self.target_y_offset = lerp(
                attach_head._basic_y_offset_at(self.target_time, left_limit=True),
                attach_tail._basic_y_offset_at(self.target_time, left_limit=True),
                get_attach_frac(attach_head.target_time, attach_tail.target_time, self.target_time),
            )

        if self.is_scored:
            schedule_note_auto_sfx(self.effect_kind, self.target_time)
            hitbox_lane, hitbox_size = self.visual_extents_at(self.target_time, left_limit=True)
            self.hitbox @= compute_hitbox_at_time(
                hitbox_lane,
                hitbox_size,
                get_leniency(self.kind),
                self.target_time,
                self.target_y_offset,
                stage_transform=self.stage_transform_at(self.target_time, left_limit=True).transform(),
                left_limit=True,
            )

        self.extend_stage_windows(self.start_time - 1.0, max(self.target_time, self.input_interval.end) + 1.0)

    def _basic_extend_stage_window(self, start_time: float, end_time: float):
        if self.stage_ref.index > 0:
            stage = self.stage_ref.get()
            stage.start_time = min(stage.start_time, start_time)
            stage.end_time = max(stage.end_time, end_time)

    def extend_stage_windows(self, start_time: float, end_time: float):
        if self.is_attached:
            self.attach_head_ref.get()._basic_extend_stage_window(start_time, end_time)
            self.attach_tail_ref.get()._basic_extend_stage_window(start_time, end_time)
        self._basic_extend_stage_window(start_time, end_time)

    def spawn_order(self) -> float:
        if DISABLE_NOTES or self.kind == NoteKind.ANCHOR:
            return 1e8
        return self.start_time

    def should_spawn(self) -> bool:
        if DISABLE_NOTES or self.kind == NoteKind.ANCHOR:
            return False
        return time() >= self.start_time

    def update_sequential(self):
        if self.despawn:
            return

        update_timescale_group(self.timescale_group)

        if self.kind == NoteKind.HIDE_DAMAGE_TICK and self.is_scored and time() in self.input_interval:
            self.hitbox.bounds @= self.damage_tick_input_bounds(offset_adjusted_time())

        if self.should_do_delayed_trigger():
            if self.best_touch_matches_direction:
                self.judge(self.best_touch_time)
            else:
                self.judge_wrong_way(self.best_touch_time)
            return
        if self.is_scored and time() in self.input_interval and self.captured_touch_id == 0:
            if has_tap_input(self.kind):
                NoteMemory.active_tap_input_notes.append(self.ref())
            elif has_release_input(self.kind) and (
                self.active_head_ref.index <= 0
                or self.active_head_ref.get().is_despawned
                or self.active_head_ref.get().captured_touch_id != 0
                or not self.active_head_ref.get().is_scored
            ):
                NoteMemory.active_release_input_notes.append(self.ref())

    def touch(self):
        if not self.is_scored:
            return
        if self.despawn:
            return
        if time() < self.input_interval.start:
            return
        kind = self.kind
        match kind:
            case (
                NoteKind.NORM_TAP
                | NoteKind.CRIT_TAP
                | NoteKind.NORM_HEAD_TAP
                | NoteKind.CRIT_HEAD_TAP
                | NoteKind.NORM_TAIL_TAP
                | NoteKind.CRIT_TAIL_TAP
            ):
                self.handle_tap_input()
            case NoteKind.NORM_FLICK | NoteKind.CRIT_FLICK | NoteKind.NORM_HEAD_FLICK | NoteKind.CRIT_HEAD_FLICK:
                self.handle_flick_input()
            case (
                NoteKind.NORM_TRACE
                | NoteKind.CRIT_TRACE
                | NoteKind.NORM_HEAD_TRACE
                | NoteKind.CRIT_HEAD_TRACE
                | NoteKind.NORM_TAIL_TRACE
                | NoteKind.CRIT_TAIL_TRACE
            ):
                self.handle_trace_input()
            case (
                NoteKind.NORM_TRACE_FLICK
                | NoteKind.CRIT_TRACE_FLICK
                | NoteKind.NORM_HEAD_TRACE_FLICK
                | NoteKind.CRIT_HEAD_TRACE_FLICK
                | NoteKind.NORM_TAIL_FLICK
                | NoteKind.CRIT_TAIL_FLICK
                | NoteKind.NORM_TAIL_TRACE_FLICK
                | NoteKind.CRIT_TAIL_TRACE_FLICK
            ):
                self.handle_trace_flick_input()
            case (
                NoteKind.NORM_RELEASE
                | NoteKind.CRIT_RELEASE
                | NoteKind.NORM_HEAD_RELEASE
                | NoteKind.CRIT_HEAD_RELEASE
                | NoteKind.NORM_TAIL_RELEASE
                | NoteKind.CRIT_TAIL_RELEASE
            ):
                self.handle_release_input()
            case NoteKind.NORM_TICK | NoteKind.CRIT_TICK | NoteKind.HIDE_TICK:
                self.handle_tick_input()
            case NoteKind.DAMAGE:
                self.handle_damage_input()
            case NoteKind.HIDE_DAMAGE_TICK:
                self.handle_damage_tick_input()
            case NoteKind.ANCHOR:
                pass
            case _:
                assert_never(kind)

    def update_parallel(self):
        if self.despawn:
            return
        if not self.is_scored and time() >= self.target_time:
            self.despawn = True
            return
        if time() > self.input_interval.end:
            self.handle_late_miss()
            return
        self.draw_hitbox()
        if time() < self.visual_start_time:
            return
        if is_head(self.kind) and time() > self.target_time:
            return
        if group_hide_notes(self.timescale_group):
            return
        if Options.disable_fake_notes and not self.is_scored:
            return
        render_lane, render_size = self.visual_extents
        if render_size <= 0:
            return
        if self.has_stage_transform():
            draw_note(
                self.kind,
                render_lane,
                render_size,
                self.visual_progress,
                self.direction,
                self.target_time,
                transform=self.visual_stage_transform().transform(),
                note_alpha=self.visual_note_alpha,
            )
        else:
            draw_note(
                self.kind,
                render_lane,
                render_size,
                self.visual_progress,
                self.direction,
                self.target_time,
                transform=IDENTITY_AFFINE_TRANSFORM,
                note_alpha=self.visual_note_alpha,
            )

    def draw_hitbox(self):
        if not Options.allow_debug_options_in_play_mode or not Options.show_hitboxes or not self.is_scored:
            return
        draw_start = hitbox_draw_start(self.kind, self.unadjusted_input_interval.start, self.target_time)
        if draw_start <= offset_adjusted_time() <= self.unadjusted_input_interval.end:
            draw_hitbox_overlay(
                self.hitbox,
                self.kind,
                hitbox_draw_alpha(self.kind, draw_start, self.target_time, offset_adjusted_time()),
                time_to_target=self.target_time - offset_adjusted_time(),
            )

    def should_do_delayed_trigger(self) -> bool:
        # Don't trigger if the previous frame was before the target time.
        # This gives the regular touch handling a chance to trigger on time the first time we pass the target time.
        if offset_adjusted_time() - delta_time() <= self.target_time and time() < self.input_interval.end:
            return False

        # Don't trigger if we never had a touch recorded.
        if self.best_touch_time == DEFAULT_BEST_TOUCH_TIME:
            return False

        # Give until the end of the perfect window to give a right-way touch if we've only had wrong-way touches.
        # After that, wrong-way has no impact anyway.
        if (
            not self.best_touch_matches_direction
            and offset_adjusted_time() < self.target_time + self.judgment_window.perfect.end
        ):
            return False

        # If a new input could improve the judgment...
        if offset_adjusted_time() < self.target_time + (self.target_time - self.best_touch_time):
            # If we're still in the perfect window, wait for it to end.
            if offset_adjusted_time() < self.target_time + self.judgment_window.perfect.end:
                return False
            # Otherwise, see if there's any ongoing touches in the hitbox.
            for touch in input_manager.processed_touches():
                if not touch.ended and self.hitbox.bounds.contains_point(touch.position):
                    return False
            # If we're past the perfect window, and there are no ongoing touches in the hitbox, we can trigger to
            # avoid delaying the trigger by too long.
        return True

    def terminate(self):
        if self.should_play_hit_effects:
            # We do this here for parallelism, and to reduce compilation time.
            render_lane, render_size = self.visual_extents
            play_note_hit_effects(
                self.kind,
                self.effect_kind,
                render_lane,
                render_size,
                self.direction,
                self.result.judgment,
                y_offset=self.visual_y_offset,
                pivot_lane=self.visual_pivot_lane,
                half_offset=self.visual_half_offset,
                single_line=self.visual_single_line,
                lane_particles=self.visual_lane_particles,
                transform=self.visual_stage_transform().transform(),
            )
        if self.is_scored:
            self.result.haptic = get_note_haptic_feedback(self.kind, self.result.judgment)
        self.end_time = offset_adjusted_time()
        self.played_hit_effects = self.should_play_hit_effects

    def handle_tap_input(self):
        if time() > self.input_interval.end:
            return
        if self.captured_touch_id == 0:
            return
        touch = next(tap for tap in input_manager.processed_touches() if tap.id == self.captured_touch_id)
        self.judge(touch.start_time)

    def handle_release_input(self):
        if time() > self.input_interval.end:
            return
        if self.captured_touch_id == 0:
            return
        touch = next(tap for tap in input_manager.processed_touches() if tap.id == self.captured_touch_id)
        self.judge(touch.time)

    def handle_flick_input(self):
        if time() > self.input_interval.end:
            return
        if self.captured_touch_id == 0:
            return

        # Another touch is allowed to flick the note as long as it started after the start of the input interval,
        # so we don't care which touch matched the tap id, just that the tap id is set.

        for touch in input_manager.processed_touches():
            if not self.check_touch_touch_is_eligible_for_flick(touch):
                continue
            if not self.check_direction_matches(touch.angle):
                continue
            input_manager.disallow_empty(touch)
            self.judge(touch.time)
            return
        for touch in input_manager.processed_touches():
            if not self.check_touch_touch_is_eligible_for_flick(touch):
                continue
            input_manager.disallow_empty(touch)
            self.judge_wrong_way(touch.time)
            return

    def handle_trace_input(self):
        if time() > self.input_interval.end:
            return
        if self.should_do_delayed_trigger():
            return
        has_touch = False
        for touch in input_manager.processed_touches():
            if not self.check_touch_is_eligible_for_trace(touch):
                continue
            input_manager.disallow_empty(touch)
            has_touch = True
            # Keep going so we disallow empty on all touches that are in the hitbox.
        if not has_touch:
            return
        if offset_adjusted_time() >= self.target_time:
            if offset_adjusted_time() - delta_time() <= self.target_time <= offset_adjusted_time():
                self.complete()
            else:
                self.judge(offset_adjusted_time())
        else:
            self.best_touch_time = offset_adjusted_time()
            self.best_touch_matches_direction = True

    def handle_trace_flick_input(self):
        if time() > self.input_interval.end:
            return
        if self.should_do_delayed_trigger():
            return
        has_touch = False
        has_correct_direction_touch = False
        for touch in input_manager.processed_touches():
            if not self.check_touch_is_eligible_for_trace(touch):
                continue
            input_manager.disallow_empty(touch)
            if not self.check_touch_is_eligible_for_trace_flick(touch):
                continue
            has_touch = True
            if self.check_direction_matches(touch.angle):
                has_correct_direction_touch = True
        if not has_touch:
            return
        if offset_adjusted_time() >= self.target_time:
            if has_correct_direction_touch:
                if offset_adjusted_time() - delta_time() <= self.target_time <= offset_adjusted_time():
                    self.complete()
                else:
                    self.judge(offset_adjusted_time())
                return
            elif offset_adjusted_time() > self.target_time + self.judgment_window.perfect.end:
                self.judge_wrong_way(offset_adjusted_time())
                return
        # Either pre-target, or post-target within perfect window with wrong direction
        current_abs_error = abs(self.best_touch_time - self.target_time)
        if not self.best_touch_matches_direction:
            current_abs_error = max(current_abs_error, self.judgment_window.perfect.end)
        incoming_abs_error = abs(offset_adjusted_time() - self.target_time)
        if not has_correct_direction_touch:
            incoming_abs_error = max(incoming_abs_error, self.judgment_window.perfect.end)
        if incoming_abs_error < current_abs_error:
            self.best_touch_time = offset_adjusted_time()
            self.best_touch_matches_direction = has_correct_direction_touch

    def handle_tick_input(self):
        has_touch = False
        for touch in input_manager.processed_touches():
            if not self.hitbox.bounds.contains_point(touch.position):
                continue
            input_manager.disallow_empty(touch)
            has_touch = True
        if has_touch:
            if offset_adjusted_time() >= self.target_time:
                self.complete()
            else:
                # Always judge as perfect accuracy for ticks if touched.
                self.best_touch_time = self.target_time
                self.best_touch_matches_direction = True

    def handle_damage_input(self):
        has_touch = False
        for touch in input_manager.processed_touches():
            if not self.hitbox.bounds.contains_point(touch.position):
                continue
            input_manager.disallow_empty(touch)
            has_touch = True
        if has_touch:
            self.fail_damage()
        else:
            self.complete_damage()

    def handle_damage_tick_input(self):
        if time() > self.input_interval.end:
            return
        has_touch = False
        for touch in input_manager.processed_touches():
            if not self.hitbox.bounds.contains_point(touch.position):
                continue
            input_manager.disallow_empty(touch)
            has_touch = True
        if has_touch:
            self.fail_damage()

    def damage_tick_input_bounds(self, t: float) -> Quad:
        connection_head_ref = +EntityRef[BaseNote]
        if self.is_attached:
            connection_head_ref @= self.attach_head_ref
        else:
            connection_head_ref @= self.ref()
        while connection_head_ref.get().prev_ref.index > 0 and connection_head_ref.get().target_time > t:
            connection_head_ref.index = connection_head_ref.get().prev_ref.index
        if connection_head_ref.get().next_ref.index <= 0 and connection_head_ref.get().prev_ref.index > 0:
            connection_head_ref.index = connection_head_ref.get().prev_ref.index
        connection_head = connection_head_ref.get()
        result = +Quad
        if connection_head.next_ref.index > 0:
            result @= compute_slide_input_bounds(
                connection_head.connector_ease,
                connection_head,
                connection_head.next_ref.get(),
                t,
                get_leniency(self.kind),
            )
        else:
            result @= self.hitbox.bounds
        return result

    def handle_late_miss(self):
        kind = self.kind
        match kind:
            case NoteKind.NORM_TICK | NoteKind.CRIT_TICK | NoteKind.HIDE_TICK:
                self.fail_late(0.125)
            case NoteKind.DAMAGE | NoteKind.HIDE_DAMAGE_TICK:
                self.complete_damage()
            case (
                NoteKind.NORM_TAP
                | NoteKind.CRIT_TAP
                | NoteKind.NORM_FLICK
                | NoteKind.CRIT_FLICK
                | NoteKind.NORM_TRACE
                | NoteKind.CRIT_TRACE
                | NoteKind.NORM_TRACE_FLICK
                | NoteKind.CRIT_TRACE_FLICK
                | NoteKind.NORM_RELEASE
                | NoteKind.CRIT_RELEASE
                | NoteKind.NORM_HEAD_TAP
                | NoteKind.CRIT_HEAD_TAP
                | NoteKind.NORM_HEAD_FLICK
                | NoteKind.CRIT_HEAD_FLICK
                | NoteKind.NORM_HEAD_TRACE
                | NoteKind.CRIT_HEAD_TRACE
                | NoteKind.NORM_HEAD_TRACE_FLICK
                | NoteKind.CRIT_HEAD_TRACE_FLICK
                | NoteKind.NORM_HEAD_RELEASE
                | NoteKind.CRIT_HEAD_RELEASE
                | NoteKind.NORM_TAIL_TAP
                | NoteKind.CRIT_TAIL_TAP
                | NoteKind.NORM_TAIL_FLICK
                | NoteKind.CRIT_TAIL_FLICK
                | NoteKind.NORM_TAIL_TRACE
                | NoteKind.CRIT_TAIL_TRACE
                | NoteKind.NORM_TAIL_TRACE_FLICK
                | NoteKind.CRIT_TAIL_TRACE_FLICK
                | NoteKind.NORM_TAIL_RELEASE
                | NoteKind.CRIT_TAIL_RELEASE
            ):
                self.fail_late()
            case NoteKind.ANCHOR:
                pass
            case _:
                assert_never(kind)

    def check_touch_touch_is_eligible_for_flick(self, touch: Touch) -> bool:
        return (
            touch.start_time >= self.captured_touch_time
            and touch.speed >= Layout.flick_speed_threshold
            and (
                self.hitbox.bounds.contains_point(touch.position)
                or self.hitbox.bounds.contains_point(touch.prev_position)
            )
        )

    def check_touch_is_eligible_for_trace(self, touch: Touch) -> bool:
        # Note that this does not check the time, since time may not be updated if the touch is stationary.
        return self.hitbox.bounds.contains_point(touch.position)

    def check_touch_is_eligible_for_trace_flick(self, touch: Touch) -> bool:
        return (
            touch.time >= self.unadjusted_input_interval.start
            and touch.speed >= Layout.flick_speed_threshold
            and (
                self.hitbox.bounds.contains_point(touch.position)
                or self.hitbox.bounds.contains_point(touch.prev_position)
            )
        )

    def check_direction_matches(self, angle: float) -> bool:
        leniency = pi / 2
        match self.direction:
            case FlickDirection.UP_OMNI | FlickDirection.DOWN_OMNI:
                return True
            case FlickDirection.UP_LEFT:
                target_angle = pi / 2 + 1
            case FlickDirection.UP_RIGHT:
                target_angle = pi / 2 - 1
            case FlickDirection.DOWN_LEFT:
                target_angle = -pi / 2 - 1
            case FlickDirection.DOWN_RIGHT:
                target_angle = -pi / 2 + 1
            case _:
                assert_never(self.direction)
        angle_diff = abs((angle + DynamicLayout.rotate + self.visual_stage_rotate - target_angle + pi) % (2 * pi) - pi)
        return angle_diff <= leniency

    def judge(self, actual_time: float):
        judgment = self.judgment_window.judge(actual_time, self.target_time)
        error = self.judgment_window.good.clamp(actual_time - self.target_time)
        self.result.judgment = judgment
        self.result.accuracy = error
        if self.result.bucket.id != -1:
            self.result.bucket_value = error * WINDOW_SCALE
        self.despawn = True
        self.should_play_hit_effects = judgment != Judgment.MISS
        self.post_judge()

    def judge_wrong_way(self, actual_time: float):
        judgment = self.judgment_window.judge(actual_time, self.target_time)
        if judgment == Judgment.PERFECT:
            judgment = Judgment.GREAT
        error = self.judgment_window.good.clamp(actual_time - self.target_time)
        self.result.judgment = judgment
        if error in self.judgment_window.perfect:
            self.result.accuracy = self.judgment_window.perfect.end
        else:
            self.result.accuracy = error
        if self.result.bucket.id != -1:
            self.result.bucket_value = error * WINDOW_SCALE
        self.despawn = True
        self.should_play_hit_effects = judgment != Judgment.MISS
        self.post_judge()

    def complete(self):
        self.result.judgment = Judgment.PERFECT
        self.result.accuracy = 0
        if self.result.bucket.id != -1:
            self.result.bucket_value = 0
        self.despawn = True
        self.should_play_hit_effects = True
        self.post_judge()

    def complete_damage(self):
        self.result.judgment = Judgment.PERFECT
        self.result.accuracy = 0
        if self.result.bucket.id != -1:
            self.result.bucket_value = 0
        self.despawn = True
        self.should_play_hit_effects = True
        # Ideally we'd call post_judge here, but this is called in update_parallel. Not a big deal.

    def fail_late(self, accuracy: float | None = None):
        if accuracy is None:
            accuracy = self.judgment_window.good.end
        self.result.judgment = Judgment.MISS
        self.result.accuracy = accuracy
        self.result.bucket = Bucket(-1)
        self.despawn = True

    def fail_damage(self):
        self.result.judgment = Judgment.MISS
        self.result.accuracy = 0.125
        self.despawn = True
        self.should_play_hit_effects = True
        self.post_judge()

    def post_judge(self):
        if self.should_play_hit_effects:
            PlayLevelMemory.last_note_sfx_time = time()

    @property
    def progress(self) -> float:
        if self.is_attached:
            attach_head = self.attach_head_ref.get()
            attach_tail = self.attach_tail_ref.get()
            head_progress = (
                progress_to(
                    attach_head.target_scaled_time,
                    group_scaled_time(attach_head.timescale_group),
                    group_force_note_speed(attach_head.timescale_group),
                )
                if time() < attach_head.target_time
                else 1.0
            )
            tail_progress = progress_to(
                attach_tail.target_scaled_time,
                group_scaled_time(attach_tail.timescale_group),
                group_force_note_speed(attach_tail.timescale_group),
            )
            head_frac = (
                0.0
                if time() < attach_head.target_time
                else get_attach_frac(attach_head.target_time, attach_tail.target_time, time())
            )
            tail_frac = 1.0
            frac = get_attach_frac(attach_head.target_time, attach_tail.target_time, self.target_time)
            return lerp(head_progress, tail_progress, get_attach_frac(head_frac, tail_frac, frac))
        else:
            return progress_to(
                self.target_scaled_time,
                group_scaled_time(self.timescale_group),
                group_force_note_speed(self.timescale_group),
            )

    @property
    def visual_progress(self) -> float:
        return self.progress - self.visual_y_offset

    def _basic_visual_lane_at(self, t: float) -> float:
        if self.stage_ref.index <= 0:
            return self.lane
        return get_stage_props(self.stage_ref.get(), t).pivot_lane + self.rel_lane

    def visual_lane_at(self, t: float) -> float:
        if self.is_attached:
            head = self.attach_head_ref.get()
            tail = self.attach_tail_ref.get()
            return lerp(head._basic_visual_lane_at(t), tail._basic_visual_lane_at(t), self.attach_eased_frac)
        return self._basic_visual_lane_at(t)

    @property
    def visual_lane(self) -> float:
        return self.visual_lane_at(time())

    @property
    def _basic_visual_mask(self) -> VisualMask:
        result = +VisualMask
        if self.stage_ref.index > 0:
            props = self.stage_ref.get().props
            result.left = props.lane - props.width
            result.right = props.lane + props.width
            result.enabled = props.mask_notes
            if result.enabled:
                result.stage_index = self.stage_ref.index
        return result

    def _basic_visual_mask_at(self, t: float, left_limit: bool = False) -> VisualMask:
        result = +VisualMask
        if self.stage_ref.index > 0:
            props = get_stage_props(self.stage_ref.get(), t, left_limit=left_limit)
            result.left = props.lane - props.width
            result.right = props.lane + props.width
            result.enabled = props.mask_notes
            if result.enabled:
                result.stage_index = self.stage_ref.index
        return result

    @property
    def visual_mask(self) -> VisualMask:
        result = +VisualMask
        if not self.is_attached:
            result @= self._basic_visual_mask
            return result

        head_mask = self.attach_head_ref.get()._basic_visual_mask
        tail_mask = self.attach_tail_ref.get()._basic_visual_mask
        result @= interpolate_visual_masks(head_mask, tail_mask, self.attach_eased_frac)
        return result

    def visual_mask_at(self, t: float, left_limit: bool = False) -> VisualMask:
        result = +VisualMask
        if not self.is_attached:
            result @= self._basic_visual_mask_at(t, left_limit=left_limit)
            return result

        head_mask = self.attach_head_ref.get()._basic_visual_mask_at(t, left_limit=left_limit)
        tail_mask = self.attach_tail_ref.get()._basic_visual_mask_at(t, left_limit=left_limit)
        result @= interpolate_visual_masks(head_mask, tail_mask, self.attach_eased_frac)
        return result

    def visual_extents_at(self, t: float, left_limit: bool = False) -> tuple[float, float]:
        render_lane = self.visual_lane_at(t)
        mask = self.visual_mask_at(t, left_limit=left_limit)
        return masked_note_extents_by_limits(render_lane, self.size, mask.left, mask.right, mask.enabled)

    @property
    def visual_extents(self) -> tuple[float, float]:
        render_lane = self.visual_lane
        mask = self.visual_mask
        return masked_note_extents_by_limits(render_lane, self.size, mask.left, mask.right, mask.enabled)

    @property
    def _basic_visual_y_offset(self) -> float:
        if self.stage_ref.index > 0:
            return self.stage_ref.get().props.y_offset
        else:
            return 0.0

    @property
    def visual_y_offset(self) -> float:
        if self.is_attached:
            head = self.attach_head_ref.get()
            tail = self.attach_tail_ref.get()
            return lerp(
                head._basic_visual_y_offset,
                tail._basic_visual_y_offset,
                get_attach_frac(head.target_time, tail.target_time, self.target_time),
            )
        return self._basic_visual_y_offset

    @property
    def _basic_visual_note_alpha(self) -> float:
        if self.stage_ref.index > 0:
            return self.stage_ref.get().props.note_alpha
        else:
            return 1.0

    @property
    def visual_note_alpha(self) -> float:
        if self.is_attached:
            head = self.attach_head_ref.get()
            tail = self.attach_tail_ref.get()
            return lerp(
                head._basic_visual_note_alpha,
                tail._basic_visual_note_alpha,
                get_attach_frac(head.target_time, tail.target_time, self.target_time),
            )
        return self._basic_visual_note_alpha

    def _basic_y_offset_at(self, t: float, left_limit: bool = False) -> float:
        if self.stage_ref.index <= 0:
            return 0.0
        return get_stage_props(self.stage_ref.get(), t, left_limit=left_limit).y_offset

    def y_offset_at(self, t: float, left_limit: bool = False) -> float:
        if self.is_attached:
            head = self.attach_head_ref.get()
            tail = self.attach_tail_ref.get()
            return lerp(
                head._basic_y_offset_at(t, left_limit=left_limit),
                tail._basic_y_offset_at(t, left_limit=left_limit),
                get_attach_frac(head.target_time, tail.target_time, self.target_time),
            )
        return self._basic_y_offset_at(t, left_limit=left_limit)

    def _basic_visual_stage_transform(self) -> StageTransform:
        result = +StageTransform
        if self.stage_ref.index > 0:
            result @= self.stage_ref.get().props.stage_transform()
        else:
            result @= identity_stage_transform()
        return result

    def visual_stage_transform(self) -> StageTransform:
        result = +StageTransform
        if self.is_attached:
            head = self.attach_head_ref.get()
            tail = self.attach_tail_ref.get()
            result @= blend_stage_transform(
                head._basic_visual_stage_transform(),
                tail._basic_visual_stage_transform(),
                self.attach_eased_frac,
            )
        else:
            result @= self._basic_visual_stage_transform()
        return result

    def _basic_has_stage_transform(self) -> bool:
        return self.stage_ref.index > 0 and self.stage_ref.get().props.has_transform()

    def has_stage_transform(self) -> bool:
        if self.is_attached:
            return (
                self.attach_head_ref.get()._basic_has_stage_transform()
                or self.attach_tail_ref.get()._basic_has_stage_transform()
            )
        return self._basic_has_stage_transform()

    @property
    def _basic_visual_stage_rotate(self) -> float:
        if self.stage_ref.index > 0:
            return self.stage_ref.get().props.rotate
        return 0.0

    @property
    def visual_stage_rotate(self) -> float:
        if self.is_attached:
            head = self.attach_head_ref.get()
            tail = self.attach_tail_ref.get()
            return lerp(
                head._basic_visual_stage_rotate,
                tail._basic_visual_stage_rotate,
                self.attach_eased_frac,
            )
        return self._basic_visual_stage_rotate

    def _basic_stage_transform_at(self, t: float, left_limit: bool = False) -> StageTransform:
        result = +StageTransform
        if self.stage_ref.index > 0:
            props = get_stage_props(self.stage_ref.get(), t, left_limit=left_limit)
            result @= compute_stage_transform(
                camera_layout_transform_at_time(t, left_limit=left_limit),
                props.rotate,
                props.x_lane_translate,
                props.y_lane_translate,
                props.lane,
                props.center_weight,
            )
        else:
            result @= identity_stage_transform()
        return result

    def stage_transform_at(self, t: float, left_limit: bool = False) -> StageTransform:
        result = +StageTransform
        if self.is_attached:
            head = self.attach_head_ref.get()
            tail = self.attach_tail_ref.get()
            result @= blend_stage_transform(
                head._basic_stage_transform_at(t, left_limit=left_limit),
                tail._basic_stage_transform_at(t, left_limit=left_limit),
                get_attach_eased_frac(self.connector_ease, head.target_time, tail.target_time, self.target_time),
            )
        else:
            result @= self._basic_stage_transform_at(t, left_limit=left_limit)
        return result

    @property
    def visual_pivot_lane(self) -> float:
        if self.stage_ref.index > 0:
            return self.stage_ref.get().props.pivot_lane
        else:
            return 0.0

    @property
    def visual_half_offset(self) -> bool:
        if self.stage_ref.index > 0:
            division = self.stage_ref.get().props.division.start
            return division.parity == DivisionParity.ODD and division.size % 2 == 1
        else:
            return False

    @property
    def visual_single_line(self) -> bool:
        if self.stage_ref.index > 0:
            return resolve_judge_line_style(self.stage_ref.get().props.judge_line_style) == JudgeLineStyle.SINGLE_LINE
        else:
            return False

    @property
    def visual_lane_particles(self) -> bool:
        if self.stage_ref.index > 0:
            return self.stage_ref.get().props.full_width <= 0.0
        else:
            return True

    @property
    def head_ease_frac(self) -> float:
        if self.is_attached:
            return get_attach_frac(
                self.attach_head_ref.get().target_time, self.attach_tail_ref.get().target_time, self.target_time
            )
        else:
            return 0.0

    @property
    def tail_ease_frac(self) -> float:
        if self.is_attached:
            return get_attach_frac(
                self.attach_head_ref.get().target_time, self.attach_tail_ref.get().target_time, self.target_time
            )
        else:
            return 1.0

    @property
    def effective_attach_head(self) -> BaseNote:
        ref = +EntityRef[BaseNote]
        if self.is_attached:
            ref @= self.attach_head_ref
        else:
            ref @= self.ref()
        return ref.get()

    @property
    def effective_attach_tail(self) -> BaseNote:
        ref = +EntityRef[BaseNote]
        if self.is_attached:
            ref @= self.attach_tail_ref
        else:
            ref @= self.ref()
        return ref.get()


def compute_slide_input_bounds(ease_type: EaseType, head: BaseNote, tail: BaseNote, t: float, leniency: float) -> Quad:
    input_frac, input_interp_frac = get_connector_fractions(
        ease_type,
        head.target_time,
        head.head_ease_frac,
        tail.target_time,
        tail.tail_ease_frac,
        t,
    )
    input_lane = lerp(head.visual_lane_at(t), tail.visual_lane_at(t), input_interp_frac)
    input_size = lerp(head.size, tail.size, input_interp_frac)
    input_mask = interpolate_visual_masks(
        head.visual_mask_at(t, left_limit=True),
        tail.visual_mask_at(t, left_limit=True),
        input_interp_frac,
    )
    input_lane, input_size = masked_note_extents_by_limits(
        input_lane,
        input_size,
        input_mask.left,
        input_mask.right,
        input_mask.enabled,
    )
    input_y_offset = lerp(
        head.y_offset_at(t, left_limit=True),
        tail.y_offset_at(t, left_limit=True),
        input_frac,
    )
    # Input arrives one input offset late, so the whole view state (stage transforms and layout)
    # is queried at t, looking back by the offset rather than using the current frame. Use the
    # left limit consistently with fixed-note judgment geometry at an event on the same timestamp.
    input_transform = blend_stage_transform(
        head.stage_transform_at(t, left_limit=True),
        tail.stage_transform_at(t, left_limit=True),
        input_interp_frac,
    )
    return compute_hitbox(
        camera_layout_transform_at_time(t, left_limit=True),
        input_lane,
        input_size,
        leniency,
        input_y_offset,
        stage_transform=input_transform.transform(),
    ).bounds


@level_memory
class NoteMemory:
    active_tap_input_notes: VarArray[EntityRef[BaseNote], Dim[256]]
    active_release_input_notes: VarArray[EntityRef[BaseNote], Dim[256]]


NormalTapNote = BaseNote.derive(archetype_names.NORMAL_TAP_NOTE, is_scored=True, key=NoteKind.NORM_TAP)
CriticalTapNote = BaseNote.derive(archetype_names.CRITICAL_TAP_NOTE, is_scored=True, key=NoteKind.CRIT_TAP)
NormalFlickNote = BaseNote.derive(archetype_names.NORMAL_FLICK_NOTE, is_scored=True, key=NoteKind.NORM_FLICK)
CriticalFlickNote = BaseNote.derive(archetype_names.CRITICAL_FLICK_NOTE, is_scored=True, key=NoteKind.CRIT_FLICK)
NormalTraceNote = BaseNote.derive(archetype_names.NORMAL_TRACE_NOTE, is_scored=True, key=NoteKind.NORM_TRACE)
CriticalTraceNote = BaseNote.derive(archetype_names.CRITICAL_TRACE_NOTE, is_scored=True, key=NoteKind.CRIT_TRACE)
NormalTraceFlickNote = BaseNote.derive(
    archetype_names.NORMAL_TRACE_FLICK_NOTE, is_scored=True, key=NoteKind.NORM_TRACE_FLICK
)
CriticalTraceFlickNote = BaseNote.derive(
    archetype_names.CRITICAL_TRACE_FLICK_NOTE, is_scored=True, key=NoteKind.CRIT_TRACE_FLICK
)
NormalReleaseNote = BaseNote.derive(archetype_names.NORMAL_RELEASE_NOTE, is_scored=True, key=NoteKind.NORM_RELEASE)
CriticalReleaseNote = BaseNote.derive(archetype_names.CRITICAL_RELEASE_NOTE, is_scored=True, key=NoteKind.CRIT_RELEASE)
NormalHeadTapNote = BaseNote.derive(archetype_names.NORMAL_HEAD_TAP_NOTE, is_scored=True, key=NoteKind.NORM_HEAD_TAP)
CriticalHeadTapNote = BaseNote.derive(
    archetype_names.CRITICAL_HEAD_TAP_NOTE, is_scored=True, key=NoteKind.CRIT_HEAD_TAP
)
NormalHeadFlickNote = BaseNote.derive(
    archetype_names.NORMAL_HEAD_FLICK_NOTE, is_scored=True, key=NoteKind.NORM_HEAD_FLICK
)
CriticalHeadFlickNote = BaseNote.derive(
    archetype_names.CRITICAL_HEAD_FLICK_NOTE, is_scored=True, key=NoteKind.CRIT_HEAD_FLICK
)
NormalHeadTraceNote = BaseNote.derive(
    archetype_names.NORMAL_HEAD_TRACE_NOTE, is_scored=True, key=NoteKind.NORM_HEAD_TRACE
)
CriticalHeadTraceNote = BaseNote.derive(
    archetype_names.CRITICAL_HEAD_TRACE_NOTE, is_scored=True, key=NoteKind.CRIT_HEAD_TRACE
)
NormalHeadTraceFlickNote = BaseNote.derive(
    archetype_names.NORMAL_HEAD_TRACE_FLICK_NOTE, is_scored=True, key=NoteKind.NORM_HEAD_TRACE_FLICK
)
CriticalHeadTraceFlickNote = BaseNote.derive(
    archetype_names.CRITICAL_HEAD_TRACE_FLICK_NOTE, is_scored=True, key=NoteKind.CRIT_HEAD_TRACE_FLICK
)
NormalHeadReleaseNote = BaseNote.derive(
    archetype_names.NORMAL_HEAD_RELEASE_NOTE, is_scored=True, key=NoteKind.NORM_HEAD_RELEASE
)
CriticalHeadReleaseNote = BaseNote.derive(
    archetype_names.CRITICAL_HEAD_RELEASE_NOTE, is_scored=True, key=NoteKind.CRIT_HEAD_RELEASE
)
NormalTailTapNote = BaseNote.derive(archetype_names.NORMAL_TAIL_TAP_NOTE, is_scored=True, key=NoteKind.NORM_TAIL_TAP)
CriticalTailTapNote = BaseNote.derive(
    archetype_names.CRITICAL_TAIL_TAP_NOTE, is_scored=True, key=NoteKind.CRIT_TAIL_TAP
)
NormalTailFlickNote = BaseNote.derive(
    archetype_names.NORMAL_TAIL_FLICK_NOTE, is_scored=True, key=NoteKind.NORM_TAIL_FLICK
)
CriticalTailFlickNote = BaseNote.derive(
    archetype_names.CRITICAL_TAIL_FLICK_NOTE, is_scored=True, key=NoteKind.CRIT_TAIL_FLICK
)
NormalTailTraceNote = BaseNote.derive(
    archetype_names.NORMAL_TAIL_TRACE_NOTE, is_scored=True, key=NoteKind.NORM_TAIL_TRACE
)
CriticalTailTraceNote = BaseNote.derive(
    archetype_names.CRITICAL_TAIL_TRACE_NOTE, is_scored=True, key=NoteKind.CRIT_TAIL_TRACE
)
NormalTailTraceFlickNote = BaseNote.derive(
    archetype_names.NORMAL_TAIL_TRACE_FLICK_NOTE, is_scored=True, key=NoteKind.NORM_TAIL_TRACE_FLICK
)
CriticalTailTraceFlickNote = BaseNote.derive(
    archetype_names.CRITICAL_TAIL_TRACE_FLICK_NOTE, is_scored=True, key=NoteKind.CRIT_TAIL_TRACE_FLICK
)
NormalTailReleaseNote = BaseNote.derive(
    archetype_names.NORMAL_TAIL_RELEASE_NOTE, is_scored=True, key=NoteKind.NORM_TAIL_RELEASE
)
CriticalTailReleaseNote = BaseNote.derive(
    archetype_names.CRITICAL_TAIL_RELEASE_NOTE, is_scored=True, key=NoteKind.CRIT_TAIL_RELEASE
)
NormalTickNote = BaseNote.derive(archetype_names.NORMAL_TICK_NOTE, is_scored=True, key=NoteKind.NORM_TICK)
CriticalTickNote = BaseNote.derive(archetype_names.CRITICAL_TICK_NOTE, is_scored=True, key=NoteKind.CRIT_TICK)
DamageNote = BaseNote.derive(archetype_names.DAMAGE_NOTE, is_scored=True, key=NoteKind.DAMAGE)
AnchorNote = BaseNote.derive(archetype_names.ANCHOR_NOTE, is_scored=False, key=NoteKind.ANCHOR)
TransientHiddenTickNote = BaseNote.derive(
    archetype_names.TRANSIENT_HIDDEN_TICK_NOTE, is_scored=True, key=NoteKind.HIDE_TICK
)
TransientHiddenDamageTickNote = BaseNote.derive(
    archetype_names.TRANSIENT_HIDDEN_DAMAGE_TICK_NOTE, is_scored=True, key=NoteKind.HIDE_DAMAGE_TICK
)
FakeNormalTapNote = BaseNote.derive(archetype_names.FAKE_NORMAL_TAP_NOTE, is_scored=False, key=NoteKind.NORM_TAP)
FakeCriticalTapNote = BaseNote.derive(archetype_names.FAKE_CRITICAL_TAP_NOTE, is_scored=False, key=NoteKind.CRIT_TAP)
FakeNormalFlickNote = BaseNote.derive(archetype_names.FAKE_NORMAL_FLICK_NOTE, is_scored=False, key=NoteKind.NORM_FLICK)
FakeCriticalFlickNote = BaseNote.derive(
    archetype_names.FAKE_CRITICAL_FLICK_NOTE, is_scored=False, key=NoteKind.CRIT_FLICK
)
FakeNormalTraceNote = BaseNote.derive(archetype_names.FAKE_NORMAL_TRACE_NOTE, is_scored=False, key=NoteKind.NORM_TRACE)
FakeCriticalTraceNote = BaseNote.derive(
    archetype_names.FAKE_CRITICAL_TRACE_NOTE, is_scored=False, key=NoteKind.CRIT_TRACE
)
FakeNormalTraceFlickNote = BaseNote.derive(
    archetype_names.FAKE_NORMAL_TRACE_FLICK_NOTE, is_scored=False, key=NoteKind.NORM_TRACE_FLICK
)
FakeCriticalTraceFlickNote = BaseNote.derive(
    "FakeCriticalTraceFlickNote", is_scored=False, key=NoteKind.CRIT_TRACE_FLICK
)
FakeNormalReleaseNote = BaseNote.derive(
    archetype_names.FAKE_NORMAL_RELEASE_NOTE, is_scored=False, key=NoteKind.NORM_RELEASE
)
FakeCriticalReleaseNote = BaseNote.derive(
    archetype_names.FAKE_CRITICAL_RELEASE_NOTE, is_scored=False, key=NoteKind.CRIT_RELEASE
)
FakeNormalHeadTapNote = BaseNote.derive(
    archetype_names.FAKE_NORMAL_HEAD_TAP_NOTE, is_scored=False, key=NoteKind.NORM_HEAD_TAP
)
FakeCriticalHeadTapNote = BaseNote.derive(
    archetype_names.FAKE_CRITICAL_HEAD_TAP_NOTE, is_scored=False, key=NoteKind.CRIT_HEAD_TAP
)
FakeNormalHeadFlickNote = BaseNote.derive(
    archetype_names.FAKE_NORMAL_HEAD_FLICK_NOTE, is_scored=False, key=NoteKind.NORM_HEAD_FLICK
)
FakeCriticalHeadFlickNote = BaseNote.derive(
    archetype_names.FAKE_CRITICAL_HEAD_FLICK_NOTE, is_scored=False, key=NoteKind.CRIT_HEAD_FLICK
)
FakeNormalHeadTraceNote = BaseNote.derive(
    archetype_names.FAKE_NORMAL_HEAD_TRACE_NOTE, is_scored=False, key=NoteKind.NORM_HEAD_TRACE
)
FakeCriticalHeadTraceNote = BaseNote.derive(
    archetype_names.FAKE_CRITICAL_HEAD_TRACE_NOTE, is_scored=False, key=NoteKind.CRIT_HEAD_TRACE
)
FakeNormalHeadTraceFlickNote = BaseNote.derive(
    archetype_names.FAKE_NORMAL_HEAD_TRACE_FLICK_NOTE, is_scored=False, key=NoteKind.NORM_HEAD_TRACE_FLICK
)
FakeCriticalHeadTraceFlickNote = BaseNote.derive(
    archetype_names.FAKE_CRITICAL_HEAD_TRACE_FLICK_NOTE, is_scored=False, key=NoteKind.CRIT_HEAD_TRACE_FLICK
)
FakeNormalHeadReleaseNote = BaseNote.derive(
    archetype_names.FAKE_NORMAL_HEAD_RELEASE_NOTE, is_scored=False, key=NoteKind.NORM_HEAD_RELEASE
)
FakeCriticalHeadReleaseNote = BaseNote.derive(
    archetype_names.FAKE_CRITICAL_HEAD_RELEASE_NOTE, is_scored=False, key=NoteKind.CRIT_HEAD_RELEASE
)
FakeNormalTailTapNote = BaseNote.derive(
    archetype_names.FAKE_NORMAL_TAIL_TAP_NOTE, is_scored=False, key=NoteKind.NORM_TAIL_TAP
)
FakeCriticalTailTapNote = BaseNote.derive(
    archetype_names.FAKE_CRITICAL_TAIL_TAP_NOTE, is_scored=False, key=NoteKind.CRIT_TAIL_TAP
)
FakeNormalTailFlickNote = BaseNote.derive(
    archetype_names.FAKE_NORMAL_TAIL_FLICK_NOTE, is_scored=False, key=NoteKind.NORM_TAIL_FLICK
)
FakeCriticalTailFlickNote = BaseNote.derive(
    archetype_names.FAKE_CRITICAL_TAIL_FLICK_NOTE, is_scored=False, key=NoteKind.CRIT_TAIL_FLICK
)
FakeNormalTailTraceNote = BaseNote.derive(
    archetype_names.FAKE_NORMAL_TAIL_TRACE_NOTE, is_scored=False, key=NoteKind.NORM_TAIL_TRACE
)
FakeCriticalTailTraceNote = BaseNote.derive(
    archetype_names.FAKE_CRITICAL_TAIL_TRACE_NOTE, is_scored=False, key=NoteKind.CRIT_TAIL_TRACE
)
FakeNormalTailTraceFlickNote = BaseNote.derive(
    archetype_names.FAKE_NORMAL_TAIL_TRACE_FLICK_NOTE, is_scored=False, key=NoteKind.NORM_TAIL_TRACE_FLICK
)
FakeCriticalTailTraceFlickNote = BaseNote.derive(
    archetype_names.FAKE_CRITICAL_TAIL_TRACE_FLICK_NOTE, is_scored=False, key=NoteKind.CRIT_TAIL_TRACE_FLICK
)
FakeNormalTailReleaseNote = BaseNote.derive(
    archetype_names.FAKE_NORMAL_TAIL_RELEASE_NOTE, is_scored=False, key=NoteKind.NORM_TAIL_RELEASE
)
FakeCriticalTailReleaseNote = BaseNote.derive(
    archetype_names.FAKE_CRITICAL_TAIL_RELEASE_NOTE, is_scored=False, key=NoteKind.CRIT_TAIL_RELEASE
)
FakeNormalTickNote = BaseNote.derive(archetype_names.FAKE_NORMAL_TICK_NOTE, is_scored=False, key=NoteKind.NORM_TICK)
FakeCriticalTickNote = BaseNote.derive(archetype_names.FAKE_CRITICAL_TICK_NOTE, is_scored=False, key=NoteKind.CRIT_TICK)
FakeDamageNote = BaseNote.derive(archetype_names.FAKE_DAMAGE_NOTE, is_scored=False, key=NoteKind.DAMAGE)
FakeAnchorNote = BaseNote.derive(archetype_names.FAKE_ANCHOR_NOTE, is_scored=False, key=NoteKind.ANCHOR)
FakeTransientHiddenTickNote = BaseNote.derive(
    archetype_names.FAKE_TRANSIENT_HIDDEN_TICK_NOTE, is_scored=False, key=NoteKind.HIDE_TICK
)
FakeTransientHiddenDamageTickNote = BaseNote.derive(
    archetype_names.FAKE_TRANSIENT_HIDDEN_DAMAGE_TICK_NOTE, is_scored=False, key=NoteKind.HIDE_DAMAGE_TICK
)


NOTE_ARCHETYPES = (
    NormalTapNote,
    CriticalTapNote,
    NormalFlickNote,
    CriticalFlickNote,
    NormalTraceNote,
    CriticalTraceNote,
    NormalTraceFlickNote,
    CriticalTraceFlickNote,
    NormalReleaseNote,
    CriticalReleaseNote,
    NormalHeadTapNote,
    CriticalHeadTapNote,
    NormalHeadFlickNote,
    CriticalHeadFlickNote,
    NormalHeadTraceNote,
    CriticalHeadTraceNote,
    NormalHeadTraceFlickNote,
    CriticalHeadTraceFlickNote,
    NormalHeadReleaseNote,
    CriticalHeadReleaseNote,
    NormalTailTapNote,
    CriticalTailTapNote,
    NormalTailFlickNote,
    CriticalTailFlickNote,
    NormalTailTraceNote,
    CriticalTailTraceNote,
    NormalTailTraceFlickNote,
    CriticalTailTraceFlickNote,
    NormalTailReleaseNote,
    CriticalTailReleaseNote,
    NormalTickNote,
    CriticalTickNote,
    DamageNote,
    AnchorNote,
    TransientHiddenTickNote,
    TransientHiddenDamageTickNote,
    FakeNormalTapNote,
    FakeCriticalTapNote,
    FakeNormalFlickNote,
    FakeCriticalFlickNote,
    FakeNormalTraceNote,
    FakeCriticalTraceNote,
    FakeNormalTraceFlickNote,
    FakeCriticalTraceFlickNote,
    FakeNormalReleaseNote,
    FakeCriticalReleaseNote,
    FakeNormalHeadTapNote,
    FakeCriticalHeadTapNote,
    FakeNormalHeadFlickNote,
    FakeCriticalHeadFlickNote,
    FakeNormalHeadTraceNote,
    FakeCriticalHeadTraceNote,
    FakeNormalHeadTraceFlickNote,
    FakeCriticalHeadTraceFlickNote,
    FakeNormalHeadReleaseNote,
    FakeCriticalHeadReleaseNote,
    FakeNormalTailTapNote,
    FakeCriticalTailTapNote,
    FakeNormalTailFlickNote,
    FakeCriticalTailFlickNote,
    FakeNormalTailTraceNote,
    FakeCriticalTailTraceNote,
    FakeNormalTailTraceFlickNote,
    FakeCriticalTailTraceFlickNote,
    FakeNormalTailReleaseNote,
    FakeCriticalTailReleaseNote,
    FakeNormalTickNote,
    FakeCriticalTickNote,
    FakeDamageNote,
    FakeAnchorNote,
    FakeTransientHiddenTickNote,
    FakeTransientHiddenDamageTickNote,
)


def derive_note_archetypes[T: type[AnyArchetype]](base: T) -> tuple[T, ...]:
    """Helper function to derive all note archetypes from a given base archetype for used in watch and preview."""
    return tuple(base.derive(str(a.name), is_scored=a.is_scored, key=a.key) for a in NOTE_ARCHETYPES)
