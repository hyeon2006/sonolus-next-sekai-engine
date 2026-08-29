from sonolus.script.archetype import PlayArchetype, callback
from sonolus.script.array import Dim
from sonolus.script.containers import VarArray
from sonolus.script.globals import level_memory
from sonolus.script.interval import clamp
from sonolus.script.runtime import offset_adjusted_time, time

from sekai.lib import archetype_names
from sekai.lib.layout import IDENTITY_AFFINE_TRANSFORM, layout_lane_area, refresh_layout, touch_to_lane
from sekai.lib.level_config import LevelConfig
from sekai.lib.stage import draw_stage_and_accessories, play_lane_hit_effects
from sekai.lib.streams import Streams
from sekai.play import input_manager
from sekai.play.common import PlayLevelMemory


@level_memory
class StageMemory:
    empty_lanes: VarArray[float, Dim[16]]


class StaticStage(PlayArchetype):
    name = archetype_names.STATIC_STAGE

    def spawn_order(self) -> float:
        return -1e8

    def should_spawn(self) -> bool:
        return True

    @callback(order=-2)
    def update_sequential(self):
        refresh_layout()

    @callback(order=3)
    def touch(self):
        empty_lanes = StageMemory.empty_lanes
        if LevelConfig.dynamic_stages:
            if len(empty_lanes) > 0:
                Streams.empty_input_lanes[offset_adjusted_time()] = empty_lanes
                empty_lanes.clear()
            return
        empty_lanes.clear()
        total_hitbox = layout_lane_area(-7, 7)
        for touch in input_manager.processed_touches():
            if not total_hitbox.contains_point(touch.position):
                continue
            if not input_manager.is_allowed_empty(touch):
                continue
            lane = touch_to_lane(touch.position, IDENTITY_AFFINE_TRANSFORM)
            rounded_lane = clamp(round(lane - 0.5) + 0.5, -5.5, 5.5)
            if touch.started:
                play_lane_hit_effects(
                    rounded_lane,
                    sfx=time() > PlayLevelMemory.last_note_sfx_time + 0.6,
                    transform=IDENTITY_AFFINE_TRANSFORM,
                )
                if not empty_lanes.is_full():
                    empty_lanes.append(rounded_lane)
            else:
                prev_lane = touch_to_lane(touch.prev_position, IDENTITY_AFFINE_TRANSFORM)
                prev_rounded_lane = clamp(round(prev_lane - 0.5) + 0.5, -5.5, 5.5)
                if rounded_lane != prev_rounded_lane:
                    play_lane_hit_effects(
                        rounded_lane,
                        sfx=time() > PlayLevelMemory.last_note_sfx_time + 0.6,
                        transform=IDENTITY_AFFINE_TRANSFORM,
                    )
                    if not empty_lanes.is_full():
                        empty_lanes.append(rounded_lane)
        if len(empty_lanes) > 0:
            Streams.empty_input_lanes[offset_adjusted_time()] = empty_lanes

    def update_parallel(self):
        draw_stage_and_accessories()
