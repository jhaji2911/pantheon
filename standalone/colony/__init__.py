"""Standalone stand-in for the Colony runtime, so Pantheon runs on its own.

`bridge.py` loads this package only when no real Colony checkout is found. It provides the
small surface Pantheon reads (settings, a model relay, prompt blocks, notebook reads) and a
seeded demo colony, so a fresh clone opens a living town with six residents.

Models come from any OpenAI-compatible endpoint: Ollama (the default), LM Studio, llama.cpp's
server, vLLM, OpenAI and so on. See `settings.py` for the environment variables.
"""
