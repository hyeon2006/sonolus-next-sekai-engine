from sonolus.script.archetype import EntityRef, PlayArchetype, callback, entity_data, imported
from sonolus.script.runtime import time

from sekai.debug import DISABLE_NOTES
from sekai.lib import archetype_names
from sekai.lib.sim_line import draw_sim_line
from sekai.lib.timescale import group_hide_notes, update_timescale_group
from sekai.play.note import BaseNote


class SimLine(PlayArchetype):
    name = archetype_names.SIM_LINE

    left_ref: EntityRef[BaseNote] = imported(name="left")
    right_ref: EntityRef[BaseNote] = imported(name="right")

    spawn_time: float = entity_data()

    @callback(order=1)
    def preprocess(self):
        if DISABLE_NOTES:
            return
        self.spawn_time = min(self.left.start_time, self.right.start_time)
        end_time = max(self.left.target_time, self.right.target_time) + 1.0
        self.left.extend_stage_windows(self.spawn_time - 1.0, end_time)
        self.right.extend_stage_windows(self.spawn_time - 1.0, end_time)

    def spawn_order(self) -> float:
        if DISABLE_NOTES:
            return 1e8
        return self.spawn_time

    def should_spawn(self) -> bool:
        if DISABLE_NOTES:
            return False
        return time() >= self.spawn_time

    def update_sequential(self):
        update_timescale_group(self.left.timescale_group)
        update_timescale_group(self.right.timescale_group)

    def update_parallel(self):
        if self.left.is_despawned or self.right.is_despawned or time() > self.left.target_time:
            self.despawn = True
            return
        if group_hide_notes(self.left.timescale_group) or group_hide_notes(self.right.timescale_group):
            return
        left_lane, left_size = self.left.visual_extents
        right_lane, right_size = self.right.visual_extents
        if left_size <= 0 or right_size <= 0:
            return
        draw_sim_line(
            left_lane=left_lane,
            left_visual_progress=self.left.visual_progress,
            left_target_time=self.left.target_time,
            right_lane=right_lane,
            right_visual_progress=self.right.visual_progress,
            right_target_time=self.right.target_time,
            left_transform=self.left.visual_stage_transform().transform(),
            right_transform=self.right.visual_stage_transform().transform(),
            left_note_alpha=self.left.visual_note_alpha,
            right_note_alpha=self.right.visual_note_alpha,
        )

    @property
    def left(self) -> BaseNote:
        return self.left_ref.get()

    @property
    def right(self) -> BaseNote:
        return self.right_ref.get()
