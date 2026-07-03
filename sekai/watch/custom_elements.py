from sonolus.script.archetype import EntityRef, WatchArchetype, callback, entity_memory
from sonolus.script.runtime import is_replay, is_skip, time

from sekai.lib import archetype_names
from sekai.lib.custom_elements import (
    LifeManager,
    ScoreIndicator,
    draw_combo_label,
    draw_combo_number,
    draw_damage_flash,
    draw_judgment_accuracy,
    draw_judgment_text,
)
from sekai.lib.options import Options
from sekai.watch import note
from sekai.watch.events import Fever


def spawn_custom(
    next_ref: EntityRef[note.WatchBaseNote],
    note_index: int,
):
    ComboJudge.spawn(
        next_ref=next_ref,
        note_index=note_index,
    )


class StateManager(WatchArchetype):
    """Resets score/life/fever level-memory state on skips.

    When a skip lands before the first judgment, no ComboJudge or Skill entity is active to
    rewrite this state, so an always-active entity has to restore the initial values.
    """

    name = archetype_names.STATE_MANAGER

    def spawn_time(self) -> float:
        return -1e8

    def despawn_time(self) -> float:
        return 1e8

    @callback(order=-1)
    def update_sequential(self):
        if not is_skip():
            return
        if time() < ScoreIndicator.first:
            if Options.custom_score == 2:
                ScoreIndicator.percentage = 100
            else:
                ScoreIndicator.percentage = 0
            ScoreIndicator.score = 0
            ScoreIndicator.ap = False
            Fever.fever_chance_current_combo = 0
        if is_replay() and time() < LifeManager.first:
            LifeManager.life = LifeManager.initial_life


class ComboJudge(WatchArchetype):
    next_ref: EntityRef[note.WatchBaseNote] = entity_memory()
    note_index: int = entity_memory()
    checker: float = entity_memory()
    name = archetype_names.COMBO_JUDGE

    def spawn_time(self) -> float:
        return note.WatchBaseNote.at(self.note_index).calc_time

    def despawn_time(self):
        if self.next_ref.index > 0:
            return self.next_ref.get().calc_time
        else:
            return 1e8

    def update_parallel(self):
        current_note = note.WatchBaseNote.at(self.note_index)
        draw_combo_label(
            ap=current_note.ap,
            combo=current_note.combo,
        )
        draw_combo_number(
            draw_time=self.spawn_time(),
            ap=current_note.ap,
            combo=current_note.combo,
        )
        draw_judgment_text(
            draw_time=self.spawn_time(),
            judgment=current_note.judgment,
            windows=current_note.judgment_window,
            accuracy=current_note.accuracy,
        )

    @callback(order=3)
    def update_sequential(self):
        if self.checker:
            return
        current_note = note.WatchBaseNote.at(self.note_index)
        Fever.fever_chance_current_combo = current_note.fever_hits

        if Options.custom_score > 0 or Options.custom_score_bar:
            ScoreIndicator.score = current_note.score
            ScoreIndicator.percentage = current_note.percentage
            ScoreIndicator.ap = current_note.ap
            note_score = current_note.note_raw_score
            ScoreIndicator.note_score = note_score if note_score > 0 else ScoreIndicator.note_score
            ScoreIndicator.note_time = self.spawn_time() if note_score > 0 else ScoreIndicator.note_time

        if is_replay():
            LifeManager.life = current_note.replay_life

        self.checker = True

    def terminate(self):
        self.checker = False


class JudgmentAccuracy(WatchArchetype):
    next_ref: EntityRef[note.WatchBaseNote] = entity_memory()
    note_index: int = entity_memory()
    name = archetype_names.JUDGMENT_ACCURACY

    def spawn_time(self) -> float:
        if not Options.custom_accuracy:
            return 1e8
        return note.WatchBaseNote.at(self.note_index).calc_time

    def despawn_time(self):
        current_note = note.WatchBaseNote.at(self.note_index)
        if self.next_ref.index > 0 and current_note.calc_time + 0.5 >= self.next_ref.get().calc_time:
            return self.next_ref.get().calc_time
        else:
            return current_note.calc_time + 0.5

    def update_parallel(self):
        current_note = note.WatchBaseNote.at(self.note_index)
        draw_judgment_accuracy(
            judgment=current_note.judgment,
            windows=current_note.judgment_window,
            accuracy=current_note.accuracy,
            wrong_way=current_note.wrong_way_check,
        )


class DamageFlash(WatchArchetype):
    next_ref: EntityRef[note.WatchBaseNote] = entity_memory()
    note_index: int = entity_memory()
    name = archetype_names.DAMAGE_FLASH

    def spawn_time(self) -> float:
        if not Options.custom_damage:
            return 1e8
        return note.WatchBaseNote.at(self.note_index).calc_time

    def despawn_time(self):
        current_note = note.WatchBaseNote.at(self.note_index)
        if self.next_ref.index > 0 and current_note.calc_time + 0.35 >= self.next_ref.get().calc_time:
            return self.next_ref.get().calc_time
        else:
            return current_note.calc_time + 0.35

    def update_parallel(self):
        draw_damage_flash(draw_time=self.spawn_time())


CUSTOM_ARCHETYPES = (StateManager, ComboJudge, JudgmentAccuracy, DamageFlash)
