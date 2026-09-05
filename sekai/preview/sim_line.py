from sonolus.script.archetype import EntityRef, PreviewArchetype, imported

from sekai.lib import archetype_names
from sekai.lib.layer import LAYER_SIM_LINE, get_z
from sekai.lib.skin import ActiveSkin
from sekai.preview.layout import layout_preview_sim_line
from sekai.preview.note import PreviewBaseNote


class PreviewSimLine(PreviewArchetype):
    name = archetype_names.SIM_LINE

    left_ref: EntityRef[PreviewBaseNote] = imported(name="left")
    right_ref: EntityRef[PreviewBaseNote] = imported(name="right")

    def render(self):
        if not self.left.is_scored or not self.right.is_scored:
            return
        left_lane, left_size = self.left.visual_extents_at(self.left.target_time, left_limit=True)
        right_lane, right_size = self.right.visual_extents_at(self.right.target_time, left_limit=True)
        if left_size <= 0 or right_size <= 0:
            return
        layout = layout_preview_sim_line(
            left_lane=left_lane,
            right_lane=right_lane,
            col=self.left.preview_col,
            y=self.left.preview_y,
        )
        ActiveSkin.sim_line.draw(layout, z=get_z(LAYER_SIM_LINE).tuple)

    @property
    def left(self) -> PreviewBaseNote:
        return self.left_ref.get()

    @property
    def right(self) -> PreviewBaseNote:
        return self.right_ref.get()
