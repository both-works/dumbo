# Dumbo Implementation Plan

## Verified facts

- Ollama supports local `/api/chat` requests with `tools` and returns `message.tool_calls`; structured output is available through the `format` field. Sources: https://github.com/ollama/ollama/blob/main/docs/api.md and https://ollama.com/blog/tool-support.
- Ollama model library pages currently list `qwen3-coder` with `30b` and `480b` tags, `qwen3-vl` with `4b`, `8b`, and `30b` tags, plus `mxbai-embed-large` and `nomic-embed-text` embedding models. Sources: https://ollama.com/library/qwen3-coder, https://ollama.com/library/qwen3-vl, https://ollama.com/library/mxbai-embed-large, https://ollama.com/library/nomic-embed-text.
- `faster-whisper` is the verified Python STT package for local Whisper inference through CTranslate2. `whisper.cpp` is a viable native fallback, but this scaffold starts with the Python adapter. Sources: https://github.com/SYSTRAN/faster-whisper and https://github.com/ggml-org/whisper.cpp.
- Piper is verified as a local TTS engine. The current upstream repository notes development movement, so Dumbo treats Piper as an external executable adapter rather than hard-binding to an unstable Python API. Sources: https://github.com/rhasspy/piper and https://rhasspy.github.io/piper-samples/.
- Playwright Python is the verified browser automation layer. Source: https://playwright.dev/python/docs/intro.
- Windows desktop automation will prefer Microsoft UI Automation through `pywinauto` and fall back to PyAutoGUI for coordinate/keyboard primitives. Sources: https://pywinauto.readthedocs.io/en/latest/, https://learn.microsoft.com/en-us/windows/win32/winauto/entry-uiautocore-overview, and https://pyautogui.readthedocs.io/.
- LangGraph is appropriate for later durable, human-in-the-loop agent execution, but the MVP keeps a small explicit loop to reduce dependencies and make policy/audit behavior obvious. Source: https://docs.langchain.com/oss/python/langgraph/overview.

## Scope for this pass

Build a Windows-first, local-first Python scaffold that can run without cloud APIs and has production-shaped seams for the full assistant:

1. Project metadata, config files, README, SECURITY, and Windows scripts.
2. Typer CLI with `doctor`, `ask`, `chat`, `voice`, `models`, `memory`, `skills`, `audit`, and `config` commands.
3. Model profiles for `recommended`, `low_resource`, and `high_end`.
4. Hardware/installation doctor and model recommendation logic using OS, RAM, Ollama status, local models, and best-effort GPU/VRAM detection.
5. Tool registry, risk policy, argument validation, dry-run paths, confirmation gates, and SQLite audit logging.
6. MVP tools for filesystem, app opening/process listing, PowerShell, browser automation, desktop automation, vision, media, memory, and skills.
7. Agent loop with strict Ollama tool-call parsing plus deterministic local intent handling for MVP acceptance commands and mocked tests.
8. SQLite memory store and YAML skill library.
9. Voice adapters that fail gracefully when optional local dependencies or Piper voices are missing.
10. Pytest coverage for policy, registry, filesystem safety, PowerShell policy, mocked agent loop, skills, and memory.

## Conservative choices

- Use Python `>=3.11` instead of pinning to 3.12 because this machine exposes Python 3.13.5/3.13.14. Optional voice/desktop extras may have narrower support; `doctor` reports missing or incompatible dependencies instead of pretending they work.
- Use `venv` in scripts because `uv` is not installed here.
- Use direct HTTP calls to local Ollama with the standard library instead of introducing a required SDK dependency.
- Do not pull models during install. `dumbo models pull --profile ...` pulls only the selected profile's Ollama models.
- Coordinate clicks, text typing into external apps, shell execution, writes, deletes, closes, and external commitments are policy gated and audited.
- LangGraph is not included as an MVP dependency; the explicit loop is easier to test and audit.

## Known limitations after this pass

- Wake word support is intentionally out of scope; push-to-talk/voice is adapter-first and dependency gated.
- Browser and desktop automation require optional extras and installed browser binaries.
- Vision depends on an installed Ollama vision model and only proposes observations/coordinates; policy still gates any desktop action.
- The MVP agent can operate on deterministic local intents or Ollama tool calls. General conversational quality depends on the user's installed local model.
