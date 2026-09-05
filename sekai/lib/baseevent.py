from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast

from sonolus.script.archetype import EntityRef, entity_data
from sonolus.script.array import Array, Dim

if TYPE_CHECKING:
    from sonolus.script.archetype import _BaseArchetype

    _BaseEventBase = _BaseArchetype
else:
    _BaseEventBase = object


class BaseEvent(_BaseEventBase):
    next_ref: EntityRef[Any] = entity_data()
    prev_ref: EntityRef[Any] = entity_data()
    skip_refs: Array[EntityRef[Any], Dim[15]] = entity_data()
    skip_levels: int = entity_data()


def get_event_as[T](ref: EntityRef, archetype: type[T]) -> T:
    """Typed wrapper around EntityRef.get_as that preserves the archetype's type (including Protocol types)."""
    return cast(T, ref.with_archetype(cast(Any, archetype)).get())


def init_event_list[T: BaseEvent](first_ref: EntityRef[T]):  # pyright: ignore[reportInvalidTypeArguments]
    if first_ref.index <= 0:
        return

    last_refs = +Array[EntityRef[Any], Dim[15]]
    for i in range(len(last_refs)):
        last_refs[i] = first_ref

    i = 1
    current_ref = +first_ref.get().next_ref
    while current_ref.index > 0:
        current = current_ref.get()
        current.prev_ref.index = last_refs[0].index
        for j in range(len(last_refs)):
            if i % (2**j) == 0:
                get_event_as(last_refs[j], first_ref.archetype()).skip_refs[j].index = current_ref.index
                last_refs[j].index = current_ref.index
        current_ref.index = current.next_ref.index
        i += 1

    first = first_ref.get()
    for i in range(len(last_refs)):
        if first.skip_refs[i].index == 0:
            first.skip_levels = i
            break
    else:
        first.skip_levels = len(last_refs)


def query_event_list[T: BaseEvent, K: float](
    first_ref: EntityRef[T],  # pyright: ignore[reportInvalidTypeArguments]
    key: K,
    accessor: Callable[[T], K],
) -> tuple[EntityRef[T], EntityRef[T]]:  # pyright: ignore[reportInvalidTypeArguments]
    ref_type = type(first_ref)
    a = ref_type(0)
    b = ref_type(0)
    result = (a, b)
    if first_ref.index <= 0:
        return result
    first = first_ref.get()
    if accessor(first) > key:
        b.index = first_ref.index
        return result
    a.index = first_ref.index
    level = first.skip_levels - 1
    while level >= 0:
        next_skip = +a.get().skip_refs[level].with_archetype(type(first))  # pyright: ignore[reportArgumentType]
        while next_skip.index > 0 and accessor(next_skip.get()) <= key:
            a.index = next_skip.index
            next_skip.index = a.get().skip_refs[level].index
        level -= 1
    b.index = a.get().next_ref.index
    return result
