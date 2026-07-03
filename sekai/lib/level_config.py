from enum import IntEnum

from sonolus.script.globals import level_data

from sekai.lib.options import Options, ScoreMode, Version


class EngineRevision(IntEnum):
    BASE = 0
    SONOLUS_1_1_0 = 1
    GAUGE_REWORK = 2

    LATEST = 2


GAUGE_LIFE_UNIT = 10
GAUGE_MAX_LIFE = 1000 * GAUGE_LIFE_UNIT


@level_data
class LevelConfig:
    revision: EngineRevision
    score_mode: ScoreMode
    dynamic_stages: bool
    has_stage_transforms: bool
    skip_default_stage: bool
    ui_version: Version
    particle_version: Version


def init_level_config(
    revision: EngineRevision = EngineRevision.LATEST,
):
    LevelConfig.revision = revision
    if revision >= EngineRevision.SONOLUS_1_1_0:
        LevelConfig.score_mode = Options.score_mode
    else:
        LevelConfig.score_mode = ScoreMode.WEIGHTED_COMBO


def init_ui_version(ui_version: Version):
    LevelConfig.ui_version = ui_version


def init_particle_version(particle_version: Version):
    LevelConfig.particle_version = particle_version
