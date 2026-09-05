# NEXT RUSH Sonolus Engine

Perspective-lane rhythm game for [Sonolus](https://sonolus.com).

## Documentation

### `version`

Package version.

### `engineFullName`

Engine full name.

### `engineShortName`

Engine short name.

### `databaseEngineItem`

Partial database engine item compatible with [sonolus-express](https://github.com/Sonolus/sonolus-express).

### `susToUSC(sus)`

Converts sus chart to USC.

- `sus`: sus chart.

### `uscToLevelData(usc, offset?)`

Converts USC to Level Data.

- `usc`: usc chart.
- `offset`: offset (default: `0`).

### Assets

The following assets are exposed as package entry points:

- `EngineConfiguration`
- `EnginePlayData`
- `EngineWatchData`
- `EnginePreviewData`
- `EngineTutorialData`
- `EngineRom`
- `EngineThumbnail`
