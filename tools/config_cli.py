from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import bootstrap


def main():
    p = argparse.ArgumentParser(description="tender engine config editor")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    g = sub.add_parser("get")
    g.add_argument("key")
    s = sub.add_parser("set")
    s.add_argument("key")
    s.add_argument("value", help="JSON value; if not valid JSON, stored as string")
    h = sub.add_parser("history")
    h.add_argument("key")
    rb = sub.add_parser("rollback")
    rb.add_argument("key")
    rb.add_argument("version", type=int)
    args = p.parse_args()

    conn, store, _ = bootstrap()

    if args.command == "list":
        for k, v in sorted(store.all().items()):
            print(f"{k} = {json.dumps(v, ensure_ascii=False)}")
    elif args.command == "get":
        print(json.dumps(store.get(args.key), ensure_ascii=False, indent=2))
    elif args.command == "set":
        try:
            value = json.loads(args.value)
        except json.JSONDecodeError:
            value = args.value
        version = store.set(args.key, value, actor="cli")
        print(f"{args.key} -> v{version}")
    elif args.command == "history":
        for h in store.history(args.key):
            active = "*" if h["active"] else " "
            print(f"{active} v{h['version']}  {h['actor']}  {h['note']}")
    elif args.command == "rollback":
        version = store.rollback(args.key, args.version, actor="cli")
        print(f"{args.key} rolled back -> new v{version}")


if __name__ == "__main__":
    main()
