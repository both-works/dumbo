# Security Model

Dumbo is designed as a local-first assistant with auditable, policy-gated PC access.

## Default Rules

- No cloud LLM API is required or enabled by default.
- The model can request only named tools from the local registry.
- Every tool call is logged to SQLite with sensitive values redacted.
- Destructive, privileged, shell, write, coordinate-click, app-close, and external-commitment actions are never silent.
- Privileged actions are blocked unless explicitly enabled in config and confirmed.
- Startup integration is not created by this scaffold.

## Risk Levels

- `READ_ONLY`: allowed automatically within configured roots.
- `LOW_RISK_OPEN`: allowed automatically and logged.
- `WRITE_SAFE`: confirmation required unless trusted mode is enabled.
- `SHELL`: confirmation required with the exact command shown.
- `DESTRUCTIVE`: confirmation required with impact information when possible.
- `PRIVILEGED`: blocked by default unless enabled in config and confirmed.
- `EXTERNAL_COMMITMENT`: explicit final user confirmation is always required.

## Filesystem Boundaries

Initial allowed roots are the user's home, Desktop, Documents, Downloads, Pictures, Music, Videos, and configured project roots. Files outside those roots are denied by default.

Dumbo blocks sensitive locations and file names by default, including browser cookies, password stores, SSH keys, API keys, credential stores, and crypto wallet material. Even confirmed sensitive reads are redacted in logs.

## Shell Policy

PowerShell commands run only through the `run_powershell` tool. Dangerous patterns are classified before execution. Credential-manager access and attempts to bypass security controls are blocked.

## Voice Privacy

Voice is Enter-to-record fixed-window first. Raw microphone audio is deleted after
transcription unless `voice.save_audio=true` is configured, in which case WAV files
are saved under Dumbo's cache audio directory.

## PowerShell Classifier

PowerShell commands are classified before execution with conservative pattern checks
for credential access, encoded commands, download-and-execute forms, hidden windows,
destructive commands, and privileged registry/service/firewall changes. This is not a
full PowerShell AST policy engine; ambiguous commands are escalated for confirmation
or blocked rather than silently trusted.

## Kill Switch

Desktop automation enables PyAutoGUI's fail-safe when available. Moving the mouse to the top-left corner aborts PyAutoGUI actions. A global `Ctrl+Alt+Esc` hook is planned but not installed by default because global hooks require extra permissions and can behave differently across Windows security contexts.
