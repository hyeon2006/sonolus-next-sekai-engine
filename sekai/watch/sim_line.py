from sonolus.script.archetype import EntityRef, WatchArchetype, callback, entity_data, imported
from sonolus.script.runtime import is_replay

from sekai.debug import DISABLE_NOTES
from sekai.lib import archetype_names
from sekai.lib.sim_line import draw_sim_line
from sekai.lib.timescale import group_hide_notes, update_timescale_group
from sekai.watch.note import WatchBaseNote


class WatchSimLine(WatchArchetype):
    name = archetype_names.SIM_LINE

    left_ref: EntityRef[WatchBaseNote] = imported(name="left")
    right_ref: EntityRef[WatchBaseNote] = imported(name="right")

    start_time: float = entity_data()
    end_time: float = entity_data()

    @callback(order=1)
    def preprocess(self):
        if DISABLE_NOTES:
            return
        self.start_time = min(self.left.start_time, self.right.start_time)
        if is_replay():
            self.end_time = min(self.left.end_time, self.right.end_time, self.left.target_time)
        else:
            self.end_time = min(self.left.target_time, self.right.target_time)
        self.left.extend_stage_windows(self.start_time - 1.0, self.end_time + 1.0)
        self.right.extend_stage_windows(self.start_time - 1.0, self.end_time + 1.0)

    def spawn_time(self) -> float:
        if DISABLE_NOTES:
            return 1e8
        return self.start_time

    def despawn_time(self) -> float:
        return self.end_time

    def update_sequential(self):
        update_timescale_group(self.left.timescale_group)
        update_timescale_group(self.right.timescale_group)

    def update_parallel(self):
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
    def left(self) -> WatchBaseNote:
        return self.left_ref.get()

    @property
    def right(self) -> WatchBaseNote:
        return self.right_ref.get()
