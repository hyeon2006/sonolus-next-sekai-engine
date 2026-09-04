import {
    EngineArchetypeDataName,
    EngineArchetypeName,
    LevelData,
    LevelDataEntity,
} from '@sonolus/core'

import { USC, USCTimeScaleChange } from './index.js'

export const uscToLevelData = (usc: USC, offset = 0): LevelData => {
    let id = 0
    const getName = () => (id++).toString(16)

    const entities: LevelDataEntity[] = [
        {
            archetype: 'Initialization',
            data: [],
        },
    ]

    const timeScaleGroup: LevelDataEntity = {
        archetype: '#TIMESCALE_GROUP',
        data: [],
    }
    entities.push(timeScaleGroup)

    const timeScaleChanges: USCTimeScaleChange[] = []
    const allowSimLines = new Map<number, { lane: number; entity: LevelDataEntity }[]>()

    for (const object of usc.objects) {
        switch (object.type) {
            case 'bpm': {
                entities.push({
                    archetype: EngineArchetypeName.BpmChange,
                    data: [
                        {
                            name: EngineArchetypeDataName.Beat,
                            value: object.beat,
                        },
                        {
                            name: EngineArchetypeDataName.Bpm,
                            value: object.bpm,
                        },
                    ],
                })
                break
            }

            case 'timeScale': {
                timeScaleChanges.push(object)
                break
            }

            case 'single': {
                const entity = {
                    archetype:
                        (object.critical ? 'Critical' : 'Normal') +
                        (object.trace
                            ? object.direction
                                ? 'TraceFlick'
                                : 'Trace'
                            : object.direction
                              ? 'Flick'
                              : 'Tap') +
                        'Note',
                    data: [
                        {
                            name: '#TIMESCALE_GROUP',
                            ref: (timeScaleGroup.name ??= getName()),
                        },
                        {
                            name: EngineArchetypeDataName.Beat,
                            value: object.beat,
                        },
                        {
                            name: 'lane',
                            value: object.lane,
                        },
                        {
                            name: 'size',
                            value: object.size,
                        },
                        {
                            name: 'direction',
                            value: flickDirections[object.direction ?? 'none'],
                        },
                        {
                            name: 'isAttached',
                            value: 0,
                        },
                        {
                            name: 'isSeparator',
                            value: 0,
                        },
                        {
                            name: 'connectorEase',
                            value: 1,
                        },
                        {
                            name: 'segmentKind',
                            value: object.critical ? 2 : 1,
                        },
                        {
                            name: 'segmentAlpha',
                            value: 1,
                        },
                        {
                            name: 'segmentLayer',
                            value: 0,
                        },
                        {
                            name: 'effectKind',
                            value: 0,
                        },
                    ],
                }

                const notes = allowSimLines.get(object.beat)
                if (notes) {
                    notes.push({ lane: object.lane, entity })
                } else {
                    allowSimLines.set(object.beat, [{ lane: object.lane, entity }])
                }

                entities.push(entity)
                break
            }

            case 'slide': {
                let head: LevelDataEntity | undefined
                let headBeat: number | undefined
                let tail: LevelDataEntity | undefined
                let attachHead: LevelDataEntity | undefined
                let attachHeadBeat = 0
                const attaches: LevelDataEntity[] = []
                const connectors: [string, string][] = []
                let prev: LevelDataEntity | undefined
                for (const [i, connection] of object.connections.entries()) {
                    const entity: LevelDataEntity = {
                        archetype:
                            (connection.type === 'ignore'
                                ? 'Anchor'
                                : (connection.critical ? 'Critical' : 'Normal') +
                                  (connection.type === 'start'
                                      ? connection.trace
                                          ? 'HeadTrace'
                                          : 'HeadTap'
                                      : connection.type === 'tick'
                                        ? connection.trace
                                            ? 'Trace'
                                            : 'Tick'
                                        : connection.type === 'attach'
                                          ? 'Tick'
                                          : connection.trace
                                            ? connection.direction
                                                ? 'TailTraceFlick'
                                                : 'TailTrace'
                                            : connection.direction
                                              ? 'TailFlick'
                                              : 'TailRelease')) + 'Note',
                        data: [
                            {
                                name: '#TIMESCALE_GROUP',
                                ref: (timeScaleGroup.name ??= getName()),
                            },
                            {
                                name: EngineArchetypeDataName.Beat,
                                value: connection.beat,
                            },
                            {
                                name: 'lane',
                                value: connection.type === 'attach' ? 0 : connection.lane,
                            },
                            {
                                name: 'size',
                                value: connection.type === 'attach' ? 0 : connection.size,
                            },
                            {
                                name: 'direction',
                                value:
                                    connection.type === 'end'
                                        ? flickDirections[connection.direction ?? 'none']
                                        : 0,
                            },
                            {
                                name: 'isAttached',
                                value: +(connection.type === 'attach'),
                            },
                            {
                                name: 'isSeparator',
                                value: +!object.active,
                            },
                            {
                                name: 'connectorEase',
                                value:
                                    connection.type === 'start' ||
                                    connection.type === 'ignore' ||
                                    connection.type === 'tick'
                                        ? connectorEases[connection.ease]
                                        : 1,
                            },
                            {
                                name: 'segmentKind',
                                value: object.active
                                    ? object.critical
                                        ? 2
                                        : 1
                                    : object.critical
                                      ? 105
                                      : 103,
                            },
                            {
                                name: 'segmentAlpha',
                                value: object.active
                                    ? 1
                                    : ((object.connections.length - 1 - i) /
                                          (object.connections.length - 1)) *
                                          1 +
                                      (i / (object.connections.length - 1)) * 0.2,
                            },
                            {
                                name: 'segmentLayer',
                                value: object.active ? 0 : 1,
                            },
                            {
                                name: 'effectKind',
                                value: 0,
                            },
                        ],
                    }

                    if (
                        connection.type === 'start' ||
                        connection.type === 'end' ||
                        (connection.type === 'tick' && connection.trace)
                    ) {
                        const notes = allowSimLines.get(connection.beat)
                        if (notes) {
                            notes.push({ lane: connection.lane, entity })
                        } else {
                            allowSimLines.set(connection.beat, [{ lane: connection.lane, entity }])
                        }
                    }

                    head ??= entity
                    headBeat ??= connection.beat
                    tail = entity

                    if (object.active && i === object.connections.length - 1) {
                        entity.data.push({
                            name: 'activeHead',
                            ref: (head.name ??= getName()),
                        })
                    }

                    if (connection.type === 'attach') {
                        attaches.push(entity)
                    } else {
                        if (attachHead) {
                            for (const attach of attaches) {
                                attach.data.push(
                                    {
                                        name: 'attachHead',
                                        ref: (attachHead.name ??= getName()),
                                    },
                                    {
                                        name: 'attachTail',
                                        ref: (entity.name ??= getName()),
                                    },
                                )
                            }
                            attaches.length = 0

                            connectors.push([
                                (attachHead.name ??= getName()),
                                (entity.name ??= getName()),
                            ])

                            if (object.active) {
                                for (
                                    let beat = Math.ceil(attachHeadBeat / 0.5) * 0.5;
                                    beat < connection.beat;
                                    beat += 0.5
                                ) {
                                    if (beat === headBeat) continue

                                    entities.push({
                                        archetype: 'TransientHiddenTickNote',
                                        data: [
                                            {
                                                name: EngineArchetypeDataName.Beat,
                                                value: beat,
                                            },
                                            {
                                                name: 'isAttached',
                                                value: 1,
                                            },
                                            {
                                                name: 'attachHead',
                                                ref: (attachHead.name ??= getName()),
                                            },
                                            {
                                                name: 'attachTail',
                                                ref: (entity.name ??= getName()),
                                            },
                                        ],
                                    })
                                }
                            }
                        }

                        attachHead = entity
                        attachHeadBeat = connection.beat
                    }

                    prev?.data.push({
                        name: 'next',
                        ref: (entity.name ??= getName()),
                    })
                    prev = entity

                    entities.push(entity)
                }

                if (!head) throw new Error('Unexpected missing head')
                if (!tail) throw new Error('Unexpected missing tail')

                for (const [headRef, tailRef] of connectors) {
                    entities.push({
                        archetype: 'Connector',
                        data: object.active
                            ? [
                                  {
                                      name: 'head',
                                      ref: headRef,
                                  },
                                  {
                                      name: 'tail',
                                      ref: tailRef,
                                  },
                                  {
                                      name: 'segmentHead',
                                      ref: (head.name ??= getName()),
                                  },
                                  {
                                      name: 'segmentTail',
                                      ref: (tail.name ??= getName()),
                                  },
                                  {
                                      name: 'activeHead',
                                      ref: (head.name ??= getName()),
                                  },
                                  {
                                      name: 'activeTail',
                                      ref: (tail.name ??= getName()),
                                  },
                              ]
                            : [
                                  {
                                      name: 'head',
                                      ref: headRef,
                                  },
                                  {
                                      name: 'tail',
                                      ref: tailRef,
                                  },
                                  {
                                      name: 'segmentHead',
                                      ref: headRef,
                                  },
                                  {
                                      name: 'segmentTail',
                                      ref: tailRef,
                                  },
                              ],
                    })
                }
                break
            }
        }
    }

    let prevTimeScaleChange: LevelDataEntity | undefined
    for (const timeScaleChange of timeScaleChanges) {
        const entity: LevelDataEntity = {
            archetype: EngineArchetypeName.TimeScaleChange,
            data: [
                {
                    name: '#TIMESCALE_GROUP',
                    ref: (timeScaleGroup.name ??= getName()),
                },
                {
                    name: EngineArchetypeDataName.Beat,
                    value: timeScaleChange.beat,
                },
                {
                    name: EngineArchetypeDataName.TimeScale,
                    value: timeScaleChange.timeScale,
                },
                {
                    name: '#TIMESCALE_SKIP',
                    value: 0,
                },
                {
                    name: '#TIMESCALE_EASE',
                    value: 0,
                },
                {
                    name: 'hideNotes',
                    value: 0,
                },
            ],
        }

        if (prevTimeScaleChange) {
            prevTimeScaleChange.data.push({
                name: 'next',
                ref: (entity.name ??= getName()),
            })
        } else {
            timeScaleGroup.data.push({
                name: 'first',
                ref: (entity.name ??= getName()),
            })
        }

        prevTimeScaleChange = entity
        entities.push(entity)
    }

    for (const notes of allowSimLines.values()) {
        if (notes.length < 2) continue

        notes.sort((a, b) => a.lane - b.lane)

        let prev: LevelDataEntity | undefined
        for (const { entity } of notes) {
            if (prev) {
                entities.push({
                    archetype: 'SimLine',
                    data: [
                        {
                            name: 'left',
                            ref: (prev.name ??= getName()),
                        },
                        {
                            name: 'right',
                            ref: (entity.name ??= getName()),
                        },
                    ],
                })
            }

            prev = entity
        }
    }

    return {
        bgmOffset: usc.offset + offset,
        entities,
    }
}

const flickDirections = {
    none: 0,
    up: 0,
    left: 1,
    right: 2,
}

const connectorEases = {
    linear: 1,
    in: 2,
    out: 3,
}
