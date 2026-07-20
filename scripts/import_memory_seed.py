#!/usr/bin/env python3
"""Import crucible worklogs and rome experiment results as conversation memory.

Creates simulated conversation sessions from markdown worklogs so that
EverOS user-memory pipeline (Episode/Profile/Fact extraction) can process them.

Each worklog file → one conversation session → one flush → one Episode.
Does NOT interfere with real-time mem_save_fact/mem_save_turn MCP operations.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys_path = str(ROOT / "scripts")
import sys

sys.path.insert(0, sys_path)

from everos.service.memorize import memorize
from everos.entrypoints.api.routes.memorize import MemorizeAddRequest, MessageItemDTO

APP_ID = "opencode"
PROJECT_ID = "noctua"
USER_ID = "mengzhilu"

# ── Sources ──────────────────────────────────────────────────────────
# (relative_path, domain_tag, context_prefix)
SOURCES: list[tuple[str, str, str]] = [
    # Crucible worklog checkpoints
    ("crucible/worklog/checkpoints", "crucible", "Crucible检查点"),
    # Crucible worklog guides
    ("crucible/worklog/guides", "crucible", "Crucible开发指南"),
    # Crucible agent skills
    ("crucible/.agents/skills", "crucible", "Crucible Agent Skill"),
    # Crucible share
    ("crucible/share", "crucible", "Crucible共享知识"),
    # Rome todos / roadmap
    ("rome/rubicon/todos", "rome", "Rome路线图"),
    # Rome worklog
    ("rome/rubicon/worklog", "rome", "Rome工作日志"),
]

MAX_FILES = 30  # safety cap
DRY_RUN = False
SLEEP_BETWEEN = 1  # seconds between flushes (gentle on API)


def _build_session_id(path: Path) -> str:
    """Stable session_id from file path. Re-imports of same file use same session."""
    return f"seed-{path.parent.name}-{path.stem}"[:128]


def _file_to_messages(path: Path, context: str) -> list[dict]:
    """Convert a markdown file into simulated user messages (2 msgs to trigger boundary)."""
    content = path.read_text(encoding="utf-8", errors="replace")
    if len(content) > 40000:
        content = content[:40000] + "\n\n... (truncated)"

    src = str(path.relative_to(ROOT))
    now_ms = int(time.time() * 1000)
    return [
        {
            "sender_id": USER_ID,
            "role": "user",
            "timestamp": now_ms,
            "content": f"[{context}] 请记录这份工作日志: {src}",
        },
        {
            "sender_id": USER_ID,
            "role": "user",
            "timestamp": now_ms + 1000,
            "content": content,
        },
    ]


async def import_file(path: Path, context: str) -> bool:
    session_id = _build_session_id(path)
    msgs = _file_to_messages(path, context)

    if DRY_RUN:
        print(f"  [DRY RUN] {session_id} ({len(msgs)} msgs)")
        return True

    try:
        result = await memorize({
            "session_id": session_id,
            "app_id": APP_ID,
            "project_id": PROJECT_ID,
            "messages": msgs,
            "flush": True,
        })
        print(f"  OK: {path.name} → session={session_id} status={result.status}")
        return True
    except Exception as e:
        print(f"  ERR {path.name}: {str(e)[:120]}")
        return False


async def main():
    print("Noctua Memory Seed Importer (Plan B)\n")

    # Collect files
    to_import: list[tuple[Path, str]] = []
    for rel, domain, context in SOURCES:
        scan = ROOT / rel
        if not scan.exists():
            print(f"SKIP (not found): {scan}")
            continue
        for f in sorted(scan.rglob("*.md")):
            to_import.append((f, f"{domain}/{context}"))

    # Deduplicate by stem
    seen = set()
    unique: list[tuple[Path, str]] = []
    for f, ctx in to_import:
        key = f.stem
        if key not in seen:
            seen.add(key)
            unique.append((f, ctx))

    unique = unique[:MAX_FILES]
    print(f"Will import {len(unique)} files (cap={MAX_FILES})\n")

    ok = 0
    for i, (f, ctx) in enumerate(unique):
        rel = f.relative_to(ROOT)
        print(f"[{i+1}/{len(unique)}] {rel}")
        if await import_file(f, ctx):
            ok += 1
        if SLEEP_BETWEEN and not DRY_RUN:
            await asyncio.sleep(SLEEP_BETWEEN)

    print(f"\nDone: {ok}/{len(unique)} imported")


if __name__ == "__main__":
    if "--dry" in sys.argv:
        DRY_RUN = True
        print("=== DRY RUN MODE ===\n")
    asyncio.run(main())
