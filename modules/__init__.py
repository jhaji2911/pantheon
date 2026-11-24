"""Module registry: every capability of the console is a module with its own routes.

A module is any file in this package exposing:

    ROUTES = [(method, compiled_regex, handler), ...]

where `handler(match, query, body)` returns `(status_code, payload)` and `payload` is
serialised to JSON. Adding a capability means adding a module and listing it here — the
core server never learns about colony internals, and one broken module cannot take the
console down (its routes report their own failure).
"""
from __future__ import annotations

from . import actions, assemblies, builds, ci, colony, god, hermes, pantheon, research, simworld, voice, world_builder

MODULES = (colony, ci, assemblies, pantheon, simworld, world_builder, research, actions, god, hermes, builds, voice)

ROUTES = [route for module in MODULES for route in getattr(module, "ROUTES", ())]
