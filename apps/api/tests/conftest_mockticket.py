"""Bind the ticket tool's httpx client to the mock ticket service in-process.

Running the real service through an ASGI transport rather than stubbing httpx means these
tests exercise both halves of the contract — our payload and their validation — so a schema
drift on either side fails a test instead of surfacing in a demo.
"""
import importlib.util
from pathlib import Path

import httpx

_MAIN = Path(__file__).resolve().parents[2] / "mockticket" / "main.py"


def load_app():
    """Import apps/mockticket/main.py under a unique name.

    Loaded by path rather than by adding the directory to sys.path: `main` is too generic
    a module name to inject into a shared import namespace.
    """
    spec = importlib.util.spec_from_file_location("configent_mockticket", _MAIN)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.app


def bind(monkeypatch, module):
    """Point `module`'s httpx.AsyncClient at the in-process mock service."""
    app = load_app()

    class _Bound(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.ASGITransport(app=app)
            kwargs.setdefault("base_url", "http://mockticket")
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(module.httpx, "AsyncClient", _Bound)
    monkeypatch.setenv("TICKET_API_URL", "http://mockticket")
    return app
