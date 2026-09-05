from __future__ import annotations

import itertools
import math
import struct
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import cast

from sonolus.build.collection import Asset
from sonolus.script.archetype import PlayArchetype
from sonolus.script.level import Level, LevelData
from sonolus.script.timing import TimescaleEase

from sekai.lib.connector import ConnectorKind, ConnectorLayer, SegmentPresentation
from sekai.lib.ease import EaseType
from sekai.lib.layout import FlickDirection, StageTransformAnchor, ZoomVerticalAlign
from sekai.lib.level_config import EngineRevision
from sekai.lib.note import NoteKind
from sekai.lib.stage import DivisionParity, JudgeLineColor, JudgeLineStyle, StageBorderStyle
from sekai.play.bpm_change import BpmChange
from sekai.play.connector import Connector
from sekai.play.dynamic_stage import (
    CameraChange,
    DynamicStage,
    StageMaskChange,
    StagePivotChange,
    StageStyleChange,
    StageTransformChange,
)
from sekai.play.events import FeverChance, FeverStart, Skill
from sekai.play.initialization import Initialization
from sekai.play.note import NOTE_ARCHETYPES, BaseNote
from sekai.play.sim_line import SimLine
from sekai.play.timescale import TimescaleChange, TimescaleGroup


def _build_note_archetype_lookup() -> dict[tuple[NoteKind, bool], type[PlayArchetype]]:
    lookup: dict[tuple[NoteKind, bool], type[PlayArchetype]] = {}
    for archetype in NOTE_ARCHETYPES:
        is_fake = str(archetype.name).startswith("Fake")
        lookup[(cast(NoteKind, archetype.key), is_fake)] = archetype
    return lookup


_NOTE_ARCHETYPE_BY_KIND = _build_note_archetype_lookup()

_SIM_LINE_EXCLUDED_KINDS = frozenset(
    {NoteKind.ANCHOR, NoteKind.NORM_TICK, NoteKind.CRIT_TICK, NoteKind.HIDE_TICK, NoteKind.HIDE_DAMAGE_TICK}
)

_ACTIVE_HOLD_SEGMENT_KINDS = frozenset(
    {
        ConnectorKind.ACTIVE_NORMAL,
        ConnectorKind.ACTIVE_CRITICAL,
        ConnectorKind.ACTIVE_FAKE_NORMAL,
        ConnectorKind.ACTIVE_FAKE_CRITICAL,
    }
)

# Segment kinds whose connectors track touches through their section's active head/tail refs.
_INPUT_TRACKED_SEGMENT_KINDS = _ACTIVE_HOLD_SEGMENT_KINDS | {ConnectorKind.DAMAGE}

_DAMAGE_TICK_STEP = 0.5
_BEAT_EPSILON = 1e-6


def _build_silent_wav(duration_seconds: float = 60.0, sample_rate: int = 8000) -> bytes:
    num_samples = int(duration_seconds * sample_rate)
    data_size = num_samples  # 1 channel, 8-bit
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + data_size,
        b"WAVE",
        b"fmt ",
        16,
        1,  # PCM
        1,  # channels
        sample_rate,
        sample_rate,  # byte rate = sample_rate * channels * bits/8
        1,  # block align
        8,  # bits per sample
        b"data",
        data_size,
    )
    return header + b"\x80" * data_size


@dataclass
class LevelBpmChange:
    beat: float
    bpm: float


@dataclass
class LevelTimescaleChange:
    beat: float
    timescale: float
    timescale_skip: float = 0.0
    timescale_ease: TimescaleEase = TimescaleEase.NONE
    hide_notes: bool = False


@dataclass
class LevelTimescaleGroup:
    changes: list[LevelTimescaleChange] = field(default_factory=list)
    force_note_speed: float = 0.0


@dataclass
class LevelStageMaskChange:
    beat: float
    lane: float
    size: float
    ease: EaseType = EaseType.LINEAR
    mask_notes: bool = False


@dataclass
class LevelStagePivotChange:
    beat: float
    lane: float
    division_size: float
    division_parity: DivisionParity
    abs_y_offset: float
    y_beat_offset: float
    ease: EaseType = EaseType.LINEAR


