from __future__ import annotations

import re
import shutil
import subprocess
from typing import Any

from dumbo.config import DumboConfig
from dumbo.tools.base import BaseTool, RiskLevel, ToolContext, ToolResult, ToolValidationError
from dumbo.tools.filesystem import FilesystemPolicyMixin

BLOCKED_PATTERNS = [
    r"\b(Get-StoredCredential|cmdkey\s*/list|vaultcmd|ConvertTo-SecureString)\b",
    r"(?i)(?:^|\s)-EncodedCommand\b",
    r"\b(iex|Invoke-Expression)\b",
    r"\b(Start-Process|powershell|pwsh)\b.*\b-WindowStyle\s+Hidden\b",
    r"\b(cookies?|passwords?|Login Data|Web Data|Local State)\b",
    r"\b(bypass|disable).*(uac|defender|antivirus|endpoint|firewall)\b",
    r"\b(Set-MpPreference)\b.*\b(DisableRealtimeMonitoring|DisableIOAVProtection)\b",
    r"\b(Invoke-WebRequest|Invoke-RestMethod|curl|wget)\b.*\|\s*(iex|Invoke-Expression)",
]
PRIVILEGED_PATTERNS = [
    r"\bSet-ExecutionPolicy\b",
    r"\b(reg\s+(add|delete)|New-ItemProperty|Set-ItemProperty)\b.*\b(HKLM|HKEY_LOCAL_MACHINE)\b",
    r"\b(New-Service|Set-Service|sc\.exe\s+(create|config|delete))\b",
    r"\bnetsh\s+advfirewall\b",
]
DESTRUCTIVE_PATTERNS = [
    r"\b(Remove-Item|rm|del|erase|rmdir)\b",
    r"\b(format|diskpart|bcdedit|cipher\s*/w|Clear-History)\b",
    r"\bStop-Process\b",
]
NETWORK_PATTERNS = [
    r"\b(Invoke-WebRequest|Invoke-RestMethod|curl|wget|scp|sftp|ftp)\b",
    r"\b(Net\.WebClient|DownloadString|DownloadFile|Start-BitsTransfer)\b",
]


class RunPowerShellTool(FilesystemPolicyMixin, BaseTool):
    name = "run_powershell"
    description = "Run a PowerShell command after policy review and audit logging."
    risk_level = RiskLevel.SHELL
    dry_run_supported = True
    allow_noninteractive_approval = False
    parameters_schema = {
        "type": "object",
        "properties": {
            "command": {"type": "string"},
            "timeout_seconds": {"type": "integer"},
            "working_directory": {"type": "string"},
        },
        "required": ["command"],
    }

    def __init__(self, config: DumboConfig | None = None):
        super().__init__(config or DumboConfig())

    def validate_args(self, args: dict[str, Any]) -> None:
        super().validate_args(args)
        command = args["command"].strip()
        if not command:
            raise ToolValidationError("PowerShell command cannot be empty")
        risk, reason = classify_powershell(command)
        if risk == RiskLevel.PRIVILEGED and reason.startswith("Blocked"):
            raise ToolValidationError(reason)
        working_directory = args.get("working_directory")
        if working_directory:
            self.resolve_allowed(str(working_directory), must_exist=True)

    def classify_risk(self, args: dict[str, Any]) -> RiskLevel:
        return classify_powershell(str(args.get("command", "")))[0]

    def execute(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        command = args["command"]
        timeout = int(args.get("timeout_seconds") or context.timeout_seconds)
        cwd = args.get("working_directory") or None
        if context.dry_run:
            risk, reason = classify_powershell(command)
            return ToolResult.success(
                f"Would run PowerShell command as {risk.value}: {reason}",
                {"command": command, "risk": risk.value},
            )
        shell_path = shutil.which("powershell") or shutil.which("pwsh")
        if shell_path is None:
            return ToolResult.failure("PowerShell executable was not found on PATH.")
        completed = subprocess.run(
            [shell_path, "-NoProfile", "-NonInteractive", "-Command", command],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        data = {
            "returncode": completed.returncode,
            "stdout": completed.stdout[-12000:],
            "stderr": completed.stderr[-12000:],
        }
        if completed.returncode != 0:
            return ToolResult(
                ok=False,
                message="PowerShell command failed.",
                data=data,
                error=completed.stderr or f"Exit code {completed.returncode}",
            )
        return ToolResult.success("PowerShell command completed.", data)

    def expected_impact(self, args: dict[str, Any]) -> str:
        return f"Runs this exact PowerShell command: {args.get('command', '')}"


def classify_powershell(command: str) -> tuple[RiskLevel, str]:
    normalized = command.strip()
    for pattern in BLOCKED_PATTERNS:
        if re.search(pattern, normalized, flags=re.IGNORECASE):
            return RiskLevel.PRIVILEGED, "Blocked credential or security-control access pattern."
    for pattern in PRIVILEGED_PATTERNS:
        if re.search(pattern, normalized, flags=re.IGNORECASE):
            return RiskLevel.PRIVILEGED, "Privileged PowerShell pattern detected."
    for pattern in DESTRUCTIVE_PATTERNS:
        if re.search(pattern, normalized, flags=re.IGNORECASE):
            return RiskLevel.DESTRUCTIVE, "Destructive PowerShell pattern detected."
    for pattern in NETWORK_PATTERNS:
        if re.search(pattern, normalized, flags=re.IGNORECASE):
            return RiskLevel.SHELL, "Network-capable shell command requires confirmation."
    return RiskLevel.SHELL, "General shell command requires confirmation."


def powershell_tools(config: DumboConfig) -> list[BaseTool]:
    return [RunPowerShellTool(config)]
