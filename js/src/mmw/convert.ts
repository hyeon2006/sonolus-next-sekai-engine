import { type LevelData, type LevelDataEntity } from '@sonolus/core'

import {
    USC,
    USCColor,
    USCConnectionAttachNote,
    USCConnectionEndNote,
    USCConnectionStartNote,
    USCConnectionTickNote,
    USCDamageNote,
    USCGuideNote,
    USCSingleNote,
    USCSlideNote,
} from '../usc/index.js'
import { analyze, EaseType } from './analyze.js'

interface IntermediateEntity {
    archetype: string
    data: Record<string, number | IntermediateEntity>
}

const SONOLUS_CONNECTOR_EASES = {
    outin: 5,
    out: 3,
    linear: 1,
    in: 2,
    inout: 4,
} as const

const mmwEaseToSonolusEase = (ease: EaseType): number => {
    switch (ease) {
        case 'linear':
            return SONOLUS_CONNECTOR_EASES.linear
        case 'easeIn':
            return SONOLUS_CONNECTOR_EASES.in
        case 'easeOut':
            return SONOLUS_CONNECTOR_EASES.out
        case 'easeInOut':
            return SONOLUS_CONNECTOR_EASES.inout
        case 'easeOutIn':
            return SONOLUS_CONNECTOR_EASES.outin
        default:
            return SONOLUS_CONNECTOR_EASES.linear
    }
}

const EPSILON = 1e-6
const TICKS_PER_BEAT = 480

const uscColorByValue = new Map(
    Object.entries(USCColor).map(([name, value]) => [value, name as USCColor]),
)

const laneToSonolusLane = (lane: number, width: number): number => {
    return lane - 6 + width / 2
}

const flickTypeToDirection = (type: string): number => {
    switch (type) {
        case 'up':
            return 0
        case 'left':
            return 1
        case 'right':
            return 2
        case 'down':
            return 3
        case 'down_left':
            return 4
        case 'down_right':
            return 5
        default:
            return 0
    }
}

const resolveConnectorKind = (isCritical: boolean, isDummy: boolean): number => {
    if (isDummy) {
        return isCritical ? 52 : 51
    }
    return isCritical ? 1 : 0
}

const mmwsEaseToUSCEase = {
    linear: 'linear',
    easeOut: 'out',
    easeIn: 'in',
    easeInOut: 'inout',
    easeOutIn: 'outin',
} as const satisfies Record<EaseType, string>

const laneToUSCLane = ({ lane, width }: { lane: number; width: number }): number => {
    return lane - 6 + width / 2
}

/**
 * Convert MMWS or CCMMWS to a USC
 */
