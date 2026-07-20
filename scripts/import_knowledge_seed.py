"""Quick seed import: key design docs and crucible rules."""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from everos.core.persistence.memory_root import MemoryRoot
from everos.entrypoints.api.routes.knowledge import _build_extractor, _parse_upload
from everos.service.knowledge import create_document

APP_ID, PROJECT_ID = "opencode", "noctua"
ROOT = Path(__file__).parent.parent

class DummyUploadFile:
    def __init__(self, path: Path):
        self.filename = path.name
        self._path = path
        self.size = path.stat().st_size
        ext = path.suffix.lower()
        self.content_type = {".md":"text/markdown",".txt":"text/plain",".json":"application/json"}.get(ext, "application/octet-stream")
    async def read(self) -> bytes:
        return self._path.read_bytes()

# Priority imports: key design docs + crucible rules
PRIORITY_FILES = [
    # Rome core design docs
    "rome/rubicon/docs/designs/ray-agentic-batch-inference.md",
    "rome/rubicon/docs/designs/sft-on-ray.md",
    "rome/rubicon/docs/designs/metrics-framework.md",
    "rome/rubicon/docs/designs/optimization-playbook.md",
    "rome/rubicon/docs/designs/inference-roofline-flowchart.md",
    "rome/rubicon/docs/designs/ray-construction-plan/README.md",
    # Rome reports
    "rome/rubicon/docs/reports/diagnosis.md",
    "rome/rubicon/docs/reports/optimization-headroom.md",
    # Crucible
    "crucible/share/migration-rules.md",
    "crucible/share/troubleshooting.md",
]

async def import_one(path: Path, source_type: str):
    try:
        dummy = DummyUploadFile(path)
        file_content = await dummy.read()
        parsed = await _parse_upload(dummy, raw_bytes=file_content)
    except Exception as e:
        print(f"  SKIP parse {path.name}: {e}")
        return

    knowledge_dir = MemoryRoot.default().knowledge_dir(APP_ID, PROJECT_ID)
    extractor = _build_extractor()
    try:
        result = await create_document(
            extractor=extractor, parsed=parsed, title=path.stem,
            knowledge_dir=knowledge_dir, source_name=path.name,
            source_type=source_type, file_content=file_content,
        )
        print(f"  OK: {path.name} → {result.doc_id} [{result.category_id}]")
    except Exception as e:
        print(f"  ERR {path.name}: {str(e)[:120]}")

async def main():
    print("Noctua Seed Knowledge Import\n")
    ok = 0
    for rel in PRIORITY_FILES:
        path = ROOT / rel
        src_type = rel.split("/")[0]
        if not path.exists():
            print(f"  MISS: {rel}")
            continue
        print(f"Importing: {rel}")
        await import_one(path, src_type)
        ok += 1
    print(f"\nDone: {ok} files imported")

asyncio.run(main())
