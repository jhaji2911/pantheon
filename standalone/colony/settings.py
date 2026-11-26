"""Standalone settings: one OpenAI-compatible endpoint serves every resident.

  PANTHEON_LLM_BASE_URL   default http://127.0.0.1:11434/v1 (Ollama)
  PANTHEON_LLM_API_KEY    sent as a bearer token when set (not needed for Ollama)
  PANTHEON_MODEL          model for every tier; default: the first model the endpoint lists
  PANTHEON_MODEL_<TIER>   per-tier override, e.g. PANTHEON_MODEL_ARCHITECT=qwen3:14b
"""
from __future__ import annotations

import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
SANDBOX = DATA / "notebooks"
DB_PATH = DATA / "demo-colony.db"

ORG = "the Pantheon colony"
WORLD_NAME = "town of Pantheon"

BASE_URL = os.environ.get("PANTHEON_LLM_BASE_URL", "http://127.0.0.1:11434/v1").rstrip("/")
API_KEY = os.environ.get("PANTHEON_LLM_API_KEY", "")
MODEL = os.environ.get("PANTHEON_MODEL", "")


def tier_model(tier: str) -> str:
    return os.environ.get("PANTHEON_MODEL_" + tier.upper(), MODEL)


_TALK = ["compute", "prove", "notebook_read", "notebook_list", "recall"]
TIERS = {
    "reflex":     {"level": 0, "model": tier_model("reflex"),     "may": ["recall"]},
    "worker":     {"level": 1, "model": tier_model("worker"),     "may": _TALK},
    "specialist": {"level": 2, "model": tier_model("specialist"), "may": _TALK},
    "architect":  {"level": 3, "model": tier_model("architect"),  "may": _TALK},
}

DEFAULTS = {
    "memory_recall": 6,
    "offered_tasks_per_agent": 3,
    "world_note": "",
    "tick_token_budget": 60000,
    "daily_token_budget": 600000,
}


def settings() -> dict:
    return dict(DEFAULTS)


def get(key, default=None):
    return DEFAULTS.get(key, default)


def signed(name: str) -> str:
    return "%s@pantheon" % name.lower()
