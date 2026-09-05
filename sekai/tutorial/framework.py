from __future__ import annotations

from math import floor
from typing import Self

from sonolus.script.array import Array, Dim
from sonolus.script.bucket import Judgment
from sonolus.script.containers import VarArray
from sonolus.script.effect import LoopedEffectHandle
from sonolus.script.globals import level_memory
from sonolus.script.instruction import clear_instruction
from sonolus.script.interval import lerp, remap, remap_clamped, unlerp
from sonolus.script.particle import ParticleHandle
from sonolus.script.record import Record
from sonolus.script.runtime import set_particle_transform, set_skin_transform, time
from sonolus.script.transform import Transform2d
from sonolus.script.vec import Vec2

from sekai.lib.connector import (
    CONNECTOR_SLOT_SPAWN_PERIOD,
    CONNECTOR_TRAIL_SPAWN_PERIOD,
    ConnectorKind,
    ConnectorLayer,
    ConnectorVisualState,
    SegmentPresentation,
    destroy_looped_particle,
    destroy_looped_sfx,
    draw_connector,
    draw_connector_slot_glow_effect,
    spawn_connector_slot_particles,
    spawn_linear_connector_trail_particle,
    update_circular_connector_particle,
    update_connector_sfx,
    update_linear_connector_particle,
)
from sekai.lib.ease import EaseType, ease
from sekai.lib.layout import IDENTITY_AFFINE_TRANSFORM, FlickDirection, transformed_vec_at
from sekai.lib.note import (
    NoteKind,
    draw_note,
    draw_slide_note_head,
    draw_tutorial_note_slot_effects,
    get_note_effect_kind,
    play_note_hit_effects,
)
from sekai.lib.stage import draw_basic_stage
from sekai.tutorial.painting import paint_hold_motion


class SlideEffectHandles(Record):
    linear: ParticleHandle
    circular: ParticleHandle
    sfx: LoopedEffectHandle
    next_trail_spawn_time: float
    next_slot_spawn_time: float

    def destroy(self):
        destroy_looped_particle(self.linear)
        destroy_looped_particle(self.circular)
        destroy_looped_sfx(self.sfx)
        self.next_trail_spawn_time = 0
        self.next_slot_spawn_time = 0


def update_start():
    PhaseState.slide_is_active = False
    clear_instruction()
    draw_basic_stage()
    reset_zoom()


def update_end():
    PhaseState.prev_time = time()
    # For engine size and compile performance reasons, we queue up actions, then
    # execute them at the end of the frame.
    # This means that the body of the act() methods are only compiled once due to
    # how the compiler inlines all function calls.
    for action_group in (
        PhaseState.queued_note_draws,
        PhaseState.queued_note_hit_effects,
        PhaseState.queued_note_slot_effects,
        PhaseState.queued_connector_draws,
    ):
        for action in action_group:
            action.act()
        action_group.clear()
    if not PhaseState.slide_is_active:
        for handles in PhaseState.slide_handles:
            handles.destroy()


def reset_phase():
    PhaseState.start_time = time()
    for handles in PhaseState.slide_handles:
        handles.destroy()


def get_slide_effect_handles(index: int) -> SlideEffectHandles:
    PhaseState.slide_is_active = True
    return PhaseState.slide_handles[index]


def current_phase_time() -> PhaseTime:
    """Return the current phase timing information."""
    return PhaseTime(time() - PhaseState.start_time, PhaseState.prev_time - PhaseState.start_time)


def phase_time_to_time(phase_time: float) -> float:
    return phase_time + PhaseState.start_time


class PhaseTime(Record):
    time: float
    prev_time: float

    def range(self, start: float, end: float, segments: int = 1) -> PhaseRange:
        return PhaseRange(self, start, end, segments)

    def first(self, end: float, repeats: int = 1) -> PhaseRange:
        return self.range(0, end * repeats, segments=repeats)

    def instant(self, timing: float) -> PhaseInstant:
        return PhaseInstant(self, timing)


