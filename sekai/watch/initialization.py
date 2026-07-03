from math import floor

from sonolus.script.archetype import (
    EntityRef,
    WatchArchetype,
    callback,
    entity_info_at,
    imported,
)
from sonolus.script.bucket import Judgment
from sonolus.script.containers import sort_linked_entities
from sonolus.script.interval import clamp
from sonolus.script.runtime import add_life_scheduled, is_replay, level_score

from sekai.lib import archetype_names
from sekai.lib.baseevent import init_event_list
from sekai.lib.buckets import init_buckets
from sekai.lib.connector import (
    CONNECTOR_SFX_ACTIVE_TIME_INIT,
    CONNECTOR_SFX_INACTIVE_TIME_INIT,
    ActiveConnectorKind,
    ConnectorKind,
    connector_sfx_is_active,
    connector_sfx_matches_kind,
    inactive_connector_sfx_times,
    schedule_connector_sfx,
    schedule_connector_sfx_between,
)
from sekai.lib.custom_elements import LifeManager, NeumaierSum, init_fixed_ui_layout
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
from sekai.lib.stage import schedule_lane_sfx
from sekai.lib.streams import Streams
from sekai.lib.ui import init_ui
from sekai.watch import custom_elements, note
from sekai.watch.connector import WatchConnector
from sekai.watch.dynamic_stage import WatchCameraChange
from sekai.watch.events import Fever, Skill
from sekai.watch.static_stage import WatchScheduledLaneEffect, WatchStaticStage


class WatchInitialization(WatchArchetype):
    name = archetype_names.INITIALIZATION

    revision: EngineRevision = imported(name="revision", default=EngineRevision.LATEST)
    replay_revision: EngineRevision = imported(name="replayRevision", default=EngineRevision.BASE)
    initial_life: int = imported(name="initialLife", default=1000)
    first_camera_ref: EntityRef[WatchCameraChange] = imported(name="firstCamera")

    is_multi: bool = imported()

    @callback(order=-1)
    def preprocess(self):
        if is_replay():
            self.revision = self.replay_revision
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
        init_score(note.WATCH_NOTE_ARCHETYPES)

        if LevelConfig.revision >= EngineRevision.GAUGE_REWORK:
            LifeManager.scale = GAUGE_LIFE_UNIT
            LifeManager.initial_life = min(self.initial_life, 1000) * GAUGE_LIFE_UNIT
            LifeManager.max_life = GAUGE_MAX_LIFE
        else:
            LifeManager.scale = 1
            LifeManager.initial_life = self.initial_life
            LifeManager.max_life = max(2000, self.initial_life * 2)
        LifeManager.life = LifeManager.initial_life

        init_event_list(self.first_camera_ref)
        WatchStaticStage.spawn()
        custom_elements.StateManager.spawn()

        for input_time, lanes in Streams.empty_input_lanes.iter_items_from(-2):
            for lane in lanes:
                schedule_lane_sfx(lane, input_time)
                WatchScheduledLaneEffect.spawn(lane=lane, target_time=input_time)

        entity_count = count_entities()
        total_combo, sorted_note_head, sorted_skill_head = sorted_linked_list(entity_count)
        init_life(note.WATCH_NOTE_ARCHETYPES, self.initial_life, total_combo)
        # Must run after init_life: the sweep reads the archetype life increments it sets.
        if is_replay():
            calculate_replay_life(sorted_note_head, sorted_skill_head)

        if is_replay() and not Options.auto_sfx:
            schedule_replay_connector_sfx(
                Streams.connector_normal_sfx_times[0],
                ConnectorKind.ACTIVE_NORMAL,
            )
            schedule_replay_connector_sfx(
                Streams.connector_critical_sfx_times[0],
                ConnectorKind.ACTIVE_CRITICAL,
            )
        else:
            schedule_auto_connector_sfx(entity_count)


