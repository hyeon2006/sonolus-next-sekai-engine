from enum import IntEnum
from typing import assert_never

from sonolus.script.easing import ease_in_out_quad, ease_in_quad, ease_out_in_quad, ease_out_quad, linstep
from sonolus.script.interval import unlerp_clamped


class EaseType(IntEnum):
    NONE = 0
    LINEAR = 1
    IN_QUAD = 2
    OUT_QUAD = 3
    IN_OUT_QUAD = 4
    OUT_IN_QUAD = 5


def safe_unlerp_clamped(a: float, b: float, x: float, fallback: float = 0.5) -> float:
    if abs(a - b) < 1e-6:
        return fallback
    return unlerp_clamped(a, b, x)


def ease(ease_type: EaseType, x: float) -> float:
    match ease_type:
        case EaseType.NONE:
            return 0.0 if x <= 1 else 1.0
        case EaseType.LINEAR:
            return linstep(x)
        case EaseType.IN_QUAD:
            return ease_in_quad(x)
        case EaseType.OUT_QUAD:
            return ease_out_quad(x)
        case EaseType.IN_OUT_QUAD:
            return ease_in_out_quad(x)
        case EaseType.OUT_IN_QUAD:
            return ease_out_in_quad(x)
        case _:
            assert_never(ease_type)
