from sonolus.script.archetype import WatchArchetype, callback, entity_memory
from sonolus.script.runtime import is_skip, time

from sekai.lib import archetype_names
from sekai.lib.custom_elements import LifeManager, ScoreIndicator, reset_skill_hide
from sekai.lib.events import reset_fever_bounds
from sekai.lib.initialization import LastNote
from sekai.lib.layout import (
    IDENTITY_AFFINE_TRANSFORM,
    StaticStageData,
    refresh_layout,
)
from sekai.lib.stage import draw_stage_and_accessories, play_lane_particle


class WatchStaticStage(WatchArchetype):
    name = archetype_names.STATIC_STAGE
    dead_time: float = entity_memory()

    def spawn_time(self) -> float:
        return -1e8

    def despawn_time(self) -> float:
        return 1e8

    def initialize(self):
        self.dead_time = -2

    @callback(order=-2)
    def update_sequential(self):
        refresh_layout()
        reset_fever_bounds()
        reset_skill_hide()

    def update_parallel(self):
        draw_stage_and_accessories(
            ScoreIndicator.ap,
            ScoreIndicator.score,
            ScoreIndicator.note_score,
            ScoreIndicator.note_time,
            ScoreIndicator.percentage,
            StaticStageData.background_cover,
            StaticStageData.dead_effect_quads,
            StaticStageData.ui_layout,
            LifeManager.life / LifeManager.scale,
            LastNote.last_time,
            self.dead_time,
            StaticStageData.layout_stage,
        )
        if LifeManager.life == 0 and self.dead_time != -2:
            self.dead_time = time()


class WatchScheduledLaneEffect(WatchArchetype):
    name = archetype_names.SCHEDULED_LANE_EFFECT

    lane: float = entity_memory()
    target_time: float = entity_memory()

    def spawn_time(self) -> float:
        return self.target_time

    def despawn_time(self) -> float:
        return self.target_time + 1

    def initialize(self):
        if is_skip():
            return
        play_lane_particle(self.lane, IDENTITY_AFFINE_TRANSFORM)
