from __future__ import annotations

from .contracts import Stage

_REGISTRY: dict[str, type[Stage]] = {}


def register(name: str):
    def deco(cls: type[Stage]):
        cls.name = name
        _REGISTRY[name] = cls
        return cls
    return deco


def get_stage(name: str) -> Stage:
    if name not in _REGISTRY:
        raise KeyError(f"stage not registered: {name}")
    return _REGISTRY[name]()


def has_stage(name: str) -> bool:
    return name in _REGISTRY


def all_stages() -> list[str]:
    return sorted(_REGISTRY)
