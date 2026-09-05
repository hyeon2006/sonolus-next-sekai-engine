from __future__ import annotations

from math import ceil, floor, pi

from sonolus.script.archetype import (
    EntityRef,
    PlayArchetype,
    StandardImport,
    callback,
    entity_data,
    imported,
    shared_memory,
)
from sonolus.script.interval import clamp
from sonolus.script.runtime import time
from sonolus.script.timing import beat_to_bpm, beat_to_time

from sekai.lib import archetype_names
from sekai.lib.baseevent import BaseEvent, init_event_list
from sekai.lib.ease import EaseType
from sekai.lib.events import Fever, draw_judgment_effect
from sekai.lib.layout import (
    StageTransform,
    StageTransformAnchor,
    ZoomVerticalAlign,
    identity_stage_transform,
    layout_lane_area,
    preempt_time,
    touch_to_lane,
)
from sekai.lib.level_config import LevelConfig
from sekai.lib.options import Options
from sekai.lib.stage import (
    DivisionParity,
    JudgeLineColor,
    JudgeLineStyle,
    StageBorderStyle,
    StageProps,
    get_draw_end_time,
    get_draw_start_time,
    get_end_time,
    get_stage_props,
    get_start_time,
    play_lane_hit_effects,
)
from sekai.play import input_manager
from sekai.play.common import PlayLevelMemory
from sekai.play.events import SkillActive
from sekai.play.static_stage import StageMemory


class CameraChange(PlayArchetype, BaseEvent):
    name = archetype_names.CAMERA_CHANGE

    beat: StandardImport.BEAT
    lane: float = imported()
    size: float = imported()
    zoom: float = imported(default=1)
    zoom_target_lane: float = imported(name="zoomTargetLane")
    zoom_target_y: float = imported(name="zoomTargetY")
    zoom_vertical_align: ZoomVerticalAlign = imported(name="zoomVerticalAlign")
    rotate: float = imported()
    stage_tilt: float = imported(name="stageTilt", default=1)
    ease: EaseType = imported()
    next_ref: EntityRef[CameraChange] = imported(name="next")

    time: float = entity_data()

    @callback(order=-2)
    def preprocess(self):
        LevelConfig.dynamic_stages = True
        self.time = beat_to_time(self.beat)
        self.zoom = max(self.zoom, 0.01)
        self.rotate = self.rotate * pi / 180
        self.stage_tilt = clamp(self.stage_tilt, 0, 1)
        if Options.mirror:
            self.lane *= -1
            self.zoom_target_lane *= -1
            self.rotate *= -1

    def spawn_order(self) -> float:
        return 1e8

    def should_spawn(self) -> bool:
        return False


class StageTransformChange(PlayArchetype, BaseEvent):
    name = archetype_names.STAGE_TRANSFORM_CHANGE

    stage_ref: EntityRef[DynamicStage] = imported(name="stage")
    beat: StandardImport.BEAT
    rotate: float = imported()
    x_lane_translate: float = imported(name="xLaneTranslate")
    y_lane_translate: float = imported(name="yLaneTranslate")
    anchor: StageTransformAnchor = imported(name="anchor")
    ease: EaseType = imported()
    next_ref: EntityRef[StageTransformChange] = imported(name="next")

    time: float = entity_data()

    @callback(order=-3)
    def preprocess(self):
        LevelConfig.dynamic_stages = True
        LevelConfig.has_stage_transforms = True
        self.time = beat_to_time(self.beat)
        self.rotate = self.rotate * pi / 180
        if Options.mirror:
            self.rotate *= -1
            self.x_lane_translate *= -1

    def spawn_order(self) -> float:
        return 1e8

    def should_spawn(self) -> bool:
        return False


