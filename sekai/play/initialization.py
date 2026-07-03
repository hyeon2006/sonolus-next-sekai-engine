from sonolus.script.archetype import EntityRef, PlayArchetype, callback, entity_info_at, exported, imported
from sonolus.script.containers import sort_linked_entities
from sonolus.script.runtime import add_life_scheduled, level_score

from sekai.lib import archetype_names
from sekai.lib.baseevent import init_event_list
from sekai.lib.buckets import init_buckets
from sekai.lib.connector import (
    CONNECTOR_SFX_ACTIVE_TIME_INIT,
    CONNECTOR_SFX_INACTIVE_TIME_INIT,
    ActiveConnectorKind,
    ConnectorKind,
    connector_sfx_matches_kind,
    init_connector_sfx_times,
    schedule_connector_sfx,
)
from sekai.lib.custom_elements import init_fixed_ui_layout
from sekai.lib.initialization import LastNote, calculate_note_weight, count_entities, sort_entities_by_time
from sekai.lib.layout import (
    StaticStageData,
    init_layout,
    init_ui_margin,
    layout_background_cover,
    layout_dead_effect_quads,
    layout_sekai_stage,
    layout_static_ui,
)
from sekai.lib.level_config import (
    GAUGE_LIFE_UNIT,
    GAUGE_MAX_LIFE,
    EngineRevision,
    LevelConfig,
    init_level_config,
    init_particle_version,
    init_ui_version,
)
from sekai.lib.note import init_life, init_score
from sekai.lib.options import Options, SkillMode
from sekai.lib.particle import ActiveParticles, init_particles
from sekai.lib.skin import ActiveSkin, init_skin
from sekai.lib.ui import init_ui
from sekai.play import custom_elements, note
from sekai.play.common import init_play_common
from sekai.play.connector import Connector, ConnectorSfxManager
from sekai.play.dynamic_stage import CameraChange
from sekai.play.events import Fever, Skill
from sekai.play.input_manager import InputManager
from sekai.play.static_stage import StaticStage


class Initialization(PlayArchetype):
    name = archetype_names.INITIALIZATION

    revision: EngineRevision = imported(name="revision", default=EngineRevision.LATEST)
    initial_life: int = imported(name="initialLife", default=1000)
    first_camera_ref: EntityRef[CameraChange] = imported(name="firstCamera")

    replay_revision: EngineRevision = exported(name="replayRevision")

    @callback(order=-1)
    def preprocess(self):
        init_level_config(self.revision)
        init_layout()
        init_skin()
        init_particles()
        init_ui_version(ActiveSkin.ui_checker.check)
        init_ui_margin()
        init_ui()
        init_fixed_ui_layout()
        StaticStageData.ui_layout = layout_static_ui()
        StaticStageData.layout_stage = layout_sekai_stage()
        StaticStageData.background_cover = layout_background_cover()
        StaticStageData.dead_effect_quads = layout_dead_effect_quads()
        init_buckets()
        init_particle_version(ActiveParticles.ui_checker.check)
        init_score(note.NOTE_ARCHETYPES)
        init_play_common()
        init_connector_sfx_times()
        init_event_list(self.first_camera_ref)

        if LevelConfig.revision >= EngineRevision.GAUGE_REWORK:
            custom_elements.LifeManager.scale = GAUGE_LIFE_UNIT
            custom_elements.LifeManager.initial_life = min(self.initial_life, 1000) * GAUGE_LIFE_UNIT
            custom_elements.LifeManager.max_life = GAUGE_MAX_LIFE
        else:
            custom_elements.LifeManager.scale = 1
            custom_elements.LifeManager.initial_life = self.initial_life
            custom_elements.LifeManager.max_life = max(2000, self.initial_life * 2)
        custom_elements.LifeManager.life = custom_elements.LifeManager.initial_life

        entity_count = count_entities()
        total_combo = sorted_linked_list(entity_count)
        init_life(note.NOTE_ARCHETYPES, self.initial_life, total_combo)
        if Options.auto_sfx:
            schedule_auto_connector_sfx(entity_count)

    def initialize(self):
        StaticStage.spawn()
        InputManager.spawn()
        ConnectorSfxManager.spawn()
        self.replay_revision = self.revision

    def spawn_order(self) -> float:
        return -1e8

    def should_spawn(self) -> bool:
        return True

    def update_parallel(self):
        self.despawn = True