class PhaseRange(Record):
    phase: PhaseTime
    start: float
    end: float
    segments: int

    @property
    def is_active(self):
        return self.start <= self.phase.time < self.end

    @property
    def progress(self) -> float:
        if self.segments == 1:
            return remap(self.start, self.end, 0, 1, self.phase.time)
        else:
            return remap_clamped(self.start, self.end, 0, 1, self.phase.time) * self.segments % 1

    @property
    def current_segment(self) -> int:
        return floor(remap_clamped(self.start, self.end, 0, self.segments, self.phase.time))

    @property
    def is_done(self):
        return self.phase.time >= self.end

    @property
    def time_since_start(self) -> float:
        return self.phase.time - self.start

    def next(self, duration: float, repeats: int = 1):
        return self.phase.range(self.end, self.end + duration * repeats, segments=repeats)

    def start_instant(self) -> PhaseInstant:
        return self.phase.instant(self.start)

    def end_instant(self) -> PhaseInstant:
        return self.phase.instant(self.end)

    def __bool__(self):
        return self.is_active


class PhaseInstant(Record):
    phase: PhaseTime
    timing: float

    @property
    def is_active(self):
        return self.phase.prev_time < self.timing <= self.phase.time

    @property
    def is_done(self):
        return self.phase.time >= self.timing and not self.is_active

    @property
    def is_upcoming(self):
        return self.phase.time < self.timing

    def __bool__(self):
        return self.is_active


def zoom_to(pos: Vec2):
    transform = Transform2d.new().translate(-pos).scale(Vec2(1.7, 1.7))
    set_skin_transform(transform)
    set_particle_transform(transform)


def zoom_for_intro():
    zoom_to(transformed_vec_at(0, 0.78))


def reset_zoom():
    transform = Transform2d.new()
    set_skin_transform(transform)
    set_particle_transform(transform)


class TutorialNoteInfo(Record):
    kind: NoteKind
    lane: float
    size: float
    direction: FlickDirection
    offset: float

    @classmethod
    def of(
        cls,
        kind: NoteKind,
        lane: float,
        size: float,
        direction: FlickDirection = FlickDirection.UP_OMNI,
        offset: float = 0,
    ) -> Self:
        return cls(kind=kind, lane=lane, size=size, direction=direction, offset=offset)  # type: ignore

    def draw(self, progress: float = 1):
        PhaseState.queued_note_draws.append(QueuedTutorialNoteDraw(note=self, progress=progress))

    def play_hit_effects(self):
        PhaseState.queued_note_hit_effects.append(QueuedTutorialNotePlayHitEffects(note=self))

    def draw_slot_effects(self, end_range: PhaseRange):
        PhaseState.queued_note_slot_effects.append(QueuedTutorialNoteDrawSlotEffects(note=self, end_range=end_range))

    def draw_connector_to(
        self,
        other: TutorialNoteInfo,
        critical: bool,
        active: bool,
        progress: float = 1,
        active_head_kind: NoteKind = NoteKind.ANCHOR,
        ease_type: EaseType = EaseType.OUT_QUAD,
        show_touch: bool = False,
        effect_index: int = -1,
    ):
        PhaseState.queued_connector_draws.append(
            QueuedTutorialNoteDrawConnectorTo(
                from_note=self,
                to_note=other,
                critical=critical,
                active=active,
                progress=progress,
                active_head_kind=active_head_kind,
                ease_type=ease_type,
                show_touch=show_touch,
                effect_index=effect_index,
            )
        )


class QueuedTutorialNoteDraw(Record):
    note: TutorialNoteInfo
    progress: float

    def act(self):
        draw_note(
            kind=self.note.kind,
            lane=self.note.lane,
            size=self.note.size,
            visual_progress=self.progress + self.note.offset,
            direction=self.note.direction,
            target_time=time() + 1 - self.progress - self.note.offset,
            transform=IDENTITY_AFFINE_TRANSFORM,
            note_alpha=1.0,
        )


class QueuedTutorialNotePlayHitEffects(Record):
    note: TutorialNoteInfo

    def act(self):
        play_note_hit_effects(
            kind=self.note.kind,
            effect_kind=get_note_effect_kind(self.note.kind),
            lane=self.note.lane,
            size=self.note.size,
            direction=self.note.direction,
            judgment=Judgment.PERFECT,
            transform=IDENTITY_AFFINE_TRANSFORM,
        )


class QueuedTutorialNoteDrawSlotEffects(Record):
    note: TutorialNoteInfo
    end_range: PhaseRange

    def act(self):
        draw_tutorial_note_slot_effects(
            kind=self.note.kind,
            lane=self.note.lane,
            size=self.note.size,
            start_time=phase_time_to_time(self.end_range.start),
            direction=self.note.direction,
        )