@dataclass
class LevelStageStyleChange:
    beat: float
    judge_line_color: JudgeLineColor
    left_border_style: StageBorderStyle
    right_border_style: StageBorderStyle
    lane_alpha: float
    judge_line_alpha: float
    judge_line_style: JudgeLineStyle = JudgeLineStyle.DEFAULT
    full_width: bool = False
    alpha: float = 1.0  # Deprecated
    division_line_alpha: float = 1.0
    note_alpha: float = 1.0
    ease: EaseType = EaseType.LINEAR


@dataclass
class LevelStageTransformChange:
    beat: float
    rotate: float = 0.0
    x_lane_translate: float = 0.0
    y_lane_translate: float = 0.0
    anchor: StageTransformAnchor = StageTransformAnchor.DEFAULT
    ease: EaseType = EaseType.LINEAR


@dataclass
class LevelStage:
    from_start: bool = False
    until_end: bool = False
    mask_changes: list[LevelStageMaskChange] = field(default_factory=list)
    pivot_changes: list[LevelStagePivotChange] = field(default_factory=list)
    style_changes: list[LevelStageStyleChange] = field(default_factory=list)
    transform_changes: list[LevelStageTransformChange] = field(default_factory=list)


@dataclass
class LevelCameraChange:
    beat: float
    lane: float = 0.0
    size: float = 6.0
    zoom: float = 1.0
    zoom_target_lane: float = 0.0
    zoom_target_y: float = 0.0
    zoom_vertical_align: ZoomVerticalAlign = ZoomVerticalAlign.DEFAULT
    rotate: float = 0.0
    stage_tilt: float = 1.0
    ease: EaseType = EaseType.LINEAR


@dataclass
class LevelNote:
    beat: float
    lane: float
    size: float
    kind: NoteKind
    timescale_group: LevelTimescaleGroup | None = None
    stage: LevelStage | None = None
    direction: FlickDirection = FlickDirection.UP_OMNI
    is_fake: bool = False
    is_separator: bool = False
    segment_kind: ConnectorKind = ConnectorKind.NONE
    segment_alpha: float = 1.0
    segment_layer: ConnectorLayer = ConnectorLayer.TOP
    segment_through_judge_line: bool = False
    segment_presentation: SegmentPresentation = SegmentPresentation.DEFAULT
    connector_ease: EaseType = EaseType.LINEAR
    attach: LevelSlide | None = None


@dataclass
class LevelSlide:
    notes: list[LevelNote] = field(default_factory=list)


@dataclass
class LevelFeverChance:
    beat: float
    force: bool = False


@dataclass
class LevelFeverStart:
    beat: float


@dataclass
class LevelSkill:
    beat: float
    effect: int
    level: int = 1
    value: int = 250
    scale: float = 1.0
    duration: float = 6


type LevelEntities = (
    LevelBpmChange
    | LevelTimescaleGroup
    | LevelNote
    | LevelSlide
    | LevelStage
    | LevelCameraChange
    | LevelFeverChance
    | LevelFeverStart
    | LevelSkill
)


def _note_archetype_for(kind: NoteKind, is_fake: bool) -> type[PlayArchetype]:
    key = (kind, is_fake)
    if key not in _NOTE_ARCHETYPE_BY_KIND and is_fake:
        key = (kind, False)
    return _NOTE_ARCHETYPE_BY_KIND[key]


