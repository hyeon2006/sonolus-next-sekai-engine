from __future__ import annotations

from math import pi

from sonolus.script.archetype import (
    EntityRef,
    PreviewArchetype,
    StandardImport,
    callback,
    entity_data,
    imported,
    shared_memory,
)
from sonolus.script.interval import clamp
from sonolus.script.timing import beat_to_bpm, beat_to_time

from sekai.lib import archetype_names
from sekai.lib.baseevent import BaseEvent, init_event_list
from sekai.lib.ease import EaseType
from sekai.lib.layout import StageTransformAnchor, ZoomVerticalAlign, preempt_time
from sekai.lib.level_config import LevelConfig
from sekai.lib.options import Options
from sekai.lib.stage import (
    DivisionParity,
    JudgeLineColor,
    JudgeLineStyle,
    StageBorderStyle,
    get_draw_end_time,
    get_draw_start_time,
    get_end_time,
    get_start_time,
)
from sekai.preview.stage import draw_preview_dynamic_stage


class PreviewCameraChange(PreviewArchetype, BaseEvent):
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
    next_ref: EntityRef[PreviewCameraChange] = imported(name="next")

    time: float = entity_data()

    @callback(order=-3)
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


class PreviewStageTransformChange(PreviewArchetype, BaseEvent):
    name = archetype_names.STAGE_TRANSFORM_CHANGE

    stage_ref: EntityRef[PreviewDynamicStage] = imported(name="stage")
    beat: StandardImport.BEAT
    rotate: float = imported()
    x_lane_translate: float = imported(name="xLaneTranslate")
    y_lane_translate: float = imported(name="yLaneTranslate")
    anchor: StageTransformAnchor = imported(name="anchor")
    ease: EaseType = imported()
    next_ref: EntityRef[PreviewStageTransformChange] = imported(name="next")

    time: float = entity_data()

    @callback(order=-3)
    def preprocess(self):
        LevelConfig.dynamic_stages = True
        self.time = beat_to_time(self.beat)
        self.rotate = self.rotate * pi / 180
        if Options.mirror:
            self.rotate *= -1
            self.x_lane_translate *= -1


class PreviewDynamicStage(PreviewArchetype):
    name = archetype_names.STAGE

    from_start: bool = imported(name="fromStart")
    until_end: bool = imported(name="untilEnd")
    first_mask_change_ref: EntityRef[PreviewStageMaskChange] = imported(name="firstMaskChange")
    first_pivot_change_ref: EntityRef[PreviewStagePivotChange] = imported(name="firstPivotChange")
    first_style_change_ref: EntityRef[PreviewStageStyleChange] = imported(name="firstStyleChange")
    first_transform_change_ref: EntityRef[PreviewStageTransformChange] = imported(name="firstTransformChange")

    start_time: float = entity_data()
    end_time: float = entity_data()
    draw_start_time: float = entity_data()
    draw_end_time: float = entity_data()

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

    def render(self):
        if not LevelConfig.dynamic_stages:
            return
        draw_preview_dynamic_stage(self, self.draw_start_time, self.draw_end_time)


class PreviewStageMaskChange(PreviewArchetype, BaseEvent):
    name = archetype_names.STAGE_MASK_CHANGE

    stage_ref: EntityRef[PreviewDynamicStage] = imported(name="stage")
    beat: StandardImport.BEAT
    lane: float = imported()
    size: float = imported()
    mask_notes: bool = imported(name="maskNotes", default=False)
    ease: EaseType = imported()
    next_ref: EntityRef[PreviewStageMaskChange] = imported(name="next")

    time: float = entity_data()

    @callback(order=-3)
    def preprocess(self):
        self.time = beat_to_time(self.beat)
        if Options.mirror:
            self.lane *= -1


class PreviewStagePivotChange(PreviewArchetype, BaseEvent):
    name = archetype_names.STAGE_PIVOT_CHANGE

    stage_ref: EntityRef[PreviewDynamicStage] = imported(name="stage")
    beat: StandardImport.BEAT
    lane: float = imported()
    division_size: float = imported(name="divisionSize")
    division_parity: DivisionParity = imported(name="divisionParity")
    abs_y_offset: float = imported(name="yOffset")
    y_beat_offset: float = imported(name="yBeatOffset")
    ease: EaseType = imported()
    next_ref: EntityRef[PreviewStagePivotChange] = imported(name="next")

    y_offset: float = entity_data()
    time: float = entity_data()

    @callback(order=-3)
    def preprocess(self):
        self.time = beat_to_time(self.beat)
        self.y_offset = self.abs_y_offset + self.y_beat_offset * 60 / beat_to_bpm(self.beat) / preempt_time()
        if Options.mirror:
            self.lane *= -1


class PreviewStageStyleChange(PreviewArchetype, BaseEvent):
    name = archetype_names.STAGE_STYLE_CHANGE

    stage_ref: EntityRef[PreviewDynamicStage] = imported(name="stage")
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
    next_ref: EntityRef[PreviewStageStyleChange] = imported(name="next")

    time: float = shared_memory()

    @callback(order=-3)
    def preprocess(self):
        self.time = beat_to_time(self.beat)
        self.lane_alpha *= self.alpha
        self.judge_line_alpha *= self.alpha
        if Options.mirror:
            self.left_border_style, self.right_border_style = self.right_border_style, self.left_border_style
