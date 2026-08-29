from __future__ import annotations

from sonolus.script.archetype import PlayArchetype, callback
from sonolus.script.array import Array, Dim
from sonolus.script.containers import ArrayMap, ArraySet, VarArray
from sonolus.script.globals import level_memory
from sonolus.script.interval import clamp
from sonolus.script.iterator import maybe_next
from sonolus.script.runtime import Touch, screen, time, touches

from sekai.lib import archetype_names
from sekai.lib.buckets import SLIDE_END_LOCKOUT_DURATION
from sekai.lib.layout import DynamicLayout, Layout, segment_closeness_score, stage_aspect_ratio_locked
from sekai.lib.note import is_head
from sekai.lib.options import Options
from sekai.play import note

INPUT_SLOTS = 16
INPUT_SCORE_TIME_SCALE = 0.05


@level_memory
class InputState:
    processed_touches: VarArray[Touch, Dim[32]]
    disallowed_empty_touches: ArraySet[int, Dim[32]]
    disallowed_release_touches: ArrayMap[int, float, Dim[32]]


def preprocess_touches():
    result = InputState.processed_touches
    result.clear()

    should_correct = Options.edge_touch_correction and stage_aspect_ratio_locked()
    field_bottom = screen().center.y - Layout.field_h / 2
    field_top = screen().center.y + Layout.field_h / 2

    for raw_touch in touches():
        if result.is_full():
            break

        touch = +raw_touch
        if should_correct:
            prev_position = raw_touch.prev_position
            touch.position.y = clamp(raw_touch.position.y, field_bottom, field_top)
            touch.start_position.y = clamp(raw_touch.start_position.y, field_bottom, field_top)
            touch.delta.y = touch.position.y - clamp(prev_position.y, field_bottom, field_top)
        result.append(touch)


def processed_touches() -> VarArray[Touch, Dim[32]]:
    return InputState.processed_touches


def disallow_empty(touch: Touch):
    InputState.disallowed_empty_touches.add(touch.id)


def disallow_release(touch: Touch, until_time: float):
    if touch.id in InputState.disallowed_release_touches:
        until_time = max(InputState.disallowed_release_touches[touch.id], until_time)
    InputState.disallowed_release_touches[touch.id] = until_time


def is_allowed_empty(touch: Touch) -> bool:
    return touch.id not in InputState.disallowed_empty_touches


def is_allowed_release(touch: Touch, target_time: float) -> bool:
    if touch.id not in InputState.disallowed_release_touches:
        return True
    return InputState.disallowed_release_touches[touch.id] <= target_time


class InputManager(PlayArchetype):
    name = archetype_names.INPUT_MANAGER

    @callback(order=-3)
    def update_sequential(self):
        preprocess_touches()
        note.NoteMemory.active_tap_input_notes.clear()
        note.NoteMemory.active_release_input_notes.clear()

    @callback(order=-1)
    def touch(self):
        update_input_state()
        preassign_taps()
        preassign_releases()


def update_input_state():
    old_disallowed_empty_touches = +InputState.disallowed_empty_touches
    InputState.disallowed_empty_touches.clear()
    for existing_id in old_disallowed_empty_touches:
        maybe_touch = maybe_next(touch for touch in processed_touches() if touch.id == existing_id)
        if maybe_touch.is_nothing:
            continue
        touch = maybe_touch.get()
        disallow_empty(touch)

    old_disallowed_release_touches = +InputState.disallowed_release_touches
    InputState.disallowed_release_touches.clear()
    for existing_id, until_time in old_disallowed_release_touches.items():
        maybe_touch = maybe_next(touch for touch in processed_touches() if touch.id == existing_id)
        if maybe_touch.is_nothing:
            continue
        touch = maybe_touch.get()
        InputState.disallowed_release_touches[touch.id] = until_time


