import { DatabaseEngineItem, LevelData } from '@sonolus/core'
import { isExtendedLevelData } from './extended/analyze.js'
import {
    type ExtendedEntityData,
    type ExtendedEntityDataField,
    extendedToLevelData,
} from './extended/convert.js'
import { isLevelData } from './LevelData/analyze.js'
import { detectMMWSType } from './mmw/analyze.js'
import { mmwsToUSC, ucmmwsToLevelData } from './mmw/convert.js'
import { susToUSC } from './sus/convert.js'
import { isUSC } from './usc/analyze.js'
import { uscToLevelData } from './usc/convert.js'
import { USC } from './usc/index.js'

export * from './usc/index.js'
export {
    type ExtendedEntityData,
    type ExtendedEntityDataField,
    extendedToLevelData,
    mmwsToUSC,
    susToUSC,
    ucmmwsToLevelData,
    uscToLevelData,
}

export const convertToLevelData = (
    input: string | Uint8Array | USC | LevelData,
    offset = 0,
): LevelData => {
    if (isExtendedLevelData(input)) {
        const converted = extendedToLevelData(input, offset)
        if (converted) return converted
    }
    if (isLevelData(input)) {
        return input
    }
    let usc: USC
    if (isUSC(input)) {
        usc = input
    } else if (input instanceof Uint8Array) {
        const type = detectMMWSType(input)
        if (type === 'UCMMWS') {
            return ucmmwsToLevelData(input)
        }
        if (type === 'MMWS' || type === 'CCMMWS') {
            usc = mmwsToUSC(input)
            if (type === 'MMWS') {
                return uscToLevelData(usc, offset, true, true)
            } else {
                return uscToLevelData(usc, offset, false, false)
            }
        }
        throw new Error('Unsupported Uint8Array type for MMWS')
    } else if (typeof input === 'string') {
        try {
            const parsed = JSON.parse(input)
            if (isExtendedLevelData(parsed)) {
                const converted = extendedToLevelData(parsed, offset)
                if (converted) return converted
            }
            if (isLevelData(parsed)) {
                return parsed
            }
            if (isUSC(parsed)) {
                usc = parsed
                return uscToLevelData(usc, offset, false, false)
            } else {
                usc = susToUSC(input)
            }
        } catch {
            usc = susToUSC(input)
        }
    } else {
        throw new Error(
            'Unsupported input type: Input must be string(SUS/USC/LevelData), Uint8Array(MMWS), or USC/LevelData object.',
        )
    }
    return uscToLevelData(usc, offset, true, true)
}

export const version = '0.0.0'

export const engineFullName = {
    en: 'Next SEKAI',
} as const

export const engineShortName = {
    en: 'Next SEKAI',
} as const

export const databaseEngineItem = {
    name: 'next-rush',
    version: 13,
    title: {
        en: 'Next RUSH',
    },
    subtitle: {
        en: 'Next RUSH',
    },
    author: {
        en: 'Next RUSH',
    },
    description: {
        en: [`Version: ${version}`].join('\n'),
    },
} as const satisfies Partial<DatabaseEngineItem>
