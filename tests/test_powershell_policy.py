import pytest

from dumbo.tools.base import RiskLevel, ToolValidationError
from dumbo.tools.powershell import RunPowerShellTool, classify_powershell


def test_general_command_is_shell_risk() -> None:
    risk, reason = classify_powershell("Get-ChildItem")
    assert risk == RiskLevel.SHELL
    assert "confirmation" in reason


def test_destructive_pattern_is_detected() -> None:
    risk, _reason = classify_powershell("Remove-Item C:\\Temp -Recurse -Force")
    assert risk == RiskLevel.DESTRUCTIVE


def test_privileged_pattern_is_detected() -> None:
    risk, _reason = classify_powershell("Set-ExecutionPolicy Unrestricted")
    assert risk == RiskLevel.PRIVILEGED


def test_credential_access_is_rejected_at_validation() -> None:
    tool = RunPowerShellTool()
    with pytest.raises(ToolValidationError):
        tool.validate_args({"command": "cmdkey /list"})
