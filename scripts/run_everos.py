"""
Noctua EverOS launcher with Gateway compatibility.

Injects /api/v1/mem/* routes so @everme/memory-mcp plugin
can talk to self-hosted EverOS. No modification to everos package.
"""
import sys
from pathlib import Path

NOCTUA_SCRIPTS = str(Path(__file__).parent.parent / "scripts")
sys.path.insert(0, NOCTUA_SCRIPTS)

from everos.entrypoints.api.app import create_app as _original_create_app
from gateway_compat import router as _gw_router


def create_app(**kwargs):
    app = _original_create_app(**kwargs)
    app.include_router(_gw_router)
    return app


import everos.entrypoints.api.app
everos.entrypoints.api.app.create_app = create_app

if __name__ == "__main__":
    from everos.entrypoints.cli.main import app
    app()