def build_level(
    name: str,
    title: str,
    bgm: Asset | None,
    entities: list[LevelEntities],
) -> Level:
    bpm_changes: list[LevelBpmChange] = []
    level_ts_groups: list[LevelTimescaleGroup] = []
    level_stages: list[LevelStage] = []
    level_camera_changes: list[LevelCameraChange] = []
    top_notes: list[LevelNote] = []
    slides: list[LevelSlide] = []
    event_entities: list[PlayArchetype] = []

    for entity in entities:
        if isinstance(entity, LevelBpmChange):
            bpm_changes.append(entity)
        elif isinstance(entity, LevelTimescaleGroup):
            level_ts_groups.append(entity)
        elif isinstance(entity, LevelStage):
            level_stages.append(entity)
        elif isinstance(entity, LevelCameraChange):
            level_camera_changes.append(entity)
        elif isinstance(entity, LevelNote):
            top_notes.append(entity)
        elif isinstance(entity, LevelSlide):
            slides.append(entity)
        elif isinstance(entity, LevelFeverChance):
            event_entities.append(FeverChance(beat=entity.beat, force=entity.force))
        elif isinstance(entity, LevelFeverStart):
            event_entities.append(FeverStart(beat=entity.beat))
        elif isinstance(entity, LevelSkill):
            event_entities.append(
                Skill(
                    beat=entity.beat,
                    effect=entity.effect,
                    level=entity.level,
                    value=entity.value,
                    scale=entity.scale,
                    duration=entity.duration,
                )
            )
        elif not isinstance(
            entity, (LevelBpmChange, LevelTimescaleGroup, LevelStage, LevelCameraChange, LevelNote, LevelSlide)
        ):
            raise TypeError(f"Unsupported level entity: {type(entity).__name__}")

    out_entities: list[PlayArchetype] = []

    default_ts_group: TimescaleGroup | None = None
    ts_group_map: dict[int, TimescaleGroup] = {}
    for level_group in level_ts_groups:
        group, group_entities = _build_timescale_group(level_group)
        ts_group_map[id(level_group)] = group
        out_entities.extend(group_entities)

    def resolve_ts_group(level_group: LevelTimescaleGroup | None) -> TimescaleGroup:
        nonlocal default_ts_group
        if level_group is not None:
            return ts_group_map[id(level_group)]
        if default_ts_group is None:
            default_level_group = LevelTimescaleGroup(changes=[LevelTimescaleChange(beat=0.0, timescale=1.0)])
            default_ts_group, group_entities = _build_timescale_group(default_level_group)
            out_entities.extend(group_entities)
        return default_ts_group

    stage_map: dict[int, DynamicStage] = {}
    for level_stage in level_stages:
        stage, stage_entities = _build_stage(level_stage)
        stage_map[id(level_stage)] = stage
        out_entities.extend(stage_entities)

    first_camera = _build_camera_changes(level_camera_changes, out_entities)

    note_entities: list[BaseNote] = []
    slide_non_attached: dict[int, list[BaseNote]] = {}

    def emit_note(level_note: LevelNote, force_separator: bool = False) -> BaseNote:
        ts_group = resolve_ts_group(level_note.timescale_group)
        archetype_cls = _note_archetype_for(level_note.kind, level_note.is_fake)
        kwargs: dict[str, object] = {
            "beat": level_note.beat,
            "lane": level_note.lane,
            "size": level_note.size,
            "direction": level_note.direction,
            "connector_ease": level_note.connector_ease,
            "is_separator": level_note.is_separator or force_separator,
            "segment_kind": level_note.segment_kind,
            "segment_alpha": level_note.segment_alpha,
            "segment_layer": level_note.segment_layer,
            "segment_through_judge_line": level_note.segment_through_judge_line,
            "segment_presentation": level_note.segment_presentation,
            "timescale_group": ts_group.ref(),
        }
        if level_note.stage is not None:
            kwargs["stage_ref"] = stage_map[id(level_note.stage)].ref()
        note = cast(BaseNote, archetype_cls(**kwargs))
        note_entities.append(note)
        out_entities.append(note)
        return note

    pending_attachments: list[tuple[BaseNote, LevelSlide]] = []

    for level_note in top_notes:
        note = emit_note(level_note)
        if level_note.attach is not None:
            pending_attachments.append((note, level_note.attach))

    for slide in slides:
        if len(slide.notes) < 2:
            raise ValueError("LevelSlide must contain at least two notes")
        last_index = len(slide.notes) - 1
        built: list[BaseNote] = []
        non_attached: list[BaseNote] = []
        for i, ln in enumerate(slide.notes):
            is_endpoint = i in (0, last_index)
            note = emit_note(ln, force_separator=is_endpoint)
            built.append(note)
            if ln.attach is None:
                non_attached.append(note)
            else:
                pending_attachments.append((note, ln.attach))

        for prev_note, next_note in itertools.pairwise(non_attached):
            prev_note.next_ref = next_note.ref()
        slide_non_attached[id(slide)] = non_attached

        separator_indices = sorted(i for i, ln in enumerate(slide.notes) if i in (0, last_index) or ln.is_separator)
        separator_index_set = set(separator_indices)
        section_by_span_head = _input_section_bounds(slide.notes, separator_indices)
        boundary_indices = [i for i, ln in enumerate(slide.notes) if i in separator_index_set or ln.attach is None]
        for a, b in itertools.pairwise(boundary_indices):
            seg_kind = slide.notes[a].segment_kind
            if seg_kind == ConnectorKind.NONE:
                continue
            seg_head_idx = a if a in separator_index_set else max(s for s in separator_indices if s < a)
            seg_tail_idx = b if b in separator_index_set else min(s for s in separator_indices if s > b)
            seg_head = built[seg_head_idx]
            seg_tail = built[seg_tail_idx]
            connector = Connector(
                head_ref=built[a].ref(),
                tail_ref=built[b].ref(),
                segment_head_ref=seg_head.ref(),
                segment_tail_ref=seg_tail.ref(),
            )
            if seg_kind in _INPUT_TRACKED_SEGMENT_KINDS:
                section_head_idx, section_tail_idx = section_by_span_head[seg_head_idx]
                connector.active_head_ref = built[section_head_idx].ref()
                connector.active_tail_ref = built[section_tail_idx].ref()
            out_entities.append(connector)

        # Link each tracked slide span to its active head.
        for span_head_idx, span_tail_idx in itertools.pairwise(separator_indices):
            if slide.notes[span_head_idx].segment_kind not in _INPUT_TRACKED_SEGMENT_KINDS:
                continue
            section_head_idx = section_by_span_head[span_head_idx][0]
            for note_idx in range(span_head_idx, span_tail_idx + 1):
                built[note_idx].active_head_ref = built[section_head_idx].ref()

        _emit_damage_ticks(slide, built, non_attached, separator_indices, emit_note)

    for note, slide in pending_attachments:
        candidates = slide_non_attached[id(slide)]
        attach_head: BaseNote | None = None
        attach_tail: BaseNote | None = None
        for cand in candidates:
            if cand.beat <= note.beat and (attach_head is None or cand.beat > attach_head.beat):
                attach_head = cand
            if cand.beat >= note.beat and (attach_tail is None or cand.beat < attach_tail.beat):
                attach_tail = cand
        if attach_head is None or attach_tail is None:
            raise ValueError(f"Attached note at beat {note.beat} is outside the non-attached span of its slide")
        note.attach_head_ref = attach_head.ref()
        note.attach_tail_ref = attach_tail.ref()
        note.is_attached = True

    out_entities.extend(BpmChange(beat=level_bpm.beat, bpm=level_bpm.bpm) for level_bpm in bpm_changes)

    out_entities.extend(event_entities)

    _emit_sim_lines(note_entities, out_entities)

    initialization = Initialization(
        revision=EngineRevision.LATEST,
        initial_life=1000,
    )
    if first_camera is not None:
        initialization.first_camera_ref = first_camera.ref()
    out_entities.insert(0, initialization)

    sorted_entities = sorted(
        out_entities,
        key=lambda e: (not isinstance(e, Initialization), getattr(e, "beat", -1.0)),
    )

    return Level(
        name=name,
        title=title,
        bgm=bgm if bgm is not None else _build_silent_wav(),
        data=LevelData(
            bgm_offset=0.0,
            entities=list(sorted_entities),
        ),
    )


