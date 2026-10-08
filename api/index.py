"""Vercel serverless entrypoint.

Vercel's Python runtime detects the module-level ASGI `app` and serves it;
`vercel.json` rewrites every incoming path to this function. The repo root is
put on sys.path so `import app...` resolves the same as it does locally.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import app  # noqa: E402,F401