def sorted_linked_list(entity_count: int) -> tuple[int, int, int]:
    note_head, note_length, skill_head, skill_length = initial_list(entity_count)

    sorted_skill_head = +EntityRef[Skill]
    if skill_length > 0:
        sorted_skill_head @= sort_entities_by_time(skill_head, Skill)
        count_skill(sorted_skill_head.index)

    sorted_note_head = +EntityRef[note.WatchBaseNote]
    if note_length > 0:
        sorted_note_head @= sort_entities_by_time(note_head, note.WatchBaseNote)
        setting_combo(sorted_note_head.index, sorted_skill_head.index)
    else:
        custom_elements.ScoreIndicator.score = 1000000
        custom_elements.ScoreIndicator.percentage = 100
        custom_elements.ScoreIndicator.first = -1e8

    return note_length, sorted_note_head.index, sorted_skill_head.index


def initial_list(entity_count):
    note_head = 0
    note_length = 0
    skill_head = 0
    skill_length = 0

    note_id = note.WatchBaseNote._compile_time_id()
    skill_id = Skill._compile_time_id()

    init_head = 0
    beats_ascending = True
    next_chain_beat = 1e8
    for i in range(entity_count):
        entity_index = entity_count - 1 - i
        if note_id in WatchArchetype._get_mro_id_array(entity_info_at(entity_index).archetype_id):
            chain_note = note.WatchBaseNote.at(entity_index)
            if chain_note.beat > next_chain_beat:
                beats_ascending = False
            next_chain_beat = chain_note.beat
            chain_note.init_chain_ref.index = init_head
            init_head = entity_index

    def get_beat(n):
        return n.beat

    def get_chain_next(n):
        return n.init_chain_ref

    if not beats_ascending:
        init_head = sort_linked_entities(
            note.WatchBaseNote.at(init_head).ref(), get_value=get_beat, get_next_ref=get_chain_next
        ).index

    init_index = init_head
    while init_index > 0:
        init_note = note.WatchBaseNote.at(init_index)
        init_note.init_data()
        init_index = init_note.init_chain_ref.index

    for i in range(entity_count):
        entity_index = entity_count - 1 - i
        info = entity_info_at(entity_index)
        mro = WatchArchetype._get_mro_id_array(info.archetype_id)
        is_note = note_id in mro
        is_skill = skill_id in mro
        if is_note:
            if note.WatchBaseNote.at(entity_index).is_scored:
                note.WatchBaseNote.at(entity_index).next_ref.index = note_head
                note_head = entity_index
                note_length += 1
        elif is_skill:
            Skill.at(entity_index).next_ref.index = skill_head
            skill_head = entity_index
            skill_length += 1

    return note_head, note_length, skill_head, skill_length