export const mmwsToUSC = (mmws: Uint8Array): USC => {
    const score = analyze(mmws)
    const usc: USC = {
        objects: [],
        offset: score.metadata.musicOffset / -1000,
    }

    for (const bpmChange of score.events.bpmChanges) {
        usc.objects.push({
            type: 'bpm',
            beat: bpmChange.tick / TICKS_PER_BEAT,
            bpm: bpmChange.bpm,
        })
    }
    const tsGroups = new Map<number, { beat: number; timeScale: number }[]>()
    for (let i = 0; i < score.numLayers; i++) {
        tsGroups.set(i, [])
    }
    for (const hispeedChange of score.events.hispeedChanges) {
        const key = hispeedChange.layer
        if (!tsGroups.has(key)) {
            if (!tsGroups.has(0)) tsGroups.set(0, [])
            tsGroups.get(0)?.push({
                beat: hispeedChange.tick / TICKS_PER_BEAT,
                timeScale: hispeedChange.speed,
            })
            continue
        }
        tsGroups.get(key)?.push({
            beat: hispeedChange.tick / TICKS_PER_BEAT,
            timeScale: hispeedChange.speed,
        })
    }
    for (const changes of tsGroups.values()) {
        usc.objects.push({
            type: 'timeScaleGroup',
            changes,
        })
    }

    for (const tap of score.taps) {
        const uscTap: USCSingleNote = {
            type: 'single',
            beat: tap.tick / TICKS_PER_BEAT,
            timeScaleGroup: tap.layer,
            critical: tap.flags.critical,
            lane: laneToUSCLane(tap),
            size: tap.width / 2,
            trace: tap.flags.friction,
        }
        if (tap.flickType === 'up' || tap.flickType === 'left' || tap.flickType === 'right') {
            uscTap.direction = tap.flickType
        }
        usc.objects.push(uscTap)
    }
    for (const hold of score.holds) {
        const uscStartNote: USCConnectionStartNote = {
            type: 'start',
            beat: hold.start.tick / TICKS_PER_BEAT,
            timeScaleGroup: hold.start.layer,
            critical: hold.start.flags.critical,
            ease: mmwsEaseToUSCEase[hold.start.ease],
            lane: laneToUSCLane(hold.start),
            size: hold.start.width / 2,
            judgeType: hold.flags.startHidden
                ? 'none'
                : hold.start.flags.friction
                  ? 'trace'
                  : 'normal',
        }
        const uscEndNote: USCConnectionEndNote = {
            type: 'end',
            beat: hold.end.tick / TICKS_PER_BEAT,
            timeScaleGroup: hold.end.layer,
            critical: hold.end.flags.critical,
            lane: laneToUSCLane(hold.end),
            size: hold.end.width / 2,
            judgeType: hold.flags.endHidden ? 'none' : hold.end.flags.friction ? 'trace' : 'normal',
        }
        if (
            hold.end.flickType === 'up' ||
            hold.end.flickType === 'left' ||
            hold.end.flickType === 'right'
        ) {
            uscEndNote.direction = hold.end.flickType
        }

        if (hold.flags.guide) {
            const uscGuide: USCGuideNote = {
                type: 'guide',
                fade: hold.fadeType === 0 ? 'out' : hold.fadeType === 1 ? 'none' : 'in',
                color: uscColorByValue.get(hold.guideColor) as USCColor,
                midpoints: [hold.start, ...hold.steps, hold.end].map((step) => ({
                    beat: step.tick / TICKS_PER_BEAT,
                    lane: laneToUSCLane(step),
                    size: step.width / 2,
                    timeScaleGroup: step.layer,
                    ease: 'ease' in step ? mmwsEaseToUSCEase[step.ease] : 'linear',
                })),
            }
            usc.objects.push(uscGuide)
        } else {
            const uscSlide: USCSlideNote = {
                type: 'slide',
                critical: hold.start.flags.critical,
                connections: [
                    uscStartNote,
                    ...hold.steps.map((step) => {
                        const beat = step.tick / TICKS_PER_BEAT
                        const lane = laneToUSCLane(step)
                        const size = step.width / 2
                        if (step.type === 'ignored') {
                            return {
                                type: 'attach',
                                beat,
                                critical: hold.start.flags.critical,
                                timeScaleGroup: step.layer,
                            } satisfies USCConnectionAttachNote
                        } else {
                            const uscStep: USCConnectionTickNote = {
                                type: 'tick',
                                beat,

                                timeScaleGroup: step.layer,
                                lane,
                                size,
                                ease: mmwsEaseToUSCEase[step.ease],
                            }
                            if (step.type === 'visible') {
                                uscStep.critical = hold.start.flags.critical
                            }

                            return uscStep
                        }
                    }),
                    uscEndNote,
                ],
            }
            usc.objects.push(uscSlide)
        }
    }

    for (const damage of score.damages) {
        const uscDamage: USCDamageNote = {
            type: 'damage',
            beat: damage.tick / TICKS_PER_BEAT,
            timeScaleGroup: damage.layer,
            lane: laneToUSCLane(damage),
            size: damage.width / 2,
        }
        usc.objects.push(uscDamage)
    }

    return usc
}

/**
 * Convert CCMMWS to a USC
 */
export const ccmmwsToUSC = mmwsToUSC

/**
 * Convert UCMMWS to a LevelData
 */
