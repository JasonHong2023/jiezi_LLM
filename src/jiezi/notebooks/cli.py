"""`scripts/jiezi notebook`（add-notebooks）：透過 gateway 管理筆記本與提問。 / Notebooks from the command line."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _conn():
    from ..cli.client import Connection
    return Connection.from_env()


def _call(method: str, path: str, timeout: float = 900, **kw):
    import httpx
    c = _conn()
    r = httpx.request(method, c.url + path, headers=c.headers, timeout=timeout, **kw)
    data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if r.status_code >= 400:
        raise SystemExit(f"jiezi: {r.status_code} {(data.get('error') or {}).get('message') or r.text[:200]}")
    return data


def _find(name: str) -> dict:
    for n in _call("GET", "/v1/notebooks")["data"]:
        if name in (n["id"], n["name"]):
            return n
    raise SystemExit(f"jiezi: no notebook named {name!r} (scripts/jiezi notebook list)")


def _is_file(item: str) -> bool:
    """長的貼上文字當路徑檢查會丟 OSError（檔名太長），視為不是檔案。 / Long pasted text is not a path."""
    try:
        return len(item) < 4096 and Path(item).expanduser().is_file()
    except (OSError, ValueError):
        return False


def main(args) -> int:
    cmd = args.nb_cmd
    if cmd == "list":
        for n in _call("GET", "/v1/notebooks")["data"]:
            print(f"{n['name']:<24} {n['sources']} 份來源  更新 {n.get('updated_at', '')[:16]}  ({n['id']})")
        return 0
    if cmd == "new":
        n = _call("POST", "/v1/notebooks", json={"name": args.name, "description": args.description or ""})
        print(f"已建立《{n['name']}》({n['id']})")
        return 0
    nb = _find(args.notebook)
    if cmd == "show":
        d = _call("GET", f"/v1/notebooks/{nb['id']}")
        for s in d["sources"]:
            warn = "  ⚠ 可疑內容" if (s.get("trust") or {}).get("injection") else ""
            print(f"{s['kind']:<6} {s['title']}  {s['chars']} 字  {s.get('origin', '')}{warn}  ({s['id']})")
        return 0
    if cmd == "add":
        for item in args.items:
            if item.startswith(("http://", "https://")):
                r = _call("POST", f"/v1/notebooks/{nb['id']}/sources", json={"url": item})
            elif _is_file(item):
                p = Path(item).expanduser()
                with p.open("rb") as f:
                    r = _call("POST", f"/v1/notebooks/{nb['id']}/sources", timeout=3600, files={"file": (p.name, f)})
            else:
                r = _call("POST", f"/v1/notebooks/{nb['id']}/sources", json={"text": item, "title": item[:20]})
            s = r["source"]
            print(f"{'已加入' if r['created'] else '已存在'}：{s['title']}（{s['chars']} 字，{s['chunks']} 段）")
        return 0
    if cmd == "rm":
        if args.source:
            print(_call("DELETE", f"/v1/notebooks/{nb['id']}/sources/{args.source}"))
        else:
            print(_call("DELETE", f"/v1/notebooks/{nb['id']}"))
        return 0
    if cmd == "ask":
        r = _call("POST", "/v1/chat/completions", json={
            "model": "jiezi", "jiezi_notebook": nb["id"], "jiezi_notebook_general": args.general,
            "messages": [{"role": "user", "content": args.question}]})
        if args.json:
            print(json.dumps(r, ensure_ascii=False, indent=1))
            return 0
        print(r["choices"][0]["message"]["content"])
        mem = ((r.get("jiezi") or {}).get("notebook") or {}).get("memory") or {}
        if mem.get("saved"):
            sys.stderr.write("jiezi: 已查證並存進記憶\n")
        elif mem.get("findings"):
            sys.stderr.write("jiezi: 查證發現（沒有存進記憶）：\n" + "".join(f"  - {f['message']}\n" for f in mem["findings"])
                             + f"  仍要存：scripts/jiezi notebook remember {nb['name']} {r['jiezi']['trajectory_id']}\n")
        return 0
    if cmd == "remember":
        print(_call("POST", f"/v1/notebooks/{nb['id']}/remember", json={"trajectory_id": args.trajectory_id}))
        return 0
    return 2


def add_parser(sub) -> None:
    p = sub.add_parser("notebook", help="notebooks of sources with cited answers (add-notebooks)")
    s = p.add_subparsers(dest="nb_cmd", required=True)
    s.add_parser("list")
    n = s.add_parser("new")
    n.add_argument("name")
    n.add_argument("--description")
    sh = s.add_parser("show", help="list a notebook's sources")
    sh.add_argument("notebook")
    a = s.add_parser("add", help="add files (PDF, Word, audio…), URLs or text")
    a.add_argument("notebook")
    a.add_argument("items", nargs="+")
    q = s.add_parser("ask")
    q.add_argument("notebook")
    q.add_argument("question")
    q.add_argument("--general", action="store_true", help="allow general knowledge, marked as not from the sources")
    q.add_argument("--json", action="store_true")
    r = s.add_parser("rm", help="delete a notebook, or one source with --source")
    r.add_argument("notebook")
    r.add_argument("--source")
    m = s.add_parser("remember", help="save an answer whose checks failed, after reading the findings")
    m.add_argument("notebook")
    m.add_argument("trajectory_id")
