from __future__ import annotations

from sonolus.script.archetype import (
    EntityRef,
    PlayArchetype,
    StandardImport,
    callback,
    entity_data,
    entity_memory,
    imported,
    shared_memory,
)
from sonolus.script.globals import level_memory
from sonolus.script.interval import clamp
from sonolus.script.runtime import is_multiplayer, time
from sonolus.script.timing import beat_to_time

from sekai.lib import archetype_names
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
from sekai.play import custom_elements


@level_memory
class SkillActive:
    judgment: bool
    start_time: float
    duration: float


class Skill(PlayArchetype):
    beat: StandardImport.BEAT
    effect: SkillMode = imported(name="effect", default=SkillMode.LEVEL_DEFAULT)
    level: int = imported(name="level", default=1)
    value: int = imported(name="value", default=250)
    scale: float = imported(name="scale", default=1.0)
    duration: float = imported(name="duration", default=6)
    start_time: float = entity_data()
    count: int = shared_memory()
    next_ref: EntityRef[Skill] = entity_data()
    check: bool = entity_memory()
    end_time_3: float = entity_memory()
    end_time_effect: float = entity_memory()
    name = archetype_names.SKILL

    @callback(order=-2)
    def preprocess(self):
        self.effect = SkillMode.from_options(SkillMode.LEVEL_DEFAULT, self.effect)
        self.start_time = beat_to_time(self.beat)
        self.end_time_3 = self.start_time + 3
        self.end_time_effect = self.start_time + self.duration
        if Options.hide_ui != 3 and Options.skill_effect and ActiveSkin.skill_bar_score.is_available:
            Effects.skill.schedule(self.start_time)
        # Native heal scheduling happens in initialization.count_skill, after LifeManager's life
        # scale is known (this preprocess runs before Initialization's).

    def spawn_order(self):
        return self.start_time

    def should_spawn(self):
        return time() >= self.start_time

    def update_parallel(self):
        current_time = time()
        elapsed = current_time - self.start_time
        if current_time < self.end_time_3:
            draw_skill_bar(elapsed, self.count, self.effect, self.level, self.value, self.scale, self.duration)
        if current_time >= self.end_time_3 and (
            self.effect != SkillMode.JUDGMENT or current_time >= self.end_time_effect
        ):
            self.despawn = True
            return
        if self.effect == SkillMode.JUDGMENT and not LevelConfig.dynamic_stages:
            draw_judgment_effect(elapsed, duration=self.duration)

    def update_sequential(self):
        if time() >= self.end_time_effect:
            SkillActive.judgment = False
            return
        if self.effect == SkillMode.JUDGMENT:
            if not SkillActive.judgment:
                SkillActive.judgment = True
            SkillActive.start_time = self.start_time
            SkillActive.duration = self.duration
        if not self.check and custom_elements.LifeManager.life > 0 and self.effect == SkillMode.HEAL:
            custom_elements.LifeManager.life += self.value * custom_elements.LifeManager.scale
            custom_elements.LifeManager.life = clamp(
                custom_elements.LifeManager.life, 0, custom_elements.LifeManager.max_life
            )
        self.check = True

    @property
    def calc_time(self) -> float:
        return self.start_time


class FeverChance(PlayArchetype):
    beat: StandardImport.BEAT
    force: bool = imported(name="force")
    start_time: float = entity_memory()
    checker: bool = entity_memory()
    counter: int = entity_memory()
    percentage: float = entity_memory()
    name = archetype_names.FEVER_CHANCE
    z: float = entity_memory()
    z2: float = entity_memory()
    z3: float = entity_memory()
    z4: float = entity_memory()

    @callback(order=-2)
    def preprocess(self):
        self.start_time = beat_to_time(self.beat)
        Fever.fever_chance_time = (
            min(self.start_time, Fever.fever_chance_time) if Fever.fever_chance_time != 0 else self.start_time
        )

    def show_ui(self) -> bool:
        return is_multiplayer() or Options.forced_fever_chance or self.force

    def spawn_order(self):
        return self.start_time if self.show_ui() else 1e8

    def should_spawn(self):
        return self.show_ui() and time() >= self.start_time

    def update_parallel(self):
        current_time = time()
        elapsed = current_time - self.start_time

        if current_time >= Fever.fever_start_time:
            spawn_fever_start_particle(self.percentage)
            self.despawn = True
            return
        if current_time >= Fever.fever_chance_time and not self.checker:
            spawn_fever_chance_particle()
            self.checker = True
        self.percentage = clamp(
            Fever.fever_chance_current_combo / self.counter,
            0,
            0.9 if not Fever.fever_chance_cant_super_fever or self.percentage >= 0.9 else 0.89,
        )

        if Options.fever_effect == 0:
            draw_fever_side_cover(elapsed)
        draw_fever_side_bar(elapsed)
        draw_fever_gauge(self.percentage)

    @callback(order=3)
    def update_sequential(self):
        if self.checker:
            return
        self.counter = Fever.fever_last_count - Fever.fever_first_count


class FeverStart(PlayArchetype):
    beat: StandardImport.BEAT
    start_time: float = entity_memory()
    name = archetype_names.FEVER_START

    @callback(order=-2)
    def preprocess(self):
        self.start_time = beat_to_time(self.beat)
        Fever.fever_start_time = (
            min(self.start_time, Fever.fever_start_time) if Fever.fever_start_time != 0 else self.start_time
        )

    def spawn_order(self):
        return 1e8

    def should_spawn(self):
        return False


EVENT_ARCHETYPES = (Skill, FeverChance, FeverStart)
