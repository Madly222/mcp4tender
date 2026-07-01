from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Protocol


class ConfigView(Protocol):
    def get(self, key: str, default: Any = None) -> Any: ...


@dataclass
class StageContext:
    payload: dict[str, Any]
    config: ConfigView
    db: Any
    run_id: str
    tender_id: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class StageResult:
    payload: dict[str, Any]
    status: str = "ok"
    metrics: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


class Stage(ABC):
    name: str = ""
    consumes: tuple[str, ...] = ()
    produces: tuple[str, ...] = ()

    def validate_input(self, ctx: StageContext) -> None:
        missing = [k for k in self.consumes if k not in ctx.payload]
        if missing:
            raise KeyError(f"{self.name}: missing input keys {missing}")

    @abstractmethod
    def run(self, ctx: StageContext) -> StageResult: ...
