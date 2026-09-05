import {
    USC,
    USCConnectionAttachNote,
    USCConnectionEndNote,
    USCConnectionStartNote,
    USCConnectionTickNote,
    USCGuideNote,
    USCObject,
    USCSlideNote,
} from '../usc/index.js'
import { analyze, NoteObject, Score } from './analyze.js'

/** Convert a SUS to a USC */
export const susToUSC = (sus: string): USC => chsLikeToUSC(analyze(sus))

export const chsLikeToUSC = (score: Score): USC => {
    const flickMods = new Map<string, 'left' | 'up' | 'right'>()
    const traceMods = new Set<string>()
    const criticalMods = new Set<string>()
    const tickRemoveMods = new Set<string>()
    const slideStartEndRemoveMods = new Set<string>()
    const easeMods = new Map<string, 'in' | 'out'>()

    const preventSingles = new Set<string>()
    const dedupeSingles = new Set<string>()
    const dedupeSlides = new Map<string, USCSlideNote | USCGuideNote>()
    const removedSlides = new Set<USCObject>()

    const requests = {
        sideLane: false,
        laneOffset: 0,
    }
    const requestsRaw = score.meta.get('REQUEST')
    if (requestsRaw) {
        for (const request of requestsRaw) {
            try {
                const [key, value] = JSON.parse(request).split(' ', 2)
                switch (key) {
                    case 'side_lane':
                        requests.sideLane = value === 'true'
                        break
                    case 'lane_offset':
                        requests.laneOffset = Number(value)
                        break
                }
            } catch {
                // Noop
            }
        }
    }

    for (const slide of score.slides) {
        if (slide.type !== 3) continue

        for (const note of slide.notes) {
            const key = getKey(note)
            switch (note.type) {
                case 1:
                case 2:
                case 3:
                case 5:
                    preventSingles.add(key)
                    break
            }
        }
    }

    for (const note of score.directionalNotes) {
        const key = getKey(note)
        switch (note.type) {
            case 1:
                flickMods.set(key, 'up')
                break
            case 3:
                flickMods.set(key, 'left')
                break
            case 4:
                flickMods.set(key, 'right')
                break
            case 2:
                easeMods.set(key, 'in')
                break
            case 5:
            case 6:
                easeMods.set(key, 'out')
                break
        }
    }
    for (const note of score.tapNotes) {
        const key = getKey(note)
        switch (note.type) {
            case 2:
                criticalMods.add(key)
                break
            case 5:
                traceMods.add(key)
                break
            case 6:
                traceMods.add(key)
                criticalMods.add(key)
                break
            case 3:
                tickRemoveMods.add(key)
                break
            case 7:
                slideStartEndRemoveMods.add(key)
                break
            case 8:
                criticalMods.add(key)
                slideStartEndRemoveMods.add(key)
                break
        }
    }

    const objects: USCObject[] = []

    for (const timeScaleChanges of score.timeScaleChanges) {
        objects.push({
            type: 'timeScaleGroup',
            changes: timeScaleChanges.map((timeScaleChange) => ({
                beat: timeScaleChange.tick / score.ticksPerBeat,
                timeScale: timeScaleChange.timeScale,
            })),
        })
    }

    for (const bpmChange of score.bpmChanges) {
        objects.push({
            type: 'bpm',
            beat: bpmChange.tick / score.ticksPerBeat,
            bpm: bpmChange.bpm,
        })
    }

    for (const note of score.tapNotes) {
        if (note.lane === 0 && note.type === 4) {
            objects.push({
                type: 'skill',
                beat: note.tick / score.ticksPerBeat,
            })
            continue
        }

        if (note.lane === 15 && note.type === 1) {
            objects.push({
                type: 'feverChance',
                beat: note.tick / score.ticksPerBeat,
            })
            continue
        }

        if (note.lane === 15 && note.type === 2) {
            objects.push({
                type: 'feverStart',
                beat: note.tick / score.ticksPerBeat,
            })
            continue
        }

        if (!requests.sideLane && (note.lane <= 1 || note.lane >= 14)) continue
        if (
            note.type !== 1 &&
            note.type !== 2 &&
            note.type !== 5 &&
            note.type !== 6 &&
            note.type !== 4
        )
            continue

        const key = getKey(note)
        if (preventSingles.has(key)) continue

        if (dedupeSingles.has(key)) continue
        dedupeSingles.add(key)

        let object: USCObject
        switch (note.type) {
            case 1:
            case 2:
            case 5:
            case 6: {
                object = {
                    type: 'single',
                    beat: note.tick / score.ticksPerBeat,
                    lane: note.lane - 8 + note.width / 2 + requests.laneOffset,
                    size: note.width / 2,
                    critical: [2, 6].includes(note.type),
                    trace: [5, 6].includes(note.type),

                    timeScaleGroup: note.timeScaleGroup,
                }

                const flickMod = flickMods.get(key)
                if (flickMod) object.direction = flickMod
                break
            }
            case 4:
                object = {
                    type: 'damage',
                    beat: note.tick / score.ticksPerBeat,
                    lane: note.lane - 8 + note.width / 2 + requests.laneOffset,
                    size: note.width / 2,

                    timeScaleGroup: note.timeScaleGroup,
                }
                break
            default:
                continue
        }

        objects.push(object)
    }

    for (const slide of score.slides) {
        const startNote = slide.notes.find(({ type }) => type === 1 || type === 2)
        if (!startNote) continue

        const object: USCSlideNote = {
            type: slide.type === 3 ? 'slide' : 'guide',
            critical: criticalMods.has(getKey(startNote)),
            connections: [] as never,
        }

        for (const note of slide.notes) {
            const key = getKey(note)

            const beat = note.tick / score.ticksPerBeat
            const lane = note.lane - 8 + note.width / 2 + requests.laneOffset
            const size = note.width / 2
            const timeScaleGroup = note.timeScaleGroup
            const critical = ('critical' in object && object.critical) || criticalMods.has(key)
            const ease = easeMods.get(key) ?? 'linear'

            let judgeType: 'normal' | 'trace' | 'none' = 'normal'
            if (traceMods.has(key)) judgeType = 'trace'
            switch (note.type) {
                case 1: {
                    if (object.type == 'guide' || slideStartEndRemoveMods.has(key)) {
                        const connection: USCConnectionStartNote = {
                            type: 'start',
                            beat,
                            lane,
                            size,
                            critical,
                            ease,
                            judgeType: 'none',

                            timeScaleGroup,
                        }

                        object.connections.push(connection)
                    } else {
                        const connection: USCConnectionStartNote = {
                            type: 'start',
                            beat,
                            lane,
                            size,
                            critical,
                            ease: easeMods.get(key) ?? 'linear',
                            judgeType,

                            timeScaleGroup,
                        }

                        object.connections.push(connection)
                    }
                    break
                }
                case 2: {
                    if (object.type == 'guide' || slideStartEndRemoveMods.has(key)) {
                        const connection: USCConnectionEndNote = {
                            type: 'end',
                            beat,
                            lane,
                            size,
                            critical,
                            judgeType: 'none',

                            timeScaleGroup,
                        }
                        object.connections.push(connection)
                    } else {
                        const connection: USCConnectionEndNote = {
                            type: 'end',
                            beat,
                            lane,
                            size,
                            critical,
                            judgeType,

                            timeScaleGroup,
                        }

                        const flickMod = flickMods.get(key)
                        if (flickMod) connection.direction = flickMod
                        object.connections.push(connection)
                    }
                    break
                }
                case 3: {
                    if (tickRemoveMods.has(key)) {
                        const connection: USCConnectionAttachNote = {
                            type: 'attach',
                            beat,
                            critical,
                            timeScaleGroup,
                        }

                        object.connections.push(connection)
                    } else {
                        const connection: USCConnectionTickNote = {
                            type: 'tick',
                            beat,
                            lane,
                            size,
                            critical,
                            ease,
                            judgeType,

                            timeScaleGroup,
                        }

                        object.connections.push(connection)
                    }
                    break
                }
                case 5: {
                    if (tickRemoveMods.has(key)) break

                    const connection: USCConnectionTickNote = {
                        type: 'tick',
                        beat,
                        lane,
                        size,
                        ease,

                        timeScaleGroup,
                    }

                    object.connections.push(connection)
                    break
                }
            }
        }

        objects.push(object)

        if (object.type == 'guide') continue

        const key = getKey(startNote)
        const dupe = dedupeSlides.get(key)
        if (dupe) removedSlides.add(dupe)

        dedupeSlides.set(key, object)
    }

    return {
        offset: score.offset,
        objects: removedSlides.size
            ? objects.filter((object) => !removedSlides.has(object))
            : objects,
    }
}

const getKey = (note: NoteObject) => `${note.lane}-${note.tick}`