def setting_combo(head: int, skill: int) -> None:
    ptr = head
    skill_ptr = skill
    combo = 0
    count = 0
    fever_hits = 0
    ap = False
    prev_acc = 0
    prev_damage = 0
    current_note_weight = 0.0

    total_weight = +NeumaierSum

    while ptr > 0:
        if skill_ptr > 0 and note.WatchBaseNote.at(ptr).target_time >= Skill.at(skill_ptr).start_time:
            if Skill.at(skill_ptr).effect == SkillMode.HEAL:
                skill_ptr = Skill.at(skill_ptr).next_ref.index
            elif Skill.at(skill_ptr).effect == SkillMode.SCORE or Skill.at(skill_ptr).effect == SkillMode.JUDGMENT:
                if Skill.at(skill_ptr).effect == SkillMode.SCORE:
                    boost = Skill.at(skill_ptr).scale
                else:
                    boost = 1.0
                skill_end_time = Skill.at(skill_ptr).start_time + Skill.at(skill_ptr).duration
                if note.WatchBaseNote.at(ptr).target_time <= skill_end_time:
                    note.WatchBaseNote.at(ptr).entity_score_multiplier += boost * (
                        note.WatchBaseNote.at(ptr).archetype_score_multiplier
                        + note.WatchBaseNote.at(ptr).entity_score_multiplier
                    )
                else:
                    skill_ptr = Skill.at(skill_ptr).next_ref.index

        judgment = note.WatchBaseNote.at(ptr).judgment
        in_fever_window = Fever.fever_chance_time <= note.WatchBaseNote.at(ptr).target_time < Fever.fever_start_time
        if is_replay() and judgment in (Judgment.GOOD, Judgment.MISS):
            combo = 0
            if in_fever_window:
                Fever.fever_chance_cant_super_fever = True
        else:
            combo += 1
            if in_fever_window:
                fever_hits += 1
        note.WatchBaseNote.at(ptr).combo = combo
        note.WatchBaseNote.at(ptr).fever_hits = fever_hits

        if is_replay() and judgment != Judgment.PERFECT:
            ap = True
        if is_replay() and ap:
            note.WatchBaseNote.at(ptr).at(ptr).ap = True

        if is_replay() and judgment != Judgment.PERFECT and note.WatchBaseNote.at(ptr).played_hit_effects:
            if prev_acc > 0:
                custom_elements.JudgmentAccuracy.spawn(
                    note_index=prev_acc,
                    next_ref=note.WatchBaseNote.at(ptr).ref(),
                )
            prev_acc = ptr

        if is_replay() and judgment == Judgment.MISS:
            if prev_damage > 0:
                custom_elements.DamageFlash.spawn(
                    note_index=prev_damage,
                    next_ref=note.WatchBaseNote.at(ptr).ref(),
                )
            prev_damage = ptr

        count += 1
        note.WatchBaseNote.at(ptr).count = count
        if in_fever_window:
            Fever.fever_first_count = (
                min(note.WatchBaseNote.at(ptr).count, Fever.fever_first_count)
                if Fever.fever_first_count != 0
                else note.WatchBaseNote.at(ptr).count
            )
            Fever.fever_last_count = max(note.WatchBaseNote.at(ptr).count, Fever.fever_last_count)

        current_note_weight = level_score().perfect_multiplier * calculate_note_weight(
            perfect_step=count,
            great_step=count,
            good_step=count,
            archetype_multiplier=note.WatchBaseNote.at(ptr).archetype_score_multiplier,
            entity_multiplier=note.WatchBaseNote.at(ptr).entity_score_multiplier,
        )

        total_weight.add(current_note_weight)

        LastNote.last_time = max(LastNote.last_time, note.WatchBaseNote.at(ptr).calc_time)
        ptr = note.WatchBaseNote.at(ptr).next_ref.index

    if prev_acc > 0:
        custom_elements.JudgmentAccuracy.spawn(
            note_index=prev_acc,
            next_ref=+EntityRef[note.WatchBaseNote],
        )
    if prev_damage > 0:
        custom_elements.DamageFlash.spawn(
            note_index=prev_damage,
            next_ref=+EntityRef[note.WatchBaseNote],
        )

    calculate_score(head, 1000000, total_weight.total)


def schedule_auto_connector_sfx(entity_count: int):
    connector_id = WatchConnector._compile_time_id()

    normal_head = 0
    critical_head = 0
    for i in range(entity_count - 1, -1, -1):
        info = entity_info_at(i)
        mro = WatchArchetype._get_mro_id_array(info.archetype_id)
        if connector_id not in mro:
            continue
        connector = WatchConnector.at(i)
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
    act_ref = sort_linked_entities(WatchConnector.at(list_head).ref(), get_value=act_time, get_next_ref=act_next).index
    deact_ref = sort_linked_entities(
        WatchConnector.at(list_head).ref(), get_value=deact_time, get_next_ref=deact_next
    ).index

    # Two-pointer merge sweep through the activation/deactivation events in time order, reproducing
    # the original hold state machine exactly.
    current_time = -1e8
    active_time = CONNECTOR_SFX_ACTIVE_TIME_INIT
    inactive_time = CONNECTOR_SFX_INACTIVE_TIME_INIT
    active_connector_index = 0

    while act_ref > 0 or deact_ref > 0:
        next_time = 1e8
        if act_ref > 0:
            next_time = WatchConnector.at(act_ref).active_head.target_time
        if deact_ref > 0:
            deact_event_time = WatchConnector.at(deact_ref).active_tail.target_time
            next_time = min(next_time, deact_event_time)

        if active_time >= inactive_time and active_connector_index > 0:
            schedule_connector_sfx(
                sfx_kind,
                WatchConnector.at(active_connector_index).segment_head.timescale_group,
                current_time,
                next_time,
            )

        while act_ref > 0 and WatchConnector.at(act_ref).active_head.target_time == next_time:
            if inactive_time == CONNECTOR_SFX_INACTIVE_TIME_INIT:
                inactive_time = next_time
            active_time = next_time
            active_connector_index = act_ref
            act_ref = WatchConnector.at(act_ref).sfx_act_next.index

        while deact_ref > 0 and WatchConnector.at(deact_ref).active_tail.target_time == next_time:
            inactive_time = next_time
            deact_ref = WatchConnector.at(deact_ref).sfx_deact_next.index

        current_time = next_time

    if active_time >= inactive_time and active_connector_index > 0:
        schedule_connector_sfx(
            sfx_kind,
            WatchConnector.at(active_connector_index).segment_head.timescale_group,
            current_time,
            LastNote.last_time,
        )


