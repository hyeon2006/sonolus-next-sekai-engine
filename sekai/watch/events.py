from __future__ import annotations

from sonolus.script.archetype import (
    EntityRef,
    StandardImport,
    WatchArchetype,
    callback,
    entity_data,
    entity_memory,
    imported,
    shared_memory,
)
from sonolus.script.globals import level_memory
from sonolus.script.interval import clamp
from sonolus.script.runtime import is_replay, is_skip, time
from sonolus.script.timing import beat_to_time

from sekai.lib import archetype_names
from sekai.lib.custom_elements import LifeManager
from sekai.lib.effect import Effects
from sekai.lib.events import (
    Fever,
    draw_fever_gauge,
    draw_fever_side_bar,
    draw_fever_side_cover,
    draw_judgment_effect,
    draw_skill_bar,
    spawn_fever_chance_particle,
    spawn_fever_start_particle,
)
from sekai.lib.level_config import LevelConfig
from sekai.lib.options import Options, SkillMode
from sekai.lib.skin import ActiveSkin


@level_memory
class SkillActive:
    judgment: bool
    start_time: float
    duration: float


class Skill(WatchArchetype):
    beat: StandardImport.BEAT
    effect: SkillMode = imported(name="effect", default=SkillMode.LEVEL_DEFAULT)
    level: int = imported(name="level", default=1)
    value: int = imported(name="value", default=250)
    scale: float = imported(name="scale", default=1.0)
    duration: float = imported(name="duration", default=6)
    start_time: float = entity_data()
    current_life: float = entity_data()
    next_note_time: float = entity_data()
    name = archetype_names.SKILL
    count: int = shared_memory()
    next_ref: EntityRef[Skill] = entity_data()
    end_time_3: float = entity_memory()
    end_time_effect: float = entity_memory()

    @callback(order=-2)
    def preprocess(self):
        self.effect = SkillMode.from_options(SkillMode.LEVEL_DEFAULT, self.effect)
        self.start_time = beat_to_time(self.beat)
        self.end_time_3 = self.start_time + 3
        self.end_time_effect = self.start_time + self.duration
        if Options.hide_ui != 3 and Options.skill_effect and ActiveSkin.skill_bar_score.is_available:
            Effects.skill.schedule(self.start_time)
        # Native heal scheduling happens in initialization.count_skill, after LifeManager's life
        # scale is known (this preprocess runs before WatchInitialization's).

    def spawn_time(self):
        return -1e8 if self.count == 0 else self.start_time

    def despawn_time(self):
        if self.next_ref.index > 0:
            return self.next_ref.get().calc_time
        else:
            return 1e8

    def update_parallel(self):
        current_time = time()
        elapsed = current_time - self.start_time
        if 0 <= elapsed < 3:
            draw_skill_bar(elapsed, self.count, self.effect, self.level, self.value, self.scale, self.duration)
        if 0 <= elapsed < self.duration and self.effect == SkillMode.JUDGMENT and not LevelConfig.dynamic_stages:
            draw_judgment_effect(elapsed, duration=self.duration)

    @callback(order=4)
    def update_sequential(self):
        if not is_replay():
            if time() < self.start_time:
                LifeManager.life = LifeManager.initial_life
            else:
                LifeManager.life = self.current_life
        elif self.start_time <= time() < self.next_note_time:
            LifeManager.life = self.current_life
        t = time()
        if self.start_time <= t < self.end_time_effect and self.effect == SkillMode.JUDGMENT:
            SkillActive.judgment = True
            SkillActive.start_time = self.start_time
            SkillActive.duration = self.duration
        else:
            SkillActive.judgment = False

    @property
    def calc_time(self) -> float:
        return self.start_time


class FeverChance(WatchArchetype):
    beat: StandardImport.BEAT
    force: bool = imported(name="force")
    start_time: float = entity_memory()
    checker: int = entity_memory()
    counter: int = entity_memory()
    percentage: float = entity_memory()
    name = archetype_names.FEVER_CHANCE

    @callback(order=-2)
    def preprocess(self):
        self.start_time = beat_to_time(self.beat)
        Fever.fever_chance_time = (
            min(self.start_time, Fever.fever_chance_time) if Fever.fever_chance_time != 0 else self.start_time
        )

    def spawn_time(self):
        return self.start_time

    def despawn_time(self):
        return Fever.fever_start_time + 1

    def update_parallel(self):
        if not Options.forced_fever_chance and not self.force:
            return
        current_time = time()
        if is_skip():
            self.checker = 0
            if current_time <= self.start_time:
                self.percentage = 0
        if self.checker >= 2:
            return
        if current_time >= Fever.fever_start_time:
            spawn_fever_start_particle(self.percentage)
            self.checker = 2
            return
        if current_time >= Fever.fever_chance_time and not self.checker:
            spawn_fever_chance_particle()
            self.checker = 1
        self.percentage = clamp(
            Fever.fever_chance_current_combo / self.counter,
            0,
            0.9 if not Fever.fever_chance_cant_super_fever or self.percentage >= 0.9 else 0.89,
        )
        elapsed = current_time - self.start_time
        if Options.fever_effect == 0:
            draw_fever_side_cover(elapsed)
        draw_fever_side_bar(elapsed)
        draw_fever_gauge(self.percentage)

    @callback(order=3)
    def update_sequential(self):
        if self.checker:
            return
        self.counter = Fever.fever_last_count - Fever.fever_first_count

    def terminate(self):
        self.percentage = 0
        self.checker = 0


class FeverStart(WatchArchetype):
    beat: StandardImport.BEAT
    start_time: float = entity_memory()
    name = archetype_names.FEVER_START

    @callback(order=-2)
    def preprocess(self):
        self.start_time = beat_to_time(self.beat)
        Fever.fever_start_time = (
            min(self.start_time, Fever.fever_start_time) if Fever.fever_start_time != 0 else self.start_time
        )

    def spawn_time(self):
        return 1e8

    def despawn_time(self):
        return 1e8


EVENT_ARCHETYPES = (Skill, FeverChance, FeverStart)