class DynamicStage(PlayArchetype):
    name = archetype_names.STAGE

    from_start: bool = imported(name="fromStart")
    until_end: bool = imported(name="untilEnd")
    first_mask_change_ref: EntityRef[StageMaskChange] = imported(name="firstMaskChange")
    first_pivot_change_ref: EntityRef[StagePivotChange] = imported(name="firstPivotChange")
    first_style_change_ref: EntityRef[StageStyleChange] = imported(name="firstStyleChange")
    first_transform_change_ref: EntityRef[StageTransformChange] = imported(name="firstTransformChange")

    start_time: float = entity_data()
    end_time: float = entity_data()
    draw_start_time: float = entity_data()
    draw_end_time: float = entity_data()

    props: StageProps = shared_memory()

    @callback(order=-2)
    def preprocess(self):
        LevelConfig.dynamic_stages = True
        LevelConfig.skip_default_stage = True
        init_event_list(self.first_mask_change_ref)
        init_event_list(self.first_pivot_change_ref)
        init_event_list(self.first_style_change_ref)
        init_event_list(self.first_transform_change_ref)
        self.start_time = get_start_time(self)
        self.end_time = get_end_time(self)
        self.draw_start_time = get_draw_start_time(self)
        self.draw_end_time = get_draw_end_time(self)

    def spawn_order(self) -> float:
        return self.start_time

    def should_spawn(self) -> bool:
        return time() >= self.start_time

    @callback(order=-1)
    def update_sequential(self):
        self.props @= get_stage_props(self)
        if time() >= self.end_time:
            self.despawn = True
            return
        self.fever_boundary()

    def fever_boundary(self):
        if self.props.lane_alpha > 0:
            l = self.props.lane - self.props.width
            r = self.props.lane + self.props.width
            stage_transform = +StageTransform
            if self.props.has_transform():
                stage_transform @= self.props.stage_transform()
            else:
                stage_transform @= identity_stage_transform()
            transform = stage_transform.transform()

            if l < Fever.min_l:
                Fever.min_l = l
                Fever.alpha_l = self.props.lane_alpha
                Fever.left_transform = transform
            elif l == Fever.min_l and self.props.lane_alpha > Fever.alpha_l:
                Fever.alpha_l = self.props.lane_alpha
                Fever.left_transform = transform

            if r > Fever.max_r:
                Fever.max_r = r
                Fever.alpha_r = self.props.lane_alpha
                Fever.right_transform = transform
            elif r == Fever.max_r and self.props.lane_alpha > Fever.alpha_r:
                Fever.alpha_r = self.props.lane_alpha
                Fever.right_transform = transform

            Fever.has_active = True
            Fever.y_offset = self.props.y_offset

    @callback(order=2)
    def touch(self):
        t = time()
        if t < self.draw_start_time or t > self.draw_end_time:
            return
        p = self.props
        if p.lane_alpha * (1 - p.full_width) < 1:
            return
        half_offset = p.division.start.parity == DivisionParity.ODD and p.division.start.size % 2 == 1
        lo = p.lane - p.width + 0.5
        hi = p.lane + p.width - 0.5
        if half_offset:
            leftmost = p.pivot_lane + ceil(lo - p.pivot_lane)
            rightmost = p.pivot_lane + floor(hi - p.pivot_lane)
        else:
            leftmost = p.pivot_lane + 0.5 + ceil(lo - p.pivot_lane - 0.5)
            rightmost = p.pivot_lane + 0.5 + floor(hi - p.pivot_lane - 0.5)
        if leftmost > rightmost:
            return
        has_transform = p.has_transform()
        transform = +StageTransform
        if has_transform:
            transform @= p.stage_transform()
        else:
            transform @= identity_stage_transform()
        transform_mat = transform.transform()
        total_hitbox = transform_mat.transform_quad(layout_lane_area(leftmost - 1.5, rightmost + 1.5))
        empty_lanes = StageMemory.empty_lanes
        empty_triggered = False
        for touch in input_manager.processed_touches():
            if not total_hitbox.contains_point(touch.position):
                continue
            if not input_manager.is_allowed_empty(touch):
                continue
            lane = touch_to_lane(touch.position, transform_mat)
            rel = lane - p.pivot_lane
            if half_offset:
                rounded_lane = clamp(p.pivot_lane + round(rel), lo, hi)
            else:
                rounded_lane = clamp(p.pivot_lane + round(rel - 0.5) + 0.5, lo, hi)
            if touch.started:
                play_lane_hit_effects(
                    rounded_lane, sfx=time() > PlayLevelMemory.last_note_sfx_time + 0.6, transform=transform_mat
                )
                empty_triggered = True
                if not empty_lanes.is_full():
                    empty_lanes.append(rounded_lane)
            else:
                prev_lane = touch_to_lane(touch.prev_position, transform_mat)
                prev_rel = prev_lane - p.pivot_lane
                if half_offset:
                    prev_rounded_lane = clamp(p.pivot_lane + round(prev_rel), lo, hi)
                else:
                    prev_rounded_lane = clamp(p.pivot_lane + round(prev_rel - 0.5) + 0.5, lo, hi)
                if rounded_lane != prev_rounded_lane:
                    play_lane_hit_effects(
                        rounded_lane, sfx=time() > PlayLevelMemory.last_note_sfx_time + 0.6, transform=transform_mat
                    )
                    empty_triggered = True
                    if not empty_lanes.is_full():
                        empty_lanes.append(rounded_lane)
        if empty_triggered:
            input_manager.release_all_empty_disallows()

    def update_parallel(self):
        t = time()
        if t < self.draw_start_time or t > self.draw_end_time:
            return
        self.props.draw()
        if SkillActive.judgment:
            elapsed = t - SkillActive.start_time
            if elapsed < SkillActive.duration:
                l = self.props.lane - self.props.width
                r = self.props.lane + self.props.width
                stage_transform = +StageTransform
                if self.props.has_transform():
                    stage_transform @= self.props.stage_transform()
                else:
                    stage_transform @= identity_stage_transform()
                draw_judgment_effect(
                    elapsed,
                    l,
                    r,
                    self.props.judge_line_alpha,
                    self.props.y_offset,
                    duration=SkillActive.duration,
                    transform=stage_transform.transform(),
                )


