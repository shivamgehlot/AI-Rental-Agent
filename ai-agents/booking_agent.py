"""Compatibility module exposing the booking agent FastAPI app."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_source_path = Path(__file__).with_name("booking-agent.py")
_spec = importlib.util.spec_from_file_location("booking_agent_service", _source_path)
if _spec is None or _spec.loader is None:
    raise RuntimeError("Unable to load booking-agent.py module")
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)

app = _module.app
