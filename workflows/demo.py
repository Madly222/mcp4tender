from __future__ import annotations

from engine.contracts import Stage, StageContext, StageResult
from engine.registry import register


@register("dummy_echo")
class DummyEcho(Stage):
    consumes = ()
    produces = ("message",)

    def run(self, ctx: StageContext) -> StageResult:
        message = ctx.config.get("dummy.message", "hello")
        return StageResult(payload={**ctx.payload, "message": message})


@register("dummy_shout")
class DummyShout(Stage):
    consumes = ("message",)
    produces = ("shout",)

    def run(self, ctx: StageContext) -> StageResult:
        text = str(ctx.payload["message"])
        return StageResult(payload={**ctx.payload, "shout": text.upper() + "!"})


@register("dummy_flaky")
class DummyFlaky(Stage):
    consumes = ()
    produces = ("flaky_ok",)

    def __init__(self):
        self.attempts = 0

    def run(self, ctx: StageContext) -> StageResult:
        self.attempts += 1
        fail_times = int(ctx.config.get("dummy.flaky_fail_times", 0))
        if self.attempts <= fail_times:
            raise RuntimeError(f"transient failure {self.attempts}")
        return StageResult(payload={**ctx.payload, "flaky_ok": self.attempts})
