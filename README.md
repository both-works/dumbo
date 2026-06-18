# Dumbo

Dumbo is a local-first desktop AI assistant for Windows PCs. It uses local Ollama models by default, gates every PC action through an explicit tool registry and policy engine, and records tool calls in a local SQLite audit log.

This scaffold does not require OpenAI, Anthropic, Google, or any cloud LLM API. Optional cloud fallback is intentionally not implemented.

## Quickstart

```powershell
.\scripts\install_windows.ps1
.\scripts\run_dumbo.ps1 doctor
.\scripts\run_dumbo.ps1 models recommend
.\scripts\run_dumbo.ps1 models pull --profile recommended
.\scripts\run_dumbo.ps1 ask "open Notepad"
.\scripts\run_dumbo.ps1 voice
```

For development without the helper scripts:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -U pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m dumbo doctor
```

## Core Commands

```powershell
python -m dumbo doctor
python -m dumbo chat
python -m dumbo ask "list my Downloads folder"
python -m dumbo ask "open Notepad"
python -m dumbo ask "run PowerShell Get-ChildItem"
python -m dumbo voice
python -m dumbo models recommend
python -m dumbo models pull --profile recommended
python -m dumbo models test
python -m dumbo memory list
python -m dumbo memory forget KEY
python -m dumbo skills list
python -m dumbo skills run NAME
python -m dumbo audit tail
python -m dumbo config path
```

## Owner Full-Access Mode

The checked-in default config is set for this PC owner workflow:

- all currently mounted drives are included in the filesystem roots
- sensitive path reads are allowed
- safe writes are allowed in trusted mode
- privileged actions can be requested, but still require confirmation
- common app aliases include Chrome, Edge, Firefox, Microsoft Office apps, and VS Code

Shell commands, destructive file operations, privileged actions, coordinate clicks,
typing into external apps, app closes, and external commitments remain confirmation
gated and audited.

## Architecture

- The model never receives uncontrolled OS access.
- Every action is a named tool with a JSON schema, risk level, dry-run support where meaningful, validation, and policy requirements.
- Read-only tools may run automatically inside configured filesystem roots.
- In the checked-in owner config, safe writes can run in trusted mode. Shell commands, destructive operations, privileged actions, coordinate clicks, app closes, and external commitments still require confirmation.
- Audit records include the user request, model, tool, redacted arguments, dry-run result, approval decision, execution result, and errors.
- Ordinary conversation runs without tool schemas or filesystem-root clutter, so the model answers normally instead of over-focusing on PC access.
- The default local inference settings favor reliable reasoning: high context, low temperature, nucleus/top-k sampling, repeat penalty, and a larger answer budget.

## Model Profiles

Profiles live in `config/profiles`.

- `recommended`: `qwen3-coder:30b`, `qwen3-vl:8b`, `mxbai-embed-large`, `faster-whisper small.en`, Piper.
- `low_resource`: `qwen3:8b`, `qwen3-vl:4b`, `nomic-embed-text`, `faster-whisper base.en`, Piper.
- `high_end`: `qwen3-coder:30b`, `qwen3-vl:30b`, `mxbai-embed-large`, `faster-whisper medium.en`, Piper. `qwen3-coder:480b` is not pulled automatically.

## Development

```powershell
.\.venv\Scripts\python.exe -m ruff format .
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pytest
```

Optional browser setup:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[browser]"
.\.venv\Scripts\python.exe -m playwright install chromium
```

Optional desktop/voice extras:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[desktop,voice]"
```

Voice mode is a local command loop: press Enter, speak naturally, and Dumbo transcribes
the command, routes it through the same agent and policy engine, then speaks the answer
when local TTS is available. You can also type into the `voice>` prompt as a fallback.
Wake words such as "Dumbo" and "Jarvis" are stripped, so phrases like "Dumbo, open a
word document" map to the same action as typed chat. Risky actions still require
approval; in voice mode you can type approval or press Enter and answer by voice.
Before each recording window, Dumbo lowers the Windows system volume to the configured
`voice.recording_volume_percent` value, which defaults to 5.

## Local Data

Dumbo uses `platformdirs` for app data, cache, and log paths. Run:

```powershell
python -m dumbo config path
```

to inspect the active paths. Memory and audit logs are local SQLite files and can be listed or deleted by the user.
