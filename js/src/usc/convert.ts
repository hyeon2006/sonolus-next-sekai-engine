import { type LevelData, type LevelDataEntity } from '@sonolus/core'

import {
    USC,
    USCBpmChange,
    USCConnectionEndNote,
    USCConnectionStartNote,
    USCDamageNote,
    USCFever,
    USCGuideNote,
    USCObject,
    USCSingleNote,
    USCSkill,
    USCSlideNote,
    USCTimeScaleChange,
} from './index.js'

interface IntermediateEntity {
    archetype: string
    data: Record<string, number | IntermediateEntity>
}

type UscEase = USCConnectionStartNote['ease']

const SONOLUS_DIRECTIONS = {
    left: 1,
    up: 0,
    right: 2,
} as const

type SonolusDirectionName = keyof typeof SONOLUS_DIRECTIONS

const SONOLUS_CONNECTOR_EASES = {
    outin: 5,
    out: 3,
    linear: 1,
    in: 2,
    inout: 4,
} as const

type SonolusEaseName = keyof typeof SONOLUS_CONNECTOR_EASES

const mapUscEaseToSonolusEase = (ease: UscEase | undefined | null): SonolusEaseName => {
    const uscEase = ease ?? 'linear'
    return uscEase
}

const SONOLUS_GUIDE_COLORS = {
    neutral: 101,
    red: 102,
    green: 103,
    blue: 104,
    yellow: 105,
    purple: 106,
    cyan: 107,
    black: 108,
} as const

const EPSILON = 1e-6