def _input_section_bounds(notes: list[LevelNote], separator_indices: list[int]) -> dict[int, tuple[int, int]]:
    """Map each separator span's head index to the separator indices bounding its input section.

    Consecutive spans whose kinds share an input class (active hold, or damage) form one section
    with a single active head/tail, so e.g. an active slide with mid-slide separators is one hold
    and a multi-segment damage slide shows its touched state as a whole.
    """

    def input_class(kind: ConnectorKind) -> int:
        # Fake actives get their own class: sharing a head with a real hold would leak their
        # forced-active state onto it.
        match kind:
            case ConnectorKind.ACTIVE_NORMAL | ConnectorKind.ACTIVE_CRITICAL:
                return 1
            case ConnectorKind.DAMAGE:
                return 2
            case ConnectorKind.ACTIVE_FAKE_NORMAL | ConnectorKind.ACTIVE_FAKE_CRITICAL:
                return 3
            case _:
                return 0

    spans = list(itertools.pairwise(separator_indices))
    classes = [input_class(notes[head].segment_kind) for head, _ in spans]
    bounds: dict[int, tuple[int, int]] = {}
    i = 0
    while i < len(spans):
        j = i
        while j + 1 < len(spans) and classes[i] != 0 and classes[j + 1] == classes[i]:
            j += 1
        for k in range(i, j + 1):
            bounds[spans[k][0]] = (spans[i][0], spans[j][1])
        i = j + 1
    return bounds