class StageMaskChange(PlayArchetype, BaseEvent):
    name = archetype_names.STAGE_MASK_CHANGE

    stage_ref: EntityRef[DynamicStage] = imported(name="stage")
    beat: StandardImport.BEAT
    lane: float = imported()
    size: float = imported()
    mask_notes: bool = imported(name="maskNotes", default=False)
    ease: EaseType = imported()
    next_ref: EntityRef[StageMaskChange] = imported(name="next")

    time: float = entity_data()

    @callback(order=-3)
    def preprocess(self):
        LevelConfig.dynamic_stages = True
        self.time = beat_to_time(self.beat)
        if Options.mirror:
            self.lane *= -1

    def spawn_order(self) -> float:
        return 1e8

    def should_spawn(self) -> bool:
        return False


class StagePivotChange(PlayArchetype, BaseEvent):
    name = archetype_names.STAGE_PIVOT_CHANGE

    stage_ref: EntityRef[DynamicStage] = imported(name="stage")
    beat: StandardImport.BEAT
    lane: float = imported()
    division_size: float = imported(name="divisionSize")
    division_parity: DivisionParity = imported(name="divisionParity")
    abs_y_offset: float = imported(name="yOffset")
    y_beat_offset: float = imported(name="yBeatOffset")
    ease: EaseType = imported()
    next_ref: EntityRef[StagePivotChange] = imported(name="next")

    y_offset: float = entity_data()
    time: float = entity_data()

    @callback(order=-3)
    def preprocess(self):
        LevelConfig.dynamic_stages = True
        self.time = beat_to_time(self.beat)
        self.y_offset = self.abs_y_offset + self.y_beat_offset * 60 / beat_to_bpm(self.beat) / preempt_time()
        if Options.mirror:
            self.lane *= -1

    def spawn_order(self) -> float:
        return 1e8

    def should_spawn(self) -> bool:
        return False


class StageStyleChange(PlayArchetype, BaseEvent):
    name = archetype_names.STAGE_STYLE_CHANGE

    stage_ref: EntityRef[DynamicStage] = imported(name="stage")
    beat: StandardImport.BEAT
    judge_line_color: JudgeLineColor = imported(name="judgeLineColor")
    judge_line_style: JudgeLineStyle = imported(name="judgeLineStyle")
    left_border_style: StageBorderStyle = imported(name="leftBorderStyle")
    right_border_style: StageBorderStyle = imported(name="rightBorderStyle")
    full_width: bool = imported(name="fullWidth")
    alpha: float = imported(default=1)  # Deprecated
    lane_alpha: float = imported(name="laneAlpha")
    judge_line_alpha: float = imported(name="judgeLineAlpha")
    division_line_alpha: float = imported(name="divisionLineAlpha", default=1)
    note_alpha: float = imported(name="noteAlpha", default=1)
    ease: EaseType = imported()
    next_ref: EntityRef[StageStyleChange] = imported(name="next")

    time: float = shared_memory()

    @callback(order=-3)
    def preprocess(self):
        LevelConfig.dynamic_stages = True
        self.time = beat_to_time(self.beat)
        self.lane_alpha *= self.alpha
        self.judge_line_alpha *= self.alpha
        if Options.mirror:
            self.left_border_style, self.right_border_style = self.right_border_style, self.left_border_style

    def spawn_order(self) -> float:
        return 1e8

    def should_spawn(self) -> bool:
        return False
