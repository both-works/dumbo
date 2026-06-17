from dumbo.config import AppConfig, DumboConfig
from dumbo.tools.base import BaseTool, RiskLevel
from dumbo.tools.policy import PolicyAction, PolicyEngine


class ReadTool(BaseTool):
    name = "read"
    risk_level = RiskLevel.READ_ONLY


class WriteTool(BaseTool):
    name = "write"
    risk_level = RiskLevel.WRITE_SAFE


class PrivilegedTool(BaseTool):
    name = "privileged"
    risk_level = RiskLevel.PRIVILEGED


def test_read_only_allowed() -> None:
    decision = PolicyEngine(DumboConfig()).assess(ReadTool(), {})
    assert decision.action == PolicyAction.ALLOW


def test_write_requires_confirmation_by_default() -> None:
    decision = PolicyEngine(DumboConfig()).assess(WriteTool(), {})
    assert decision.action == PolicyAction.REQUIRE_CONFIRMATION


def test_trusted_mode_allows_safe_write() -> None:
    config = DumboConfig(app=AppConfig(trusted_mode=True))
    decision = PolicyEngine(config).assess(WriteTool(), {})
    assert decision.action == PolicyAction.ALLOW


def test_privileged_blocked_by_default() -> None:
    decision = PolicyEngine(DumboConfig()).assess(PrivilegedTool(), {})
    assert decision.action == PolicyAction.BLOCK