def preassign_taps():
    active = note.NoteMemory.active_tap_input_notes
    active.sort(key=lambda ref: ref.get().target_time)

    input_assigned = +Array[bool, Dim[INPUT_SLOTS]]
    for i in range(INPUT_SLOTS):
        if i >= len(processed_touches()) or not processed_touches()[i].started:
            input_assigned[i] = True

    scores = +Array[float, Dim[INPUT_SLOTS]]
    preferred = +Array[int, Dim[INPUT_SLOTS]]

    for _ in range(INPUT_SLOTS):
        for i in range(INPUT_SLOTS):
            scores[i] = 0.0
            preferred[i] = -1

        for i in range(INPUT_SLOTS):
            if input_assigned[i]:
                continue
            touch = processed_touches()[i]
            for note_i in range(len(active)):
                target_note = active[note_i].get()
                if target_note.captured_touch_id != 0:
                    continue
                if not target_note.hitbox.bounds.contains_point(touch.position):
                    continue
                if touch.time not in target_note.unadjusted_input_interval:
                    continue
                score = (
                    segment_closeness_score(touch.position, target_note.hitbox.target) / DynamicLayout.w_scale
                    + (time() - target_note.target_time) / INPUT_SCORE_TIME_SCALE
                )
                if preferred[i] == -1 or score > scores[i]:
                    scores[i] = score
                    preferred[i] = note_i

        any_assigned = False
        for i in range(INPUT_SLOTS):
            note_i = preferred[i]
            if note_i < 0:
                continue
            is_best = True
            for j in range(INPUT_SLOTS):
                if j == i or preferred[j] != note_i:
                    continue
                if scores[j] > scores[i] or (scores[j] == scores[i] and j < i):
                    is_best = False
                    break
            if not is_best:
                continue
            target_note = active[note_i].get()
            touch = processed_touches()[i]
            disallow_empty(touch)
            if not is_head(target_note.kind):
                disallow_release(touch, target_note.target_time + SLIDE_END_LOCKOUT_DURATION)
            target_note.captured_touch_id = touch.id
            target_note.captured_touch_time = min(touch.time, touch.start_time)
            input_assigned[i] = True
            any_assigned = True

        if not any_assigned:
            break


def preassign_releases():
    active = note.NoteMemory.active_release_input_notes
    active.sort(key=lambda ref: ref.get().target_time)

    input_assigned = +Array[bool, Dim[INPUT_SLOTS]]
    for i in range(INPUT_SLOTS):
        if i >= len(processed_touches()) or not processed_touches()[i].ended:
            input_assigned[i] = True

    scores = +Array[float, Dim[INPUT_SLOTS]]
    preferred = +Array[int, Dim[INPUT_SLOTS]]

    for _ in range(INPUT_SLOTS):
        for i in range(INPUT_SLOTS):
            scores[i] = 0.0
            preferred[i] = -1

        for i in range(INPUT_SLOTS):
            if input_assigned[i]:
                continue
            touch = processed_touches()[i]
            for note_i in range(len(active)):
                target_note = active[note_i].get()
                if target_note.captured_touch_id != 0:
                    continue
                if not target_note.hitbox.bounds.contains_point(touch.position):
                    continue
                if touch.time not in target_note.unadjusted_input_interval:
                    continue
                ignore_lockout = False
                if target_note.active_head_ref.index > 0:
                    head_bounds = target_note.active_head_ref.get().active_connector_info.input_bounds
                    ongoing = False
                    for t in processed_touches():
                        if not t.ended and head_bounds.contains_point(t.position):
                            ongoing = True
                            break
                    ignore_lockout = not ongoing
                if not ignore_lockout and not is_allowed_release(touch, target_note.target_time):
                    continue
                score = (
                    segment_closeness_score(touch.position, target_note.hitbox.target) / DynamicLayout.w_scale
                    + (time() - target_note.target_time) / INPUT_SCORE_TIME_SCALE
                )
                if preferred[i] == -1 or score > scores[i]:
                    scores[i] = score
                    preferred[i] = note_i

        any_assigned = False
        for i in range(INPUT_SLOTS):
            note_i = preferred[i]
            if note_i < 0:
                continue
            is_best = True
            for j in range(INPUT_SLOTS):
                if j == i or preferred[j] != note_i:
                    continue
                if scores[j] > scores[i] or (scores[j] == scores[i] and j < i):
                    is_best = False
                    break
            if not is_best:
                continue
            target_note = active[note_i].get()
            touch = processed_touches()[i]
            disallow_empty(touch)
            target_note.captured_touch_id = touch.id
            target_note.captured_touch_time = touch.time
            input_assigned[i] = True
            any_assigned = True

        if not any_assigned:
            break