def sorted_linked_list(entity_count: int) -> int:
    note_head, note_length, skill_head, skill_length = initial_list(entity_count)

    sorted_skill_head = +EntityRef[Skill]
    if skill_length > 0:
        sorted_skill_head @= sort_entities_by_time(skill_head, Skill)
        count_skill(sorted_skill_head.index)

    if note_length > 0:
        sorted_note_head = sort_entities_by_time(note_head, note.BaseNote)
        setting_count(sorted_note_head.index, sorted_skill_head.index)
    else:
        # No scorable notes: the result can never change, so show the maximum score from the start.
        custom_elements.ScoreIndicator.max_score = 1000000
        custom_elements.ScoreIndicator.score = 1000000
        custom_elements.ScoreIndicator.percentage = 100

    return note_length


def initial_list(entity_count):
    note_head = 0
    note_length = 0
    skill_head = 0
    skill_length = 0

    note_id = note.BaseNote._compile_time_id()
    skill_id = Skill._compile_time_id()

    init_head = 0
    beats_ascending = True
    next_chain_beat = 1e8
    for i in range(entity_count):
        entity_index: int = entity_count - 1 - i
        if note_id in PlayArchetype._get_mro_id_array(entity_info_at(entity_index).archetype_id):
            chain_note = note.BaseNote.at(entity_index)
            if chain_note.beat > next_chain_beat:
                beats_ascending = False
            next_chain_beat = chain_note.beat
            chain_note.tick_head_ref.index = init_head
            init_head = entity_index

    def get_beat(n):
        return n.beat

    def get_chain_next(n):
        return n.tick_head_ref

    if not beats_ascending:
        init_head = sort_linked_entities(
            note.BaseNote.at(init_head).ref(), get_value=get_beat, get_next_ref=get_chain_next
        ).index

    init_index = init_head
    while init_index > 0:
        init_note = note.BaseNote.at(init_index)
        next_init_index = init_note.tick_head_ref.index
        init_note.init_data()
        init_note.tick_head_ref.index = 0
        init_index = next_init_index

    for i in range(entity_count):
        entity_index: int = entity_count - 1 - i
        info = entity_info_at(entity_index)
        mro = PlayArchetype._get_mro_id_array(info.archetype_id)
        is_note = note_id in mro
        is_skill = skill_id in mro
        if is_note:
            if note.BaseNote.at(entity_index).is_scored:
                note.BaseNote.at(entity_index).next_ref.index = note_head
                note_head = entity_index
                note_length += 1
        elif is_skill:
            Skill.at(entity_index).next_ref.index = skill_head
            skill_head = entity_index
            skill_length += 1

    return note_head, note_length, skill_head, skill_length


def schedule_auto_connector_sfx(entity_count: int):
    connector_id = Connector._compile_time_id()

    normal_head = 0
    critical_head = 0
    for i in range(entity_count - 1, -1, -1):
        info = entity_info_at(i)
        mro = PlayArchetype._get_mro_id_array(info.archetype_id)
        if connector_id not in mro:
            continue
        connector = Connector.at(i)
        if connector.active_head_ref.index <= 0:
            continue
        if connector.active_head.target_time == connector.active_tail.target_time:
            # Zero-length slide: its activation and release land on the same instant, which the
            # hold-wins-over-release tie-break would otherwise leave stuck on. It holds for no
            # duration, so skip it entirely.
            continue
        if connector_sfx_matches_kind(connector.segment_head.segment_kind, ConnectorKind.ACTIVE_NORMAL):
            connector.sfx_act_next.index = normal_head
            connector.sfx_deact_next.index = normal_head
            normal_head = i
        elif connector_sfx_matches_kind(connector.segment_head.segment_kind, ConnectorKind.ACTIVE_CRITICAL):
            connector.sfx_act_next.index = critical_head
            connector.sfx_deact_next.index = critical_head
            critical_head = i

    schedule_auto_connector_sfx_kind(normal_head, ConnectorKind.ACTIVE_NORMAL)
    schedule_auto_connector_sfx_kind(critical_head, ConnectorKind.ACTIVE_CRITICAL)