def _emit_damage_ticks(
    slide: LevelSlide,
    built: list[BaseNote],
    non_attached: list[BaseNote],
    separator_indices: list[int],
    emit_note: Callable[..., BaseNote],
) -> None:
    """Emit a TransientHiddenDamageTickNote every half beat over each DAMAGE segment of the slide.

    Ticks cover both segment endpoints, except that the slide's very first beat never gets a tick
    and a damage->damage joint is emitted once, by the earlier segment. A damage run ending off the
    half-beat grid gets a tick at its final beat, since no grid tick's window covers that stretch.
    """
    spans = list(itertools.pairwise(separator_indices))
    section_by_span_head = _input_section_bounds(slide.notes, separator_indices)
    slide_start_beat = slide.notes[0].beat

    def emit_tick(beat: float, head_ln: LevelNote, section_head_idx: int) -> None:
        tick = emit_note(
            LevelNote(
                beat=beat,
                lane=0.0,
                size=0.0,
                kind=NoteKind.HIDE_DAMAGE_TICK,
                timescale_group=head_ln.timescale_group,
                is_fake=head_ln.is_fake,
            )
        )
        attach_head, attach_tail = _bracketing_non_attached(non_attached, beat)
        tick.attach_head_ref = attach_head.ref()
        tick.attach_tail_ref = attach_tail.ref()
        tick.is_attached = True
        tick.active_head_ref = built[section_head_idx].ref()

    for span_i, (span_head_idx, span_tail_idx) in enumerate(spans):
        head_ln = slide.notes[span_head_idx]
        if head_ln.segment_kind != ConnectorKind.DAMAGE:
            continue
        head_beat = head_ln.beat
        tail_beat = slide.notes[span_tail_idx].beat
        prev_is_damage = span_i > 0 and slide.notes[spans[span_i - 1][0]].segment_kind == ConnectorKind.DAMAGE
        next_is_damage = (
            span_i + 1 < len(spans) and slide.notes[spans[span_i + 1][0]].segment_kind == ConnectorKind.DAMAGE
        )
        section_head_idx = section_by_span_head[span_head_idx][0]
        first_step = math.ceil(head_beat / _DAMAGE_TICK_STEP - _BEAT_EPSILON)
        last_step = math.floor(tail_beat / _DAMAGE_TICK_STEP + _BEAT_EPSILON)
        for step in range(first_step, last_step + 1):
            beat = step * _DAMAGE_TICK_STEP
            if abs(beat - slide_start_beat) < _BEAT_EPSILON:
                continue
            if prev_is_damage and abs(beat - head_beat) < _BEAT_EPSILON:
                continue
            emit_tick(beat, head_ln, section_head_idx)
        if not next_is_damage and tail_beat > last_step * _DAMAGE_TICK_STEP + _BEAT_EPSILON:
            emit_tick(tail_beat, head_ln, section_head_idx)


def _bracketing_non_attached(non_attached: list[BaseNote], beat: float) -> tuple[BaseNote, BaseNote]:
    """Find the consecutive non-attached joints enclosing the beat, attaching backward only at the slide's end."""
    attach_tail: BaseNote | None = None
    for cand in non_attached:
        if cand.beat > beat + _BEAT_EPSILON:
            attach_tail = cand
            break
    if attach_tail is None:
        attach_tail = non_attached[-1]
    attach_head = non_attached[0]
    for cand in non_attached:
        if cand is attach_tail:
            break
        if cand.beat <= beat + _BEAT_EPSILON:
            attach_head = cand
    return attach_head, attach_tail


def _build_timescale_group(
    level_group: LevelTimescaleGroup,
) -> tuple[TimescaleGroup, list[PlayArchetype]]:
    if not level_group.changes:
        raise ValueError("LevelTimescaleGroup must have at least one change")
    group = TimescaleGroup(force_note_speed=level_group.force_note_speed)
    change_entities: list[TimescaleChange] = []
    for level_change in sorted(level_group.changes, key=lambda c: c.beat):
        change = TimescaleChange(
            beat=level_change.beat,
            timescale=level_change.timescale,
            timescale_skip=level_change.timescale_skip,
            timescale_group=group.ref(),
            timescale_ease=level_change.timescale_ease,
            hide_notes=level_change.hide_notes,
        )
        if change_entities:
            change_entities[-1].next_ref = change.ref()
        change_entities.append(change)
    group.first_ref = change_entities[0].ref()
    return group, [group, *change_entities]