/** Convert a USC to a Level Data */
export const uscToLevelData = (
    usc: USC,
    offset = 0,
    smoothGuideFade = false,
    useGuideLayer = false,
): LevelData => {
    const allUscObjects: USCObject[] = usc.objects ?? []

    const allIntermediateEntities: IntermediateEntity[] = []
    const simLineEligibleNotes: IntermediateEntity[] = []
    const timeScaleGroupIntermediates: IntermediateEntity[] = []

    const createIntermediate = (
        archetype: string,
        data: Record<string, number | IntermediateEntity>,
        isSimEligible = false,
    ): IntermediateEntity => {
        const intermediateEntity: IntermediateEntity = { archetype, data }
        allIntermediateEntities.push(intermediateEntity)
        if (isSimEligible) {
            simLineEligibleNotes.push(intermediateEntity)
        }
        return intermediateEntity
    }

    createIntermediate('Initialization', {})

    const bpmChanges = allUscObjects.filter((o): o is USCBpmChange => o.type === 'bpm')
    const timeScaleGroups = allUscObjects.filter(
        (o): o is USCTimeScaleChange => o.type === 'timeScaleGroup',
    )
    const singleNotes = allUscObjects.filter((o): o is USCSingleNote => o.type === 'single')
    const damageNotes = allUscObjects.filter((o): o is USCDamageNote => o.type === 'damage')
    const slideNotes = allUscObjects.filter(
        (o): o is USCSlideNote => o.type === 'slide' || (o.type === 'guide' && !('midpoints' in o)),
    )
    const guideNotes = allUscObjects.filter(
        (o): o is USCGuideNote => o.type === 'guide' && 'midpoints' in o,
    )
    const skills = allUscObjects.filter((o): o is USCSkill => o.type === 'skill')
    const feverChance = allUscObjects
        .filter((o): o is USCFever => o.type === 'feverChance')
        .sort((a, b) => a.beat - b.beat)
        .slice(0, 1)

    const feverStart = allUscObjects
        .filter((o): o is USCFever => o.type === 'feverStart')
        .sort((a, b) => a.beat - b.beat)
        .slice(0, 1)

    if (bpmChanges.length === 0) {
        bpmChanges.push({ type: 'bpm', beat: 0, bpm: 160 })
    }
    for (const bpmChange of bpmChanges) {
        createIntermediate('#BPM_CHANGE', {
            '#BEAT': bpmChange.beat,
            '#BPM': bpmChange.bpm,
        })
    }

    if (timeScaleGroups.length === 0) {
        timeScaleGroups.push({
            type: 'timeScaleGroup',
            changes: [{ beat: 0, timeScale: 1 }],
        })
    }

    for (const skill of skills) {
        createIntermediate('Skill', {
            '#BEAT': skill.beat,
        })
    }
    for (const fc of feverChance) {
        createIntermediate('FeverChance', {
            '#BEAT': fc.beat,
        })
    }
    for (const fs of feverStart) {
        createIntermediate('FeverStart', {
            '#BEAT': fs.beat,
        })
    }

    for (const timeScaleGroup of timeScaleGroups) {
        const groupIntermediateEntity: IntermediateEntity = createIntermediate(
            '#TIMESCALE_GROUP',
            {},
        )
        timeScaleGroupIntermediates.push(groupIntermediateEntity)

        let lastChangeIntermediate: IntermediateEntity | null = null
        const changes = [...timeScaleGroup.changes].sort((a, b) => a.beat - b.beat)

        for (const timeScaleChange of changes) {
            const newChangeIntermediate: IntermediateEntity = createIntermediate(
                '#TIMESCALE_CHANGE',
                {
                    '#BEAT': timeScaleChange.beat,
                    '#TIMESCALE':
                        timeScaleChange.timeScale === 0 ? 0.000001 : timeScaleChange.timeScale,
                    '#TIMESCALE_SKIP': 0,
                    '#TIMESCALE_GROUP': groupIntermediateEntity,
                    '#TIMESCALE_EASE': 0,
                },
            )

            if (lastChangeIntermediate === null) {
                groupIntermediateEntity.data.first = newChangeIntermediate
            } else {
                lastChangeIntermediate.data.next = newChangeIntermediate
            }
            lastChangeIntermediate = newChangeIntermediate
        }
    }

    for (const singleNote of singleNotes) {
        const name_parts: string[] = []
        name_parts.push(singleNote.critical ? 'Critical' : 'Normal')

        if (singleNote.direction === undefined || singleNote.direction === null) {
            name_parts.push(singleNote.trace ? 'Trace' : 'Tap')
        } else {
            name_parts.push(singleNote.trace ? 'TraceFlick' : 'Flick')
        }
        name_parts.push('Note')

        const archetype = name_parts.join('')
        const timeScaleGroupRef = timeScaleGroupIntermediates[singleNote.timeScaleGroup ?? 0]

        let sonolusDirName: string
        if (singleNote.direction === undefined || singleNote.direction === null) {
            sonolusDirName = 'up'
        } else {
            sonolusDirName = singleNote.direction
        }

        const data: Record<string, number | IntermediateEntity> = {
            '#BEAT': singleNote.beat,
            lane: singleNote.lane,
            size: singleNote.size,
            isAttached: 0,
            connectorEase: SONOLUS_CONNECTOR_EASES.linear,
            isSeparator: 0,
            segmentKind: singleNote.critical ? 2 : 1,
            segmentAlpha: 1,
            '#TIMESCALE_GROUP': timeScaleGroupRef,
        }

        const directionValue = SONOLUS_DIRECTIONS[sonolusDirName as SonolusDirectionName]
        if (directionValue !== undefined) {
            data.direction = directionValue
        }

        createIntermediate(archetype, data, true)
    }

    for (const damageNote of damageNotes) {
        const archetype = 'DamageNote'
        const timeScaleGroupRef = timeScaleGroupIntermediates[damageNote.timeScaleGroup ?? 0]

        createIntermediate(archetype, {
            '#BEAT': damageNote.beat,
            lane: damageNote.lane,
            size: damageNote.size,
            direction: SONOLUS_DIRECTIONS.up,
            isAttached: 0,
            connectorEase: SONOLUS_CONNECTOR_EASES.linear,
            isSeparator: 0,
            segmentKind: 1,
            segmentAlpha: 1,
            '#TIMESCALE_GROUP': timeScaleGroupRef,
        })
    }

    for (const slideNote of slideNotes) {
        let prevJointIntermediate: IntermediateEntity | null = null
        let prevNoteIntermediate: IntermediateEntity | null = null
        let headNoteIntermediate: IntermediateEntity | null = null
        let currentSegmentHead: IntermediateEntity | null = null
        const queuedAttachIntermediates: IntermediateEntity[] = []
        const connectors: IntermediateEntity[] = []
        const pendingSegmentConnectors: IntermediateEntity[] = []

        const connections = [...slideNote.connections].sort((a, b) => a.beat - b.beat)
        if (connections.length === 0) continue

        const stepSize = Math.max(1, connections.length - 1)

        let nextHiddenTickBeat = Math.floor(connections[0].beat * 2 + 1) / 2

        let stepIdx = 0

        for (const connectionNote of connections) {
            let isSimLineEligible = false
            let isAttached = false
            const name_parts: string[] = []

            switch (connectionNote.type) {
                case 'start':
                    if (connectionNote.judgeType === 'none') {
                        name_parts.push('Anchor')
                    } else {
                        name_parts.push(connectionNote.critical ? 'Critical' : 'Normal')
                        name_parts.push('Head')
                        if (connectionNote.judgeType === 'trace') name_parts.push('Trace')
                        else if (connectionNote.judgeType === 'normal') name_parts.push('Tap')
                        isSimLineEligible = true
                    }
                    break
                case 'end':
                    if (connectionNote.judgeType === 'none') {
                        name_parts.push('Anchor')
                    } else {
                        name_parts.push(connectionNote.critical ? 'Critical' : 'Normal')
                        name_parts.push('Tail')
                        if (
                            connectionNote.direction === undefined ||
                            connectionNote.direction === null
                        ) {
                            if (connectionNote.judgeType === 'trace') name_parts.push('Trace')
                            else if (connectionNote.judgeType === 'normal')
                                name_parts.push('Release')
                        } else {
                            if (connectionNote.judgeType === 'trace') name_parts.push('TraceFlick')
                            else if (connectionNote.judgeType === 'normal') name_parts.push('Flick')
                        }
                        isSimLineEligible = true
                    }
                    break
                case 'tick':
                    if (connectionNote.critical !== undefined) {
                        name_parts.push(connectionNote.critical ? 'Critical' : 'Normal')
                        if (connectionNote.judgeType === 'trace') name_parts.push('Trace')
                        else name_parts.push('Tick')
                    } else {
                        name_parts.push('Anchor')
                    }
                    break
                case 'attach':
                    isAttached = true
                    if (connectionNote.critical !== undefined) {
                        name_parts.push(connectionNote.critical ? 'Critical' : 'Normal')
                        name_parts.push('Tick')
                    } else {
                        name_parts.push('TransientHiddenTick')
                    }
                    break
            }
            name_parts.push('Note')
            const archetype = name_parts.join('')

            const timeScaleGroupRef =
                timeScaleGroupIntermediates[connectionNote.timeScaleGroup ?? 0]

            let sonolusDirName: string
            const direction = (connectionNote as USCConnectionEndNote).direction
            if (direction === undefined || direction === null) {
                sonolusDirName = 'up'
            } else {
                sonolusDirName = direction
            }

            const sonolusEaseValue =
                SONOLUS_CONNECTOR_EASES[
                    mapUscEaseToSonolusEase(
                        'ease' in connectionNote
                            ? (connectionNote as unknown as { ease?: UscEase }).ease
                            : undefined,
                    )
                ]

            let segmentAlpha = 1
            if (slideNote.type === 'guide') {
                // 공식: 1 - (0.8 * (현재단계 / 전체구간)) -> 1에서 0.2까지 감소
                segmentAlpha = 1 - 0.8 * (stepIdx / stepSize)
            }
            const isSeparatorValue = slideNote.type == 'slide' ? 0 : 1

            const data: Record<string, number | IntermediateEntity> = {
                '#BEAT': connectionNote.beat,
                lane: 'lane' in connectionNote ? connectionNote.lane : 0,
                size: 'size' in connectionNote ? connectionNote.size : 0,
                isAttached: isAttached ? 1 : 0,
                connectorEase: sonolusEaseValue,
                isSeparator: isSeparatorValue,
                segmentKind:
                    slideNote.type == 'slide'
                        ? slideNote.critical
                            ? 2
                            : 1
                        : slideNote.critical
                          ? 105
                          : 103,
                segmentAlpha: segmentAlpha,
                segmentLayer: slideNote.type == 'slide' ? 0 : 1,
                '#TIMESCALE_GROUP': timeScaleGroupRef,
            }

            const directionValue = SONOLUS_DIRECTIONS[sonolusDirName as SonolusDirectionName]
            if (directionValue !== undefined) {
                data.direction = directionValue
            }

            const connectionIntermediate = createIntermediate(archetype, data, isSimLineEligible)

            if (headNoteIntermediate === null) {
                headNoteIntermediate = connectionIntermediate
            }
            if (currentSegmentHead === null) {
                currentSegmentHead = connectionIntermediate
            }
            connectionIntermediate.data.activeHead = headNoteIntermediate

            if (isAttached) {
                queuedAttachIntermediates.push(connectionIntermediate)
            } else {
                if (prevJointIntermediate !== null) {
                    for (const attachIntermediate of queuedAttachIntermediates) {
                        attachIntermediate.data.attachHead = prevJointIntermediate
                        attachIntermediate.data.attachTail = connectionIntermediate
                    }
                    queuedAttachIntermediates.length = 0

                    while (
                        slideNote.type == 'slide' &&
                        nextHiddenTickBeat + EPSILON <
                            (connectionIntermediate.data['#BEAT'] as number)
                    ) {
                        createIntermediate('TransientHiddenTickNote', {
                            '#BEAT': nextHiddenTickBeat,
                            '#TIMESCALE_GROUP': timeScaleGroupIntermediates[0],
                            lane: connectionIntermediate.data.lane,
                            size: connectionIntermediate.data.size,
                            direction: SONOLUS_DIRECTIONS.up,
                            isAttached: 1,
                            connectorEase: SONOLUS_CONNECTOR_EASES.linear,
                            isSeparator: 0,
                            segmentKind: 1,
                            segmentAlpha: 0,
                            activeHead: headNoteIntermediate,
                            attachHead: prevJointIntermediate,
                            attachTail: connectionIntermediate,
                        })
                        nextHiddenTickBeat += 0.5
                    }

                    const connectorIntermediate = createIntermediate('Connector', {
                        head: prevJointIntermediate,
                        tail: connectionIntermediate,
                    })
                    connectors.push(connectorIntermediate)
                    pendingSegmentConnectors.push(connectorIntermediate)
                }
                prevJointIntermediate = connectionIntermediate
            }

            if (isSeparatorValue === 1) {
                for (const conn of pendingSegmentConnectors) {
                    conn.data.segmentHead = currentSegmentHead
                    conn.data.segmentTail = connectionIntermediate
                }
                pendingSegmentConnectors.length = 0

                currentSegmentHead = connectionIntermediate
            }

            if (prevNoteIntermediate !== null) {
                prevNoteIntermediate.data.next = connectionIntermediate
            }
            prevNoteIntermediate = connectionIntermediate
            stepIdx++
        }

        if (!headNoteIntermediate || !prevJointIntermediate) {
            continue
        }
        if (currentSegmentHead) {
            for (const conn of pendingSegmentConnectors) {
                conn.data.segmentHead = currentSegmentHead
                conn.data.segmentTail = prevJointIntermediate
            }
        }
        if (slideNote.type === 'slide') {
            for (const connectorIntermediate of connectors) {
                connectorIntermediate.data.activeHead = headNoteIntermediate
                connectorIntermediate.data.activeTail = prevJointIntermediate
            }
        }
    }

    for (const guideNote of guideNotes) {
        const connections = [...guideNote.midpoints].sort((a, b) => a.beat - b.beat)
        let prevMidpointIntermediate: IntermediateEntity | null = null
        let headMidpointIntermediate: IntermediateEntity | null = null
        const guideConnectors: IntermediateEntity[] = []

        const stepSize = Math.max(1, connections.length - 1)
        let stepIdx = 0

        for (const midpointNote of connections) {
            const timeScaleGroupRef = timeScaleGroupIntermediates[midpointNote.timeScaleGroup ?? 0]

            let segmentAlpha = 1
            let isSeparator = 0

            if (smoothGuideFade) {
                isSeparator = 1

                if (guideNote.fade === 'out') {
                    segmentAlpha = 1 - 0.8 * (stepIdx / stepSize)
                } else if (guideNote.fade === 'in') {
                    segmentAlpha = 1 - 0.8 * ((stepSize - stepIdx) / stepSize)
                }
            }

            const midpointIntermediate = createIntermediate('AnchorNote', {
                '#BEAT': midpointNote.beat,
                lane: midpointNote.lane,
                size: midpointNote.size,
                direction: SONOLUS_DIRECTIONS.up,
                isAttached: 0,
                connectorEase: SONOLUS_CONNECTOR_EASES[mapUscEaseToSonolusEase(midpointNote.ease)],
                isSeparator: isSeparator,
                segmentKind: SONOLUS_GUIDE_COLORS[guideNote.color],
                segmentAlpha: segmentAlpha,
                segmentLayer: useGuideLayer ? 1 : 0,
                '#TIMESCALE_GROUP': timeScaleGroupRef,
            })

            if (headMidpointIntermediate === null) {
                headMidpointIntermediate = midpointIntermediate
            }

            if (prevMidpointIntermediate !== null) {
                const connectorIntermediate = createIntermediate('Connector', {
                    head: prevMidpointIntermediate,
                    tail: midpointIntermediate,
                })
                guideConnectors.push(connectorIntermediate)
                prevMidpointIntermediate.data.next = midpointIntermediate
            }
            prevMidpointIntermediate = midpointIntermediate

            stepIdx++
        }

        if (!headMidpointIntermediate || !prevMidpointIntermediate) {
            continue
        }

        for (const connectorIntermediate of guideConnectors) {
            connectorIntermediate.data.segmentHead = headMidpointIntermediate
            connectorIntermediate.data.segmentTail = prevMidpointIntermediate
        }

        if (!smoothGuideFade) {
            switch (guideNote.fade) {
                case 'in':
                    if (headMidpointIntermediate) {
                        headMidpointIntermediate.data.segmentAlpha = 0
                    }
                    break
                case 'out':
                    if (prevMidpointIntermediate) {
                        prevMidpointIntermediate.data.segmentAlpha = 0
                    }
                    break
                case 'none':
                    break
            }
        }
    }

    simLineEligibleNotes.sort((noteA, noteB) => {
        const beatA = noteA.data['#BEAT'] as number
        const beatB = noteB.data['#BEAT'] as number
        if (beatA !== beatB) return beatA - beatB
        const laneA = noteA.data.lane as number
        const laneB = noteB.data.lane as number
        return laneA - laneB
    })

    const simGroups: IntermediateEntity[][] = []
    let currentSimGroup: IntermediateEntity[] = []
    for (const simNote of simLineEligibleNotes) {
        if (
            currentSimGroup.length === 0 ||
            Math.abs(
                (simNote.data['#BEAT'] as number) - (currentSimGroup[0].data['#BEAT'] as number),
            ) < 1e-2
        ) {
            currentSimGroup.push(simNote)
        } else {
            simGroups.push(currentSimGroup)
            currentSimGroup = [simNote]
        }
    }
    if (currentSimGroup.length > 0) {
        simGroups.push(currentSimGroup)
    }

    for (const simGroup of simGroups) {
        for (let i = 0; i < simGroup.length - 1; i++) {
            const leftNote = simGroup[i]
            const rightNote = simGroup[i + 1]
            createIntermediate('SimLine', {
                left: leftNote,
                right: rightNote,
            })
        }
    }

    const entities: LevelDataEntity[] = []
    const intermediateToRef = new Map<IntermediateEntity, string>()
    let entityRefCounter = 0

    const getRef = (intermediateEntity: IntermediateEntity): string => {
        let ref = intermediateToRef.get(intermediateEntity)
        if (ref) return ref
        ref = (entityRefCounter++).toString(16)
        intermediateToRef.set(intermediateEntity, ref)
        return ref
    }

    for (const intermediateEntity of allIntermediateEntities) {
        const entity: LevelDataEntity = {
            archetype: intermediateEntity.archetype,
            name: getRef(intermediateEntity),
            data: [],
        }

        for (const [dataName, dataValue] of Object.entries(intermediateEntity.data)) {
            if (typeof dataValue === 'number') {
                entity.data.push({ name: dataName, value: dataValue })
            } else if (dataValue !== undefined) {
                entity.data.push({ name: dataName, ref: getRef(dataValue) })
            }
        }

        entities.push(entity)
    }

    return {
        bgmOffset: usc.offset + offset,
        entities,
    }
}
