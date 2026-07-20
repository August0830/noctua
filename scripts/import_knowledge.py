#!/usr/bin/env python3
"""Batch import markdown documents from rome/ and crucible/ into EverOS Knowledge Wiki.

Reads .md files from the symlinked directories and uploads them as knowledge documents.
Skips already-imported files based on source_name.
Does NOT go through the conversation memory pipeline — uses the fast Knowledge pipeline.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

NOCTUA_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(NOCTUA_ROOT / "scripts"))

from everos.core.persistence.memory_root import MemoryRoot
from everos.entrypoints.api.routes.knowledge import _build_extractor, _parse_upload
from everos.service.knowledge import create_document

APP_ID = "opencode"
PROJECT_ID = "noctua"

# Directories to scan (relative to noctua root)
SCAN_DIRS = [
    ("rome/rubicon/docs", "rome"),
    ("crucible/share", "crucible"),
    ("crucible/worklog/guides", "crucible"),
]

# File patterns to include
INCLUDE_GLOBS = ["*.md", "*.MD"]

# Max file size to import (5 MB)
MAX_SIZE_BYTES = 5 * 1024 * 1024


class DummyUploadFile:
    """Minimal UploadFile-compatible object for _parse_upload."""

    def __init__(self, path: Path):
        self.filename = path.name
        self._path = path
        self.size = path.stat().st_size
        # Guess content_type from extension
        ext = path.suffix.lower()
        self.content_type = {
            ".md": "text/markdown",
            ".txt": "text/plain",
            ".json": "application/json",
            ".yaml": "application/x-yaml",
            ".yml": "application/x-yaml",
        }.get(ext, "application/octet-stream")

    async def read(self) -> bytes:
        return self._path.read_bytes()


async def import_file(path: Path, source_type: str) -> bool:
    if path.stat().st_size > MAX_SIZE_BYTES:
        print(f"  SKIP (too large {path.stat().st_size}B): {path.name}")
        return False

    try:
        dummy = DummyUploadFile(path)
        file_content = await dummy.read()
        parsed = await _parse_upload(dummy, raw_bytes=file_content)
    except Exception as e:
        print(f"  ERROR parsing {path.name}: {e}")
        return False

    title = path.stem
    knowledge_dir = MemoryRoot.default().knowledge_dir(APP_ID, PROJECT_ID)
    extractor = _build_extractor()

    try:
        result = await create_document(
            extractor=extractor,
            parsed=parsed,
            title=title,
            knowledge_dir=knowledge_dir,
            source_name=path.name,
            source_type=source_type,
            file_content=file_content,
        )
        print(f"  OK: {path.name} → id={result.doc_id}")
        return True
    except Exception as e:
        error_msg = str(e)[:120]
        print(f"  ERROR importing {path.name}: {error_msg}")
        return False


async def main():
    print("Noctua Knowledge Importer")
    print("=========================\n")

    root = NOCTUA_ROOT
    total_ok, total_fail = 0, 0

    for scan_dir, source_type in SCAN_DIRS:
        scan_path = root / scan_dir
        if not scan_path.exists():
            print(f"SKIP (not found): {scan_path}")
            continue

        print(f"Scanning: {scan_path}")
        md_files: list[Path] = []
        for glob in INCLUDE_GLOBS:
            md_files.extend(sorted(scan_path.rglob(glob)))

        # Deduplicate by filename
        seen: set[str] = set()
        unique: list[Path] = []
        for f in md_files:
            if f.name not in seen:
                seen.add(f.name)
                unique.append(f)

        print(f"  Found {len(unique)} unique files\n")
        ok, fail = 0, 0
        for f in unique:
            if await import_file(f, source_type):
                ok += 1
            else:
                fail += 1
        print(f"  Imported: {ok} OK, {fail} failed\n")
        total_ok += ok
        total_fail += fail

    print(f"Done: {total_ok} imported, {total_fail} failed")


if __name__ == "__main__":
    asyncio.run(main())