def _build_stage(level_stage: LevelStage) -> tuple[DynamicStage, list[PlayArchetype]]:
    stage = DynamicStage(from_start=level_stage.from_start, until_end=level_stage.until_end)
    extra: list[PlayArchetype] = [stage]

    mask_events = [
        StageMaskChange(
            stage_ref=stage.ref(),
            beat=m.beat,
            lane=m.lane,
            size=m.size,
            mask_notes=m.mask_notes,
            ease=m.ease,
        )
        for m in sorted(level_stage.mask_changes, key=lambda c: c.beat)
    ]
    _chain_next_refs(mask_events)
    if mask_events:
        stage.first_mask_change_ref = mask_events[0].ref()
    extra.extend(mask_events)

    pivot_events = [
        StagePivotChange(
            stage_ref=stage.ref(),
            beat=p.beat,
            lane=p.lane,
            division_size=p.division_size,
            division_parity=p.division_parity,
            abs_y_offset=p.abs_y_offset,
            y_beat_offset=p.y_beat_offset,
            ease=p.ease,
        )
        for p in sorted(level_stage.pivot_changes, key=lambda c: c.beat)
    ]
    _chain_next_refs(pivot_events)
    if pivot_events:
        stage.first_pivot_change_ref = pivot_events[0].ref()
    extra.extend(pivot_events)

    style_events = [
        StageStyleChange(
            stage_ref=stage.ref(),
            beat=s.beat,
            judge_line_color=s.judge_line_color,
            judge_line_style=s.judge_line_style,
            left_border_style=s.left_border_style,
            right_border_style=s.right_border_style,
            full_width=s.full_width,
            alpha=s.alpha,
            lane_alpha=s.lane_alpha,
            judge_line_alpha=s.judge_line_alpha,
            division_line_alpha=s.division_line_alpha,
            note_alpha=s.note_alpha,
            ease=s.ease,
        )
        for s in sorted(level_stage.style_changes, key=lambda c: c.beat)
    ]
    _chain_next_refs(style_events)
    if style_events:
        stage.first_style_change_ref = style_events[0].ref()
    extra.extend(style_events)

    transform_events = [
        StageTransformChange(
            stage_ref=stage.ref(),
            beat=tr.beat,
            rotate=tr.rotate,
            x_lane_translate=tr.x_lane_translate,
            y_lane_translate=tr.y_lane_translate,
            anchor=tr.anchor,
            ease=tr.ease,
        )
        for tr in sorted(level_stage.transform_changes, key=lambda c: c.beat)
    ]
    _chain_next_refs(transform_events)
    if transform_events:
        stage.first_transform_change_ref = transform_events[0].ref()
    extra.extend(transform_events)

    return stage, extra


def _build_camera_changes(
    level_cameras: list[LevelCameraChange], out_entities: list[PlayArchetype]
) -> CameraChange | None:
    if not level_cameras:
        return None
    camera_entities = [
        CameraChange(
            beat=c.beat,
            lane=c.lane,
            size=c.size,
            zoom=c.zoom,
            zoom_target_lane=c.zoom_target_lane,
            zoom_target_y=c.zoom_target_y,
            zoom_vertical_align=c.zoom_vertical_align,
            rotate=c.rotate,
            stage_tilt=c.stage_tilt,
            ease=c.ease,
        )
        for c in sorted(level_cameras, key=lambda c: c.beat)
    ]
    _chain_next_refs(camera_entities)
    out_entities.extend(camera_entities)
    return camera_entities[0]


def _chain_next_refs(events: list) -> None:
    for i in range(len(events) - 1):
        events[i].next_ref = events[i + 1].ref()


def _emit_sim_lines(note_entities: list[BaseNote], out_entities: list[PlayArchetype]) -> None:
    buckets: dict[float, list[BaseNote]] = {}
    for note in note_entities:
        if note.key in _SIM_LINE_EXCLUDED_KINDS:
            continue
        buckets.setdefault(note.beat, []).append(note)
    for group in buckets.values():
        if len(group) < 2:
            continue
        group.sort(key=lambda n: n.lane)
        for left, right in itertools.pairwise(group):
            out_entities.append(SimLine(left_ref=left.ref(), right_ref=right.ref()))
