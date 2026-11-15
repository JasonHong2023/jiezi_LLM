"""`scripts/jiezi check-clients`：唯讀檢查並列出 Hermes Agent / OpenCode 的建議設定，**不寫入任何設定檔**
（規格 cli：Read-Only Client Check；add-cli design D7）。
Read-only check that lists suggested Hermes Agent / OpenCode settings; **writes no config file**."""

from __future__ import annotations

import json
import sys

import httpx

from .client import Connection


def main() -> int:
    conn = Connection.from_env()
    if not conn.key:
        print("JIEZI_GATEWAY_KEY is not set; run scripts/jiezi init-key", file=sys.stderr)
        return 3
    try:
        r = httpx.get(f"{conn.url}/v1/models", headers=conn.headers, timeout=5)
    except httpx.HTTPError:
        print(f"gateway not reachable at {conn.url}; start it with scripts/jiezi serve", file=sys.stderr)
        return 2
    if r.status_code != 200:
        print(f"gateway answered {r.status_code}: {r.text[:200]}", file=sys.stderr)
        return 3
    ids = [m["id"] for m in r.json().get("data", [])]
    print(f"gateway OK at {conn.url}; policies: {', '.join(ids)}\n")
    print("以下只是建議，本指令不會修改任何設定 / Suggestions only; this command changes nothing.\n")
    print("Hermes Agent:")
    print(f"  hermes config set model.base_url {conn.url}/v1")
    print("  hermes config set model.default jiezi")
    print("  hermes config set model.api_key <JIEZI_GATEWAY_KEY from .env>\n")
    print("OpenCode (provider entry in opencode.jsonc):")
    print(json.dumps({"provider": {"jiezi": {"npm": "@ai-sdk/openai-compatible", "name": "Jiezi",
                                              "options": {"baseURL": f"{conn.url}/v1",
                                                          "apiKey": "<JIEZI_GATEWAY_KEY>"},
                                              "models": {i: {"name": i} for i in ids}}}}, indent=2))
    return 0