class QueuedTutorialNoteDrawConnectorTo(Record):
    from_note: TutorialNoteInfo
    to_note: TutorialNoteInfo
    critical: bool
    active: bool
    progress: float
    active_head_kind: NoteKind
    ease_type: EaseType
    show_touch: bool
    effect_index: int

    def act(self):
        kind = ConnectorKind.ACTIVE_CRITICAL if self.critical else ConnectorKind.ACTIVE_NORMAL
        visual_state = ConnectorVisualState.ACTIVE if self.active else ConnectorVisualState.WAITING
        head_progress = self.progress + self.from_note.offset
        head_target_time = time() + 1 - self.progress - self.from_note.offset
        tail_progress = self.progress + self.to_note.offset
        tail_target_time = time() + 1 - self.progress - self.to_note.offset
        draw_connector(
            kind=kind,
            visual_state=visual_state,
            ease_type=self.ease_type,
            head_lane=self.from_note.lane,
            head_size=self.from_note.size,
            head_visual_progress=head_progress,
            head_target_time=head_target_time,
            head_ease_frac=0.0,
            tail_lane=self.to_note.lane,
            tail_size=self.to_note.size,
            tail_visual_progress=tail_progress,
            tail_target_time=tail_target_time,
            tail_ease_frac=1.0,
            segment_head_target_time=head_target_time,
            segment_head_lane=self.from_note.lane,
            segment_head_alpha=1,
            segment_tail_target_time=tail_target_time,
            segment_tail_alpha=1,
            layer=ConnectorLayer.TOP,
            presentation=SegmentPresentation.DEFAULT,
            bypass_tail_target_time_check=False,
            head_transform=None,
            tail_transform=None,
            head_note_alpha=1.0,
            tail_note_alpha=1.0,
            head_mask=None,
            tail_mask=None,
        )
        if self.effect_index >= 0 and tail_progress < 1 < head_progress and self.active:
            frac = unlerp(head_progress, tail_progress, 1)
            eased_frac = ease(self.ease_type, frac)
            lane = lerp(self.from_note.lane, self.to_note.lane, eased_frac)
            size = lerp(self.from_note.size, self.to_note.size, eased_frac)
            handles = get_slide_effect_handles(self.effect_index)
            update_circular_connector_particle(
                handles.circular,
                kind,
                lane,
                replace=False,
                transform=IDENTITY_AFFINE_TRANSFORM,
            )
            update_linear_connector_particle(
                handles.linear,
                kind,
                lane,
                replace=False,
                transform=IDENTITY_AFFINE_TRANSFORM,
            )
            if time() >= handles.next_trail_spawn_time:
                handles.next_trail_spawn_time = max(
                    handles.next_trail_spawn_time + CONNECTOR_TRAIL_SPAWN_PERIOD,
                    time() + CONNECTOR_TRAIL_SPAWN_PERIOD / 2,
                )
                spawn_linear_connector_trail_particle(kind, lane, transform=IDENTITY_AFFINE_TRANSFORM)
            if time() >= handles.next_slot_spawn_time:
                handles.next_slot_spawn_time = max(
                    handles.next_slot_spawn_time + CONNECTOR_SLOT_SPAWN_PERIOD,
                    time() + CONNECTOR_SLOT_SPAWN_PERIOD / 2,
                )
                spawn_connector_slot_particles(kind, lane, size, transform=IDENTITY_AFFINE_TRANSFORM)
            update_connector_sfx(
                handles.sfx,
                kind,
                replace=False,
            )
            draw_connector_slot_glow_effect(kind, head_target_time, lane, size, transform=IDENTITY_AFFINE_TRANSFORM)
            draw_slide_note_head(
                self.active_head_kind,
                kind,
                lane,
                size,
                head_target_time,
                transform=IDENTITY_AFFINE_TRANSFORM,
                note_alpha=1.0,
            )
            if self.show_touch:
                paint_hold_motion(transformed_vec_at(lane))


@level_memory
class PhaseState:
    start_time: float
    slide_handles: Array[SlideEffectHandles, Dim[8]]
    slide_is_active: bool
    prev_time: float

    queued_note_draws: VarArray[QueuedTutorialNoteDraw, Dim[8]]
    queued_note_hit_effects: VarArray[QueuedTutorialNotePlayHitEffects, Dim[8]]
    queued_note_slot_effects: VarArray[QueuedTutorialNoteDrawSlotEffects, Dim[8]]
    queued_connector_draws: VarArray[QueuedTutorialNoteDrawConnectorTo, Dim[8]]
