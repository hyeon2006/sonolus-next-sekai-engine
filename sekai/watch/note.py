from __future__ import annotations

from typing import cast

from sonolus.script.archetype import (
    EntityRef,
    StandardImport,
    WatchArchetype,
    entity_data,
    entity_memory,
    imported,
    shared_memory,
)
from sonolus.script.bucket import Judgment
from sonolus.script.interval import lerp
from sonolus.script.quad import Quad
from sonolus.script.runtime import is_replay, is_skip, time
from sonolus.script.timing import beat_to_time

from sekai.debug import DISABLE_NOTES
from sekai.lib.buckets import SekaiWindow
from sekai.lib.connector import (
    ActiveConnectorInfo,
    ConnectorKind,
    ConnectorLayer,
    SegmentPresentation,
    get_connector_fractions,
)
from sekai.lib.ease import EaseType
from sekai.lib.layout import (
    FlickDirection,
    Hitbox,
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
    get_visual_spawn_time,
    hitbox_draw_alpha,
    hitbox_draw_start,
    is_head,
    map_note_kind,
    mirror_flick_direction,
    play_note_hit_effects,
    schedule_note_auto_sfx,
    schedule_note_particles,
    schedule_note_sfx,
    schedule_note_slot_effects,
)
from sekai.lib.options import Options
from sekai.lib.stage import (
    DivisionParity,
    JudgeLineStyle,
    VisualMask,
    get_stage_props,
    interpolate_visual_masks,
    masked_note_extents,
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
from sekai.play.note import derive_note_archetypes, get_note_window
from sekai.watch.custom_elements import spawn_custom
from sekai.watch.dynamic_stage import WatchDynamicStage

MIN_START_TIME = 0.0167  # Executes the terminate process with a guaranteed minimum duration.


class WatchBaseNote(WatchArchetype):
    beat: StandardImport.BEAT
    timescale_group: StandardImport.TIMESCALE_GROUP
    stage_ref: EntityRef[WatchDynamicStage] = imported(name="stage")
    lane: float = imported()
    size: float = imported()
    direction: FlickDirection = imported()
    active_head_ref: EntityRef[WatchBaseNote] = imported(name="activeHead")
    is_attached: bool = imported(name="isAttached")
    connector_ease: EaseType = imported(name="connectorEase")
    segment_kind: ConnectorKind = imported(name="segmentKind")
    segment_alpha: float = imported(name="segmentAlpha")
    segment_layer: ConnectorLayer = imported(name="segmentLayer")
    segment_through_judge_line: bool = imported(name="segmentThroughJudgeLine")
    segment_presentation: SegmentPresentation = imported(name="segmentPresentation")
    attach_head_ref: EntityRef[WatchBaseNote] = imported(name="attachHead")
    attach_tail_ref: EntityRef[WatchBaseNote] = imported(name="attachTail")
    next_ref: EntityRef[WatchBaseNote] = imported(name="next")
    prev_ref: EntityRef[WatchBaseNote] = imported(name="prev")
    effect_kind: NoteEffectKind = imported(name="effectKind")

    kind: NoteKind = entity_data()
    data_init_done: bool = entity_data()
    rel_lane: float = entity_data()
    target_time: float = entity_data()
    visual_start_time: float = entity_data()
    start_time: float = entity_data()
    target_scaled_time: CompositeTime = entity_data()
    target_y_offset: float = shared_memory()
    not_render: float = entity_memory()

    active_connector_info: ActiveConnectorInfo = shared_memory()

    init_chain_ref: EntityRef[WatchBaseNote] = shared_memory()

    hitbox: Hitbox = entity_memory()
    attach_eased_frac: float = shared_memory()

    end_time: float = imported()
    played_hit_effects: bool = imported()

    judgment: StandardImport.JUDGMENT = imported()
    accuracy: StandardImport.ACCURACY = imported()

    wrong_way_check: bool = imported()
    combo: int = shared_memory()
    count: int = shared_memory()
    ap: bool = shared_memory()
    score: float = shared_memory()
    percentage: float = shared_memory()
    note_raw_score: float = shared_memory()
    fever_hits: int = shared_memory()
    replay_life: float = shared_memory()

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

        if not self.is_attached:
            self.target_scaled_time = group_time_to_scaled_time(self.timescale_group, self.target_time)
            self.visual_start_time = get_visual_spawn_time(self.timescale_group, self.target_scaled_time)
            self.start_time = self.visual_start_time

        if self.stage_ref.index > 0:
            stage_props = get_stage_props(self.stage_ref.get(), self.target_time)
            self.rel_lane = self.lane
            self.lane += stage_props.pivot_lane
            self.target_y_offset = self._basic_y_offset_at(self.target_time, left_limit=True)

        if self.next_ref.index > 0:
            self.next_ref.get().prev_ref = self.ref()

    def preprocess(self):
        if DISABLE_NOTES:
            self.result.target_time = 1e8
            return
        # self.init_data()

        self.result.bucket = get_note_bucket(self.kind)

        if self.is_attached:
            attach_head = self.attach_head_ref.get()
            attach_tail = self.attach_tail_ref.get()
            # attach_head.init_data()
            # attach_tail.init_data()
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
            self.start_time = self.visual_start_time
            self.target_y_offset = lerp(
                attach_head._basic_y_offset_at(self.target_time, left_limit=True),
                attach_tail._basic_y_offset_at(self.target_time, left_limit=True),
                get_attach_frac(attach_head.target_time, attach_tail.target_time, self.target_time),
            )

        if self.is_scored:
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

        if is_replay():
            if self.played_hit_effects:
                if Options.auto_sfx:
                    schedule_note_auto_sfx(self.effect_kind, self.target_time)
                else:
                    schedule_note_sfx(self.effect_kind, self.judgment, self.end_time)
                self.schedule_slot_effects_at(self.end_time)
            self.result.bucket_value = self.accuracy * 1000
        else:
            self.judgment = Judgment.PERFECT
            if self.is_scored:
                schedule_note_sfx(self.effect_kind, Judgment.PERFECT, self.target_time)
                self.schedule_slot_effects_at(self.target_time)

        self.result.target_time = self.target_time

        self.extend_stage_windows(self.start_time - 1.0, max(self.target_time, self.despawn_time()) + 1.0)

        if self.is_scored:
            spawn_custom(
                self.next_ref,
                self.index,
            )

        if self.played_hit_effects or not is_replay():
            self.spawn_note_particles()
            self.get_min_start_time()

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

    def get_min_start_time(self):
        if self.calc_time - self.visual_start_time > MIN_START_TIME:
            return self.visual_start_time
        else:
            self.not_render = True
            return self.calc_time - MIN_START_TIME

    def spawn_note_particles(self):
        if not self.is_scored:
            return
        if not (Options.note_effect_enabled or Options.lane_effect_enabled):
            return
        if self.kind == NoteKind.HIDE_TICK:
            return
        t = self.calc_time
        pivot_lane = 0.0
        half_offset = False
        if self.stage_ref.index > 0:
            props = get_stage_props(self.stage_ref.get(), t)
            pivot_lane = props.pivot_lane
            division = props.division.start
            half_offset = division.parity == DivisionParity.ODD and division.size % 2 == 1
        schedule_note_particles(
            self.kind,
            self.effect_kind,
            self.visual_lane_at(t),
            self.size,
            t,
            self.direction,
            self.judgment,
            y_offset=self.y_offset_at(t),
            pivot_lane=pivot_lane,
            half_offset=half_offset,
            group_id=self.index,
            transform=self.stage_transform_at(t).transform(),
        )

    def schedule_slot_effects_at(self, t: float):
        transform = +StageTransform
        if self.stage_ref.index > 0:
            props = get_stage_props(self.stage_ref.get(), t)
            pivot_lane = props.pivot_lane
            y_offset = props.y_offset
            half_offset = props.division.start.parity == DivisionParity.ODD and props.division.start.size % 2 == 1
            single_line = resolve_judge_line_style(props.judge_line_style) == JudgeLineStyle.SINGLE_LINE
            if self.is_attached:
                visual_lane = self.visual_lane_at(t)
                transform @= self.stage_transform_at(t)
            else:
                visual_lane = props.pivot_lane + self.rel_lane
                transform @= compute_stage_transform(
                    camera_layout_transform_at_time(t),
                    props.rotate,
                    props.x_lane_translate,
                    props.y_lane_translate,
                    props.lane,
                    props.center_weight,
                )
            render_size = self.size
            if not self.is_attached:
                visual_lane, render_size = masked_note_extents(visual_lane, self.size, props)
        else:
            pivot_lane = 0.0
            y_offset = 0.0
            half_offset = False
            single_line = False
            visual_lane = self.visual_lane_at(t)
            render_size = self.size
            transform @= self.stage_transform_at(t)
        if self.is_attached:
            visual_lane, render_size = self.visual_extents_at(t)
        schedule_note_slot_effects(
            self.kind,
            visual_lane,
            render_size,
            t,
            self.direction,
            self.judgment,
            y_offset=y_offset,
            pivot_lane=pivot_lane,
            half_offset=half_offset,
            group_id=self.index,
            single_line=single_line,
            transform=transform.transform(),
        )

    def spawn_time(self) -> float:
        if DISABLE_NOTES or self.kind == NoteKind.ANCHOR:
            return 1e8
        return self.start_time

    def despawn_time(self) -> float:
        return self.calc_time

    @property
    def judgment_window(self) -> SekaiWindow:
        return get_note_window(self.kind, self.active_head_ref.index > 0 or self.is_attached)

    @property
    def calc_time(self) -> float:
        if is_replay() and self.is_scored:
            if self.end_time == 0 and self.accuracy == 0 and self.judgment == Judgment.MISS:
                # This is a note that's part of a partial replay that ended before this note was hit
                return self.target_time + self.accuracy
            return self.end_time
        else:
            return self.target_time

    def update_sequential(self):
        update_timescale_group(self.timescale_group)

    def update_parallel(self):
        self.draw_hitbox()
        if time() < self.visual_start_time:
            return
        if is_head(self.kind) and time() > self.target_time:
            return
        if group_hide_notes(self.timescale_group):
            return
        if Options.disable_fake_notes and not self.is_scored:
            return
        if self.not_render:
            return
        render_lane, render_size = self.visual_extents
        if render_size <= 0:
            return
        stage_transform = +StageTransform
        if self.has_stage_transform():
            stage_transform @= self.visual_stage_transform()
        else:
            stage_transform @= identity_stage_transform()
        draw_note(
            self.kind,
            render_lane,
            render_size,
            self.visual_progress,
            self.direction,
            self.target_time,
            transform=stage_transform.transform(),
            note_alpha=self.visual_note_alpha,
        )

    def draw_hitbox(self):
        if not Options.show_hitboxes or not self.is_scored:
            return
        if self.kind == NoteKind.HIDE_DAMAGE_TICK:
            self.draw_damage_tick_hitbox()
            return
        input_interval = get_note_window(self.kind, self.active_head_ref.index > 0).bad + self.target_time
        draw_start = hitbox_draw_start(self.kind, input_interval.start, self.target_time)
        if draw_start <= time() <= input_interval.end:
            draw_hitbox_overlay(
                self.hitbox,
                self.kind,
                hitbox_draw_alpha(self.kind, draw_start, self.target_time, time()),
                time_to_target=self.target_time - time(),
            )

    def draw_damage_tick_hitbox(self):
        # Damage segments have no connector-level hold hitbox, so this is the only hitbox drawn for them.
        if self.active_head_ref.index <= 0:
            return
        window_start_beat = max(damage_tick_input_start_beat(self.beat), self.active_head_ref.get().beat)
        window_start_time = beat_to_time(window_start_beat)
        draw_start = hitbox_draw_start(self.kind, window_start_time, self.target_time)
        if draw_start <= time() <= self.target_time:
            hitbox = +Hitbox
            hitbox.bounds @= self.damage_tick_input_bounds(time())
            draw_hitbox_overlay(
                hitbox,
                self.kind,
                hitbox_draw_alpha(self.kind, draw_start, self.target_time, time()),
                time_to_target=self.target_time - time(),
            )

    def damage_tick_input_bounds(self, t: float) -> Quad:
        connection_head_ref = +EntityRef[WatchBaseNote]
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

    def terminate(self):
        if is_skip():
            return
        if time() < self.despawn_time():
            return
        if (not is_replay() or self.played_hit_effects) and self.is_scored:
            render_lane, render_size = self.visual_extents
            play_note_hit_effects(
                self.kind,
                self.effect_kind,
                render_lane,
                render_size,
                self.direction,
                self.judgment,
                y_offset=self.visual_y_offset,
                pivot_lane=self.visual_pivot_lane,
                half_offset=self.visual_half_offset,
                lane_particles=self._stage_lane_particles_at(time()),
                transform=self.visual_stage_transform().transform(),
            )

    def _basic_visual_lane_at(self, t: float) -> float:
        if self.stage_ref.index <= 0:
            return self.lane
        stage = self.stage_ref.get()
        if t == time():
            return stage.props.pivot_lane + self.rel_lane
        return get_stage_props(stage, t).pivot_lane + self.rel_lane

    def visual_lane_at(self, t: float) -> float:
        if self.is_attached:
            head = self.attach_head_ref.get()
            tail = self.attach_tail_ref.get()
            return lerp(head._basic_visual_lane_at(t), tail._basic_visual_lane_at(t), self.attach_eased_frac)
        return self._basic_visual_lane_at(t)

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

    def _stage_pivot_lane_at(self, t: float) -> float:
        if self.stage_ref.index <= 0:
            return 0.0
        return get_stage_props(self.stage_ref.get(), t).pivot_lane

    def _stage_half_offset_at(self, t: float) -> bool:
        if self.stage_ref.index <= 0:
            return False
        division = get_stage_props(self.stage_ref.get(), t).division.start
        return division.parity == DivisionParity.ODD and division.size % 2 == 1

    def _stage_single_line_at(self, t: float) -> bool:
        if self.stage_ref.index <= 0:
            return False
        return (
            resolve_judge_line_style(get_stage_props(self.stage_ref.get(), t).judge_line_style)
            == JudgeLineStyle.SINGLE_LINE
        )

    def _stage_lane_particles_at(self, t: float) -> bool:
        if self.stage_ref.index <= 0:
            return True
        return get_stage_props(self.stage_ref.get(), t).full_width <= 0.0

    @property
    def visual_lane(self) -> float:
        return self.visual_lane_at(time())

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

    def visual_mask_at(self, t: float, left_limit: bool = False) -> VisualMask:
        result = +VisualMask
        if not self.is_attached:
            result @= self._basic_visual_mask_at(t, left_limit=left_limit)
            return result

        head_mask = self.attach_head_ref.get()._basic_visual_mask_at(t, left_limit=left_limit)
        tail_mask = self.attach_tail_ref.get()._basic_visual_mask_at(t, left_limit=left_limit)
        result @= interpolate_visual_masks(head_mask, tail_mask, self.attach_eased_frac)
        return result

    @property
    def visual_mask(self) -> VisualMask:
        return self.visual_mask_at(time())

    def visual_extents_at(self, t: float, left_limit: bool = False) -> tuple[float, float]:
        render_lane = self.visual_lane_at(t)
        mask = self.visual_mask_at(t, left_limit=left_limit)
        return masked_note_extents_by_limits(render_lane, self.size, mask.left, mask.right, mask.enabled)

    @property
    def visual_extents(self) -> tuple[float, float]:
        return self.visual_extents_at(time())

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
    def progress(self) -> float:
        if self.is_attached:
            current_time = time()
            attach_head = self.attach_head_ref.get()
            attach_tail = self.attach_tail_ref.get()
            head_progress = (
                progress_to(
                    attach_head.target_scaled_time,
                    group_scaled_time(attach_head.timescale_group),
                    group_force_note_speed(attach_head.timescale_group),
                )
                if current_time < attach_head.target_time
                else 1.0
            )
            tail_progress = progress_to(
                attach_tail.target_scaled_time,
                group_scaled_time(attach_tail.timescale_group),
                group_force_note_speed(attach_tail.timescale_group),
            )
            head_frac = (
                0.0
                if current_time < attach_head.target_time
                else get_attach_frac(attach_head.target_time, attach_tail.target_time, current_time)
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
    def effective_attach_head(self) -> WatchBaseNote:
        ref = +EntityRef[WatchBaseNote]
        if self.is_attached:
            ref @= self.attach_head_ref
        else:
            ref @= self.ref()
        return ref.get()

    @property
    def effective_attach_tail(self) -> WatchBaseNote:
        ref = +EntityRef[WatchBaseNote]
        if self.is_attached:
            ref @= self.attach_tail_ref
        else:
            ref @= self.ref()
        return ref.get()


def compute_slide_input_bounds(
    ease_type: EaseType, head: WatchBaseNote, tail: WatchBaseNote, t: float, leniency: float
) -> Quad:
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


WATCH_NOTE_ARCHETYPES = derive_note_archetypes(WatchBaseNote)