def schedule_auto_connector_sfx_kind(list_head: int, sfx_kind: ActiveConnectorKind):
    if list_head <= 0:
        return

    def act_time(c):
        return c.active_head.target_time

    def act_next(c):
        return c.sfx_act_next

    def deact_time(c):
        return c.active_tail.target_time

    def deact_next(c):
        return c.sfx_deact_next

    # O(N log N) merge sorts: one list ordered by activation time, one by deactivation time. Both
    # start from the same head; the activation sort only rewrites sfx_act_next, leaving the
    # sfx_deact_next chain (still headed at list_head) intact for the deactivation sort.
    act_ref = sort_linked_entities(Connector.at(list_head).ref(), get_value=act_time, get_next_ref=act_next).index
    deact_ref = sort_linked_entities(Connector.at(list_head).ref(), get_value=deact_time, get_next_ref=deact_next).index

    # Two-pointer merge sweep through the activation/deactivation events in time order, reproducing
    # the original hold state machine exactly.
    current_time = -1e8
    active_time = CONNECTOR_SFX_ACTIVE_TIME_INIT
    inactive_time = CONNECTOR_SFX_INACTIVE_TIME_INIT
    active_connector_index = 0

    while act_ref > 0 or deact_ref > 0:
        next_time = 1e8
        if act_ref > 0:
            next_time = Connector.at(act_ref).active_head.target_time
        if deact_ref > 0:
            deact_event_time = Connector.at(deact_ref).active_tail.target_time
            next_time = min(next_time, deact_event_time)

        if active_time >= inactive_time and active_connector_index > 0:
            schedule_connector_sfx(
                sfx_kind,
                Connector.at(active_connector_index).segment_head.timescale_group,
                current_time,
                next_time,
            )

        while act_ref > 0 and Connector.at(act_ref).active_head.target_time == next_time:
            if inactive_time == CONNECTOR_SFX_INACTIVE_TIME_INIT:
                inactive_time = next_time
            active_time = next_time
            active_connector_index = act_ref
            act_ref = Connector.at(act_ref).sfx_act_next.index

        while deact_ref > 0 and Connector.at(deact_ref).active_tail.target_time == next_time:
            inactive_time = next_time
            deact_ref = Connector.at(deact_ref).sfx_deact_next.index

        current_time = next_time

    if active_time >= inactive_time and active_connector_index > 0:
        schedule_connector_sfx(
            sfx_kind,
            Connector.at(active_connector_index).segment_head.timescale_group,
            current_time,
            LastNote.last_time,
        )


def setting_count(head: int, skill: int) -> None:
    ptr = head
    skill_ptr = skill
    count = 0
    current_note_weight = 0.0

    custom_elements.ScoreIndicator.max_score = 1000000
    while ptr > 0:
        if skill_ptr > 0 and note.BaseNote.at(ptr).target_time >= Skill.at(skill_ptr).start_time:
            if Skill.at(skill_ptr).effect == SkillMode.HEAL:
                skill_ptr = Skill.at(skill_ptr).next_ref.index
            elif Skill.at(skill_ptr).effect == SkillMode.SCORE or Skill.at(skill_ptr).effect == SkillMode.JUDGMENT:
                if Skill.at(skill_ptr).effect == SkillMode.SCORE:
                    boost = Skill.at(skill_ptr).scale
                else:
                    boost = 1.0
                skill_end_time = Skill.at(skill_ptr).start_time + Skill.at(skill_ptr).duration
                if note.BaseNote.at(ptr).target_time <= skill_end_time:
                    note.BaseNote.at(ptr).entity_score_multiplier += boost * (
                        note.BaseNote.at(ptr).archetype_score_multiplier + note.BaseNote.at(ptr).entity_score_multiplier
                    )
                else:
                    skill_ptr = Skill.at(skill_ptr).next_ref.index
        count += 1
        note.BaseNote.at(ptr).count += count

        # arcade score = judgmentMultiplier * (consecutiveJudgmentMultiplier + archetypeMultiplier + entityMultiplier)
        current_note_weight = level_score().perfect_multiplier * calculate_note_weight(
            perfect_step=count,
            great_step=count,
            good_step=count,
            archetype_multiplier=note.BaseNote.at(ptr).archetype_score_multiplier,
            entity_multiplier=note.BaseNote.at(ptr).entity_score_multiplier,
        )
        custom_elements.ScoreIndicator.total_weight.add(current_note_weight)

        if Fever.fever_chance_time <= note.BaseNote.at(ptr).target_time < Fever.fever_start_time:
            Fever.fever_first_count = (
                min(note.BaseNote.at(ptr).count, Fever.fever_first_count)
                if Fever.fever_first_count != 0
                else note.BaseNote.at(ptr).count
            )
            Fever.fever_last_count = max(note.BaseNote.at(ptr).count, Fever.fever_last_count)

        LastNote.last_time = max(LastNote.last_time, note.BaseNote.at(ptr).calc_time)
        ptr = note.BaseNote.at(ptr).next_ref.index

    if Options.custom_score == 2:
        custom_elements.ScoreIndicator.percentage = 100


def count_skill(head: int) -> None:
    ptr = head
    count = 0
    while ptr > 0:
        Skill.at(ptr).count = count
        count += 1
        if Skill.at(ptr).effect == SkillMode.HEAL:
            add_life_scheduled(Skill.at(ptr).value * custom_elements.LifeManager.scale, Skill.at(ptr).start_time)
        ptr = Skill.at(ptr).next_ref.index