export const ucmmwsToLevelData = (mmws: Uint8Array): LevelData => {
    const score = analyze(mmws)
    const entities: LevelDataEntity[] = []

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
    createIntermediate('Stage', {})

    if (score.events.bpmChanges.length === 0) {
        createIntermediate('#BPM_CHANGE', { '#BEAT': 0, '#BPM': 120 })
    }
    for (const bpm of score.events.bpmChanges) {
        createIntermediate('#BPM_CHANGE', {
            '#BEAT': bpm.tick / TICKS_PER_BEAT,
            '#BPM': bpm.bpm,
        })
    }

    for (const skillTick of score.events.skills) {
        createIntermediate('Skill', { '#BEAT': skillTick / TICKS_PER_BEAT })
    }

    if (score.events.fever.start > 0) {
        createIntermediate('FeverChance', { '#BEAT': score.events.fever.start / TICKS_PER_BEAT })
    }
    if (score.events.fever.end > 0) {
        createIntermediate('FeverStart', { '#BEAT': score.events.fever.end / TICKS_PER_BEAT })
    }

    const layerChanges = new Map<number, typeof score.events.hispeedChanges>()
    for (let i = 0; i < Math.max(1, score.numLayers); i++) {
        layerChanges.set(i, [])
    }
    for (const hs of score.events.hispeedChanges) {
        if (!layerChanges.has(hs.layer)) {
            if (!layerChanges.has(0)) layerChanges.set(0, [])
            layerChanges.get(0)?.push(hs)
            continue
        }
        layerChanges.get(hs.layer)?.push(hs)
    }

    for (let i = 0; i < Math.max(1, score.numLayers); i++) {
        const changes = layerChanges.get(i) || []

        if (changes.length === 0 || changes[0].tick !== 0) {
            changes.unshift({
                tick: 0,
                speed: 1,
                layer: i,
                skip: 0,
                ease: 0,
                hideNotes: false,
            })
        }
        changes.sort((a, b) => a.tick - b.tick)

        const groupIntermediate = createIntermediate('#TIMESCALE_GROUP', {})
        timeScaleGroupIntermediates[i] = groupIntermediate

        let lastChangeIntermediate: IntermediateEntity | null = null

        for (const hs of changes) {
            const data: Record<string, number | IntermediateEntity> = {
                '#BEAT': hs.tick / TICKS_PER_BEAT,
                '#TIMESCALE': hs.speed === 0 ? 0.000001 : hs.speed,
                '#TIMESCALE_SKIP': hs.skip || 0,
                '#TIMESCALE_EASE': hs.ease || 0,
                '#TIMESCALE_GROUP': groupIntermediate,
            }

            if (hs.hideNotes) {
                data.hideNotes = 1
            }

            const newChangeIntermediate = createIntermediate('#TIMESCALE_CHANGE', data)

            if (lastChangeIntermediate === null) {
                groupIntermediate.data.first = newChangeIntermediate
            } else {
                lastChangeIntermediate.data.next = newChangeIntermediate
            }
            lastChangeIntermediate = newChangeIntermediate
        }
    }

    for (const tap of score.taps) {
        const name_parts: string[] = []
        name_parts.push(tap.flags.critical ? 'Critical' : 'Normal')

        if (tap.flickType !== 'none') {
            name_parts.push(tap.flags.friction ? 'TraceFlick' : 'Flick')
        } else {
            name_parts.push(tap.flags.friction ? 'Trace' : 'Tap')
        }
        name_parts.push('Note')

        const archetype = tap.flags.dummy ? `Fake${name_parts.join('')}` : name_parts.join('')

        const timeScaleGroupRef =
            timeScaleGroupIntermediates[tap.layer] || timeScaleGroupIntermediates[0]

        const data: Record<string, number | IntermediateEntity> = {
            '#BEAT': tap.tick / TICKS_PER_BEAT,
            lane: laneToSonolusLane(tap.lane, tap.width),
            size: tap.width,
            isAttached: 0,
            connectorEase: SONOLUS_CONNECTOR_EASES.linear,
            isSeparator: 0,
            segmentKind: tap.flags.critical ? 2 : 1,
            segmentAlpha: 1,
            '#TIMESCALE_GROUP': timeScaleGroupRef,
        }

        if (tap.flickType !== 'none') {
            data.direction = flickTypeToDirection(tap.flickType)
        }

        createIntermediate(archetype, data, true)
    }

    for (const damage of score.damages) {
        const archetype = damage.flags.dummy ? 'FakeDamageNote' : 'DamageNote'
        const timeScaleGroupRef =
            timeScaleGroupIntermediates[damage.layer] || timeScaleGroupIntermediates[0]

        createIntermediate(archetype, {
            '#BEAT': damage.tick / TICKS_PER_BEAT,
            lane: laneToSonolusLane(damage.lane, damage.width),
            size: damage.width,
            direction: 0,
            isAttached: 0,
            connectorEase: SONOLUS_CONNECTOR_EASES.linear,
            isSeparator: 0,
            segmentKind: 1,
            segmentAlpha: 1,
            '#TIMESCALE_GROUP': timeScaleGroupRef,
        })
    }

    for (const hold of score.holds) {
        const timeScaleGroupRef =
            timeScaleGroupIntermediates[hold.start.layer] || timeScaleGroupIntermediates[0]

        if (hold.flags.guide) {
            const points = [hold.start, ...hold.steps, hold.end]
            points.sort((a, b) => a.tick - b.tick)

            let prevMidpointIntermediate: IntermediateEntity | null = null
            let headMidpointIntermediate: IntermediateEntity | null = null
            const guideConnectors: IntermediateEntity[] = []

            const stepSize = Math.max(1, points.length - 1)
            let stepIdx = 0

            for (const point of points) {
                let segmentAlpha = 1
                if (hold.fadeType === 0) {
                    segmentAlpha = 1 - 0.8 * (stepIdx / stepSize)
                } else if (hold.fadeType === 2) {
                    segmentAlpha = 1 - 0.8 * ((stepSize - stepIdx) / stepSize)
                }

                const sonolusColorId = 101 + hold.guideColor

                const midpointIntermediate = createIntermediate('AnchorNote', {
                    '#BEAT': point.tick / TICKS_PER_BEAT,
                    lane: laneToSonolusLane(point.lane, point.width),
                    size: point.width,
                    direction: 0,
                    isAttached: 0,
                    connectorEase:
                        'ease' in point
                            ? mmwEaseToSonolusEase(point.ease)
                            : SONOLUS_CONNECTOR_EASES.linear,
                    isSeparator: 0,
                    segmentKind: sonolusColorId,
                    segmentAlpha: segmentAlpha,
                    segmentLayer: 0,
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

            if (headMidpointIntermediate && prevMidpointIntermediate) {
                for (const conn of guideConnectors) {
                    conn.data.segmentHead = headMidpointIntermediate
                    conn.data.segmentTail = prevMidpointIntermediate
                    conn.data.activeHead = headMidpointIntermediate
                    conn.data.activeTail = prevMidpointIntermediate
                }

                if (hold.fadeType === 2) {
                    headMidpointIntermediate.data.segmentAlpha = 0
                } else if (hold.fadeType === 0) {
                    prevMidpointIntermediate.data.segmentAlpha = 0
                }
            }
        } else {
            let prevJointIntermediate: IntermediateEntity | null = null
            let prevNoteIntermediate: IntermediateEntity | null = null
            let headNoteIntermediate: IntermediateEntity | null = null
            let currentSegmentHead: IntermediateEntity | null = null

            const queuedAttachIntermediates: IntermediateEntity[] = []
            const connectors: IntermediateEntity[] = []
            const pendingSegmentConnectors: IntermediateEntity[] = []

            interface SlideEvent {
                tick: number
                lane: number
                width: number
                type: 'start' | 'end' | 'tick' | 'attach'
                critical: boolean
                friction: boolean
                flick: string
                ease?: EaseType
            }

            const events: SlideEvent[] = []

            events.push({
                tick: hold.start.tick,
                lane: hold.start.lane,
                width: hold.start.width,
                type: 'start',
                critical: hold.start.flags.critical,
                friction: hold.start.flags.friction,
                flick: 'none',
                ease: hold.start.ease,
            })

            for (const step of hold.steps) {
                if (step.type === 'ignored') {
                    events.push({
                        tick: step.tick,
                        lane: step.lane,
                        width: step.width,
                        type: 'attach',
                        critical: hold.start.flags.critical,
                        friction: false,
                        flick: 'none',
                        ease: step.ease,
                    })
                } else {
                    if (step.type === 'visible') {
                        events.push({
                            tick: step.tick,
                            lane: step.lane,
                            width: step.width,
                            type: 'tick',
                            critical: hold.start.flags.critical,
                            friction: false,
                            flick: 'none',
                            ease: step.ease,
                        })
                    } else {
                        events.push({
                            tick: step.tick,
                            lane: step.lane,
                            width: step.width,
                            type: 'attach',
                            critical: hold.start.flags.critical,
                            friction: false,
                            flick: 'none',
                            ease: step.ease,
                        })
                    }
                }
            }

            events.push({
                tick: hold.end.tick,
                lane: hold.end.lane,
                width: hold.end.width,
                type: 'end',
                critical: hold.end.flags.critical,
                friction: hold.end.flags.friction,
                flick: hold.end.flickType,
            })

            events.sort((a, b) => a.tick - b.tick)

            let nextHiddenTickBeat = Math.floor((hold.start.tick / TICKS_PER_BEAT) * 2 + 1) / 2

            for (const event of events) {
                let isSimLineEligible = false
                let isAttached = false
                const name_parts: string[] = []

                if (event.type === 'start') {
                    if (hold.flags.startHidden) {
                        name_parts.push('Anchor')
                    } else {
                        name_parts.push(event.critical ? 'Critical' : 'Normal')
                        name_parts.push('Head')
                        name_parts.push(event.friction ? 'Trace' : 'Tap')
                        isSimLineEligible = true
                    }
                } else if (event.type === 'end') {
                    if (hold.flags.endHidden) {
                        name_parts.push('Anchor')
                    } else {
                        name_parts.push(event.critical ? 'Critical' : 'Normal')
                        name_parts.push('Tail')
                        if (event.flick !== 'none') {
                            name_parts.push(event.friction ? 'TraceFlick' : 'Flick')
                        } else {
                            name_parts.push(event.friction ? 'Trace' : 'Release')
                        }
                        isSimLineEligible = true
                    }
                } else if (event.type === 'tick') {
                    name_parts.push(event.critical ? 'Critical' : 'Normal')
                    name_parts.push('Tick')
                } else {
                    isAttached = true
                    if (event.critical) {
                        name_parts.push('Critical')
                        name_parts.push('Tick')
                    } else {
                        name_parts.push('TransientHiddenTick')
                    }
                }

                name_parts.push('Note')
                let archetype = name_parts.join('')
                if (hold.flags.dummy) archetype = `Fake${archetype}`

                const data: Record<string, number | IntermediateEntity> = {
                    '#BEAT': event.tick / TICKS_PER_BEAT,
                    lane: laneToSonolusLane(event.lane, event.width),
                    size: event.width,
                    isAttached: isAttached ? 1 : 0,
                    connectorEase: event.ease
                        ? mmwEaseToSonolusEase(event.ease)
                        : SONOLUS_CONNECTOR_EASES.linear,
                    isSeparator: 0,
                    segmentKind: event.critical ? 2 : 1,
                    segmentAlpha: 1,
                    segmentLayer: 0,
                    '#TIMESCALE_GROUP': timeScaleGroupRef,
                }

                if (event.flick && event.flick !== 'none') {
                    data.direction = flickTypeToDirection(event.flick)
                } else {
                    data.direction = 0
                }

                const connectionIntermediate = createIntermediate(
                    archetype,
                    data,
                    isSimLineEligible,
                )

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
                            nextHiddenTickBeat + EPSILON <
                            (connectionIntermediate.data['#BEAT'] as number)
                        ) {
                            createIntermediate('TransientHiddenTickNote', {
                                '#BEAT': nextHiddenTickBeat,
                                '#TIMESCALE_GROUP': timeScaleGroupRef,
                                lane: connectionIntermediate.data.lane,
                                size: connectionIntermediate.data.size,
                                direction: 0,
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
                            kind: resolveConnectorKind(event.critical, !!hold.flags.dummy),
                        })
                        connectors.push(connectorIntermediate)
                        pendingSegmentConnectors.push(connectorIntermediate)
                    }
                    prevJointIntermediate = connectionIntermediate
                }

                if (prevNoteIntermediate !== null) {
                    prevNoteIntermediate.data.next = connectionIntermediate
                }
                prevNoteIntermediate = connectionIntermediate
            }

            if (headNoteIntermediate && prevJointIntermediate) {
                if (currentSegmentHead) {
                    for (const conn of pendingSegmentConnectors) {
                        conn.data.segmentHead = currentSegmentHead
                        conn.data.segmentTail = prevJointIntermediate
                    }
                }
                for (const conn of connectors) {
                    conn.data.activeHead = headNoteIntermediate
                    conn.data.activeTail = prevJointIntermediate
                }
            }
        }
    }

    simLineEligibleNotes.sort((a, b) => {
        const beatA = a.data['#BEAT'] as number
        const beatB = b.data['#BEAT'] as number
        if (Math.abs(beatA - beatB) > EPSILON) return beatA - beatB
        const laneA = a.data.lane as number
        const laneB = b.data.lane as number
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
    if (currentSimGroup.length > 0) simGroups.push(currentSimGroup)

    for (const simGroup of simGroups) {
        for (let i = 0; i < simGroup.length - 1; i++) {
            createIntermediate('SimLine', {
                left: simGroup[i],
                right: simGroup[i + 1],
            })
        }
    }

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
        bgmOffset: score.metadata.musicOffset / 1000,
        entities,
    }
}
