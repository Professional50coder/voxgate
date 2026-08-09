"""Vercel FastAPI entrypoint.

Vercel's build statically scans a fixed set of entrypoint files for a
top-level FastAPI instance named ``app`` (see
`deploying FastAPI on Vercel <https://vercel.com/docs/frameworks/backend/fastapi>`_).
VoxGate builds its app lazily inside ``voxgate.service.app`` so importing the
package in tests has no side effects, which means no file in the repo used to
match Vercel's scan. This thin shim exists only to give the runtime that
top-level attribute.

The singleton semantics live in ``voxgate.service.app`` (PEP 562
``__getattr__``), so this import is equivalent to ``uvicorn
voxgate.service.app:app``.
"""

from voxgate.service.app import create_app

app = create_app()