def schedule_replay_connector_sfx(stream, kind: ActiveConnectorKind):
    last_times = inactive_connector_sfx_times()
    last_time = -1e8
    for next_time, next_times in stream.iter_items_from(-2):
        if connector_sfx_is_active(last_times):
            schedule_connector_sfx_between(kind, last_time, next_time)
        last_times @= next_times
        last_time = next_time
    if connector_sfx_is_active(last_times):
        schedule_connector_sfx_between(kind, last_time, LastNote.last_time)


def calculate_score(head: int, max_score: int, total_weight: float):
    ptr = head
    count = 0
    score = 0
    current_raw_score = +NeumaierSum
    acc_sum = +NeumaierSum
    processed_weight = +NeumaierSum
    perfect_step = 0
    great_step = 0
    good_step = 0
    total_weight = total_weight if total_weight > 0 else 1.0
    if Options.custom_score == 2:
        custom_elements.ScoreIndicator.percentage = 100
    custom_elements.ScoreIndicator.first = note.WatchBaseNote.at(head).calc_time
    while ptr > 0:
        count += 1
        # score = judgmentMultiplier * (consecutiveJudgmentMultiplier + archetypeMultiplier + entityMultiplier)
        judgment_multiplier = 0
        if is_replay():
            match note.WatchBaseNote.at(ptr).judgment:
                case Judgment.PERFECT:
                    judgment_multiplier = level_score().perfect_multiplier
                    perfect_step += 1
                    great_step += 1
                    good_step += 1
                case Judgment.GREAT:
                    judgment_multiplier = level_score().great_multiplier
                    perfect_step = 0
                    great_step += 1
                    good_step += 1
                case Judgment.GOOD:
                    judgment_multiplier = level_score().good_multiplier
                    perfect_step = 0
                    great_step = 0
                    good_step += 1
                case Judgment.MISS:
                    judgment_multiplier = 0
                    perfect_step = 0
                    great_step = 0
                    good_step = 0
        else:
            judgment_multiplier = level_score().perfect_multiplier
            perfect_step += 1
            great_step += 1
            good_step += 1

        inv_perfect_step = (
            1.0 / level_score().consecutive_perfect_step if level_score().consecutive_perfect_step > 0 else 0.0
        )
        inv_great_step = 1.0 / level_score().consecutive_great_step if level_score().consecutive_great_step > 0 else 0.0
        inv_good_step = 1.0 / level_score().consecutive_good_step if level_score().consecutive_good_step > 0 else 0.0
        note_raw_score = judgment_multiplier * (
            (
                min(
                    floor(perfect_step * inv_perfect_step + 1e-9) * level_score().consecutive_perfect_multiplier,
                    (level_score().consecutive_perfect_cap * inv_perfect_step)
                    * level_score().consecutive_perfect_multiplier,
                )
                + min(
                    floor(great_step * inv_great_step + 1e-9) * level_score().consecutive_great_multiplier,
                    (level_score().consecutive_great_cap * inv_great_step) * level_score().consecutive_great_multiplier,
                )
                + min(
                    floor(good_step * inv_good_step + 1e-9) * level_score().consecutive_good_multiplier,
                    (level_score().consecutive_good_cap * inv_good_step) * level_score().consecutive_good_multiplier,
                )
            )
            + note.WatchBaseNote.at(ptr).archetype_score_multiplier
            + note.WatchBaseNote.at(ptr).entity_score_multiplier
        )
        raw_calc = (note_raw_score * max_score) / total_weight
        note.WatchBaseNote.at(ptr).note_raw_score = raw_calc

        current_raw_score.add(note_raw_score)

        final_calc = (current_raw_score.total / total_weight) * max_score
        score = clamp(
            final_calc,
            0,
            max_score,
        )
        note.WatchBaseNote.at(ptr).score = score

        match Options.custom_score:
            case 1:
                note.WatchBaseNote.at(ptr).percentage = (current_raw_score.total / total_weight) * 100.0
            case 2:
                note_ideal_weight = level_score().perfect_multiplier * (
                    (
                        min(
                            floor(count * inv_perfect_step + 1e-9) * level_score().consecutive_perfect_multiplier,
                            (level_score().consecutive_perfect_cap * inv_perfect_step)
                            * level_score().consecutive_perfect_multiplier,
                        )
                        + min(
                            floor(count * inv_great_step + 1e-9) * level_score().consecutive_great_multiplier,
                            (level_score().consecutive_great_cap * inv_great_step)
                            * level_score().consecutive_great_multiplier,
                        )
                        + min(
                            floor(count * inv_good_step + 1e-9) * level_score().consecutive_good_multiplier,
                            (level_score().consecutive_good_cap * inv_good_step)
                            * level_score().consecutive_good_multiplier,
                        )
                    )
                    + note.WatchBaseNote.at(ptr).archetype_score_multiplier
                    + note.WatchBaseNote.at(ptr).entity_score_multiplier
                )
                processed_weight.add(note_ideal_weight)

                current_loss = processed_weight.total - current_raw_score.total
                current_visible_score = total_weight - current_loss
                percent = (current_visible_score / total_weight) * 100.0
                note.WatchBaseNote.at(ptr).percentage = clamp(percent, 0.0, 100.0)
            case 3:
                current_acc = (1 - abs(note.WatchBaseNote.at(ptr).accuracy)) * 100

                acc_sum.add(current_acc)

                note.WatchBaseNote.at(ptr).percentage = acc_sum.total / count

        ptr = note.WatchBaseNote.at(ptr).next_ref.index


