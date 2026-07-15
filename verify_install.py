import sys
import pathlib
import py_compile

print("python:", sys.version.split()[0], "->", sys.executable)

REQUIRED = [
    "engine/db.py", "engine/collectors.py", "engine/scheduler.py",
    "workflows/segments.py", "workflows/analysis.py", "workflows/collect_jobs.py",
    "web/routes_results.py", "web/routes_analyze.py", "web/routes_schedule.py",
    "web/server.py", "web/render.py", "web/config_meta.py", "web/assets.py", "web/roles.py",
    "web/user/layout.py", "web/user/nav.py", "web/user/routes_home.py",
    "web/user/errors.py", "web/user/cards.py", "web/user/routes_inbox.py",
    "workflows/work.py",
    "web/static/user/tokens.css", "web/static/user/base.css",
    "web/static/user/components.css",
    "config/defaults/150_results.json", "config/defaults/20_schedule.json", "app.py",
]

missing = [f for f in REQUIRED if not pathlib.Path(f).exists()]
if missing:
    for f in missing:
        print("MISSING ", f)
    print("\nInstall incomplete: unpack the bundle again.")
    sys.exit(1)
print("files    OK (%d)" % len(REQUIRED))

bad = []
for f in REQUIRED:
    if f.endswith(".py"):
        try:
            py_compile.compile(f, doraise=True, quiet=1)
        except py_compile.PyCompileError as exc:
            bad.append(f"{f}: {exc.exc_value}")
if bad:
    print("\nSYNTAX ERRORS (your Python is too old for this code):")
    for b in bad:
        print(" ", b)
    sys.exit(1)
print("compile  OK")

try:
    import workflows.segments        # noqa: F401
    import workflows.collect_jobs    # noqa: F401
    import workflows.analysis        # noqa: F401
    import engine.scheduler          # noqa: F401
    import web.routes_schedule       # noqa: F401
    import web.routes_results        # noqa: F401
    import web.routes_analyze        # noqa: F401
    from web.server import create_app  # noqa: F401
except Exception as exc:
    print(f"IMPORT FAILED: {type(exc).__name__}: {exc}")
    sys.exit(1)
print("imports  OK")

import inspect
from engine.collectors import _store_item
if "origin" not in inspect.signature(_store_item).parameters:
    print("STALE engine/collectors.py"); sys.exit(1)
from workflows.analysis import SCOPES
if "not_new" not in SCOPES:
    print("STALE workflows/analysis.py"); sys.exit(1)
from web.user.layout import SHEETS
if "user/tokens.css" not in SHEETS:
    print("STALE web/user/layout.py"); sys.exit(1)
from engine import accounts
if not hasattr(accounts, "set_role"):
    print("STALE engine/accounts.py"); sys.exit(1)
from engine.db import SCHEMA_WORK
if "tender_work" not in SCHEMA_WORK:
    print("STALE engine/db.py"); sys.exit(1)
print("versions OK")
print("\nInstall looks good. Restart the service.")