def count_skill(head: int) -> None:
    ptr = head
    count = 0
    life = LifeManager.initial_life
    while ptr > 0:
        Skill.at(ptr).count = count
        count += 1
        if Skill.at(ptr).effect == SkillMode.HEAL:
            add_life_scheduled(Skill.at(ptr).value * LifeManager.scale, Skill.at(ptr).start_time)
            life = clamp(life + Skill.at(ptr).value * LifeManager.scale, 0, LifeManager.max_life)
        Skill.at(ptr).current_life = life
        ptr = Skill.at(ptr).next_ref.index


def calculate_replay_life(note_head: int, skill_head: int) -> None:
    life = 1.0 * LifeManager.initial_life
    first_event_time = 1e8
    note_ptr = note_head
    skill_ptr = skill_head
    while note_ptr > 0 or skill_ptr > 0:
        note_time = note.WatchBaseNote.at(note_ptr).calc_time if note_ptr > 0 else 1e8
        skill_time = Skill.at(skill_ptr).start_time if skill_ptr > 0 else 1e8
        if skill_ptr > 0 and skill_time <= note_time:
            current_skill = Skill.at(skill_ptr)
            if current_skill.effect == SkillMode.HEAL:
                first_event_time = min(first_event_time, skill_time)
                if life > 0:
                    life = clamp(life + current_skill.value * LifeManager.scale, 0, LifeManager.max_life)
            current_skill.current_life = life
            current_skill.next_note_time = note_time
            skill_ptr = current_skill.next_ref.index
        else:
            current_note = note.WatchBaseNote.at(note_ptr)
            first_event_time = min(first_event_time, note_time)
            if life > 0:
                match current_note.judgment:
                    case Judgment.PERFECT:
                        life += (
                            current_note.archetype_life.perfect_increment + current_note.entity_life.perfect_increment
                        )
                    case Judgment.GREAT:
                        life += current_note.archetype_life.great_increment + current_note.entity_life.great_increment
                    case Judgment.GOOD:
                        life += current_note.archetype_life.good_increment + current_note.entity_life.good_increment
                    case Judgment.MISS:
                        life += current_note.archetype_life.miss_increment + current_note.entity_life.miss_increment
                life = clamp(life, 0, LifeManager.max_life)
            current_note.replay_life = life
            note_ptr = current_note.next_ref.index
    LifeManager.first = first_event_time
