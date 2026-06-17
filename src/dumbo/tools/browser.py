from __future__ import annotations

import ipaddress
import re
from typing import Any
from urllib.parse import urlparse

from dumbo.config import DumboConfig
from dumbo.tools.base import BaseTool, RiskLevel, ToolContext, ToolResult, ToolValidationError

DESTRUCTIVE_CLICK_RE = re.compile(r"\b(delete|remove)\b", re.IGNORECASE)
EXTERNAL_CLICK_RE = re.compile(
    r"\b(send|submit|buy|purchase|checkout|pay|confirm|post|upload|publish|reply|"
    r"forward|transfer)\b",
    re.IGNORECASE,
)


class BrowserSession:
    def __init__(self, config: DumboConfig):
        self.config = config
        self._playwright = None
        self._browser = None
        self._page = None

    def launch(self) -> ToolResult:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return ToolResult.failure("Playwright is not installed. Install Dumbo with .[browser].")
        if self._browser is None:
            try:
                self._playwright = sync_playwright().start()
                self._browser = self._playwright.chromium.launch(
                    headless=self.config.browser.headless
                )
                self._page = self._browser.new_page()
            except Exception as exc:
                if self._playwright is not None:
                    self._playwright.stop()
                    self._playwright = None
                return ToolResult.failure(
                    "Could not launch Chromium. Run: python -m playwright install chromium",
                    error=str(exc),
                )
        return ToolResult.success("Browser launched.")

    @property
    def page(self) -> Any:
        if self._page is None:
            result = self.launch()
            if not result.ok:
                raise RuntimeError(result.message)
        return self._page

    def close(self) -> ToolResult:
        if self._browser is not None:
            self._browser.close()
            self._browser = None
            self._page = None
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None
        return ToolResult.success("Browser closed.")


class LaunchBrowserTool(BaseTool):
    name = "launch_browser"
    description = "Launch a Playwright Chromium browser session."
    risk_level = RiskLevel.LOW_RISK_OPEN
    parameters_schema = {"type": "object", "properties": {}, "required": []}

    def __init__(self, session: BrowserSession):
        self.session = session

    def execute(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        if context.dry_run:
            return ToolResult.success("Would launch browser.")
        return self.session.launch()


class OpenUrlTool(BaseTool):
    name = "open_url"
    description = "Open a URL in the Playwright browser session."
    risk_level = RiskLevel.LOW_RISK_OPEN
    allow_noninteractive_approval = False
    parameters_schema = {
        "type": "object",
        "properties": {"url": {"type": "string"}},
        "required": ["url"],
    }

    def __init__(self, session: BrowserSession):
        self.session = session

    def validate_args(self, args: dict[str, Any]) -> None:
        super().validate_args(args)
        if not args["url"].startswith(("http://", "https://")):
            raise ToolValidationError("Only http:// and https:// URLs are supported.")

    def classify_risk(self, args: dict[str, Any]) -> RiskLevel:
        url = str(args.get("url", ""))
        if _is_local_or_private_url(url) and not _url_is_trusted(
            url, self.session.config.browser.trusted_local_urls
        ):
            return RiskLevel.WRITE_SAFE
        return RiskLevel.LOW_RISK_OPEN

    def execute(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        if context.dry_run:
            return ToolResult.success(f"Would open URL {args['url']}.")
        page = self.session.page
        page.goto(args["url"], wait_until="domcontentloaded")
        return ToolResult.success(
            f"Opened {args['url']}.", {"title": page.title(), "url": page.url}
        )


class BrowserAccessibilitySnapshotTool(BaseTool):
    name = "get_page_accessibility_snapshot"
    description = "Get a structured browser page snapshot, falling back to visible text."
    risk_level = RiskLevel.READ_ONLY
    parameters_schema = {"type": "object", "properties": {}, "required": []}

    def __init__(self, session: BrowserSession):
        self.session = session

    def execute(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        page = self.session.page
        snapshot = None
        body = page.locator("body")
        aria_snapshot = getattr(body, "aria_snapshot", None)
        if callable(aria_snapshot):
            snapshot = aria_snapshot(timeout=5000)
            return ToolResult.success("Captured structured ARIA snapshot.", {"snapshot": snapshot})
        accessibility = getattr(page, "accessibility", None)
        if accessibility is not None and hasattr(accessibility, "snapshot"):
            snapshot = accessibility.snapshot()
            return ToolResult.success(
                "Captured structured accessibility snapshot.", {"snapshot": snapshot}
            )
        if snapshot is None:
            snapshot = {"visible_text": page.locator("body").inner_text(timeout=5000)}
        return ToolResult.success(
            "Structured snapshot unavailable; captured visible text fallback.",
            {"snapshot": snapshot},
        )


class ClickByRoleOrTextTool(BaseTool):
    name = "click_by_role_or_text"
    description = "Click a browser element by ARIA role/name or visible text."
    risk_level = RiskLevel.LOW_RISK_OPEN
    parameters_schema = {
        "type": "object",
        "properties": {
            "role": {"type": ["string", "null"]},
            "name": {"type": "string"},
        },
        "required": ["name"],
    }

    def __init__(self, session: BrowserSession):
        self.session = session

    def classify_risk(self, args: dict[str, Any]) -> RiskLevel:
        name = str(args.get("name", ""))
        if DESTRUCTIVE_CLICK_RE.search(name):
            return RiskLevel.DESTRUCTIVE
        if EXTERNAL_CLICK_RE.search(name):
            return RiskLevel.EXTERNAL_COMMITMENT
        return RiskLevel.LOW_RISK_OPEN

    def execute(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        if context.dry_run:
            return ToolResult.success(f"Would click browser element {args['name']}.")
        page = self.session.page
        role = args.get("role")
        if role:
            page.get_by_role(role, name=args["name"]).click()
        else:
            page.get_by_text(args["name"]).click()
        return ToolResult.success(f"Clicked {args['name']}.")


class FillFieldTool(BaseTool):
    name = "fill_field"
    description = "Fill a browser field by label or placeholder."
    risk_level = RiskLevel.WRITE_SAFE
    parameters_schema = {
        "type": "object",
        "properties": {
            "label_or_placeholder": {"type": "string"},
            "text": {"type": "string"},
        },
        "required": ["label_or_placeholder", "text"],
    }

    def __init__(self, session: BrowserSession):
        self.session = session

    def execute(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        if context.dry_run:
            return ToolResult.success(f"Would fill browser field {args['label_or_placeholder']}.")
        page = self.session.page
        target = args["label_or_placeholder"]
        locator = page.get_by_label(target)
        if locator.count() == 0:
            locator = page.get_by_placeholder(target)
        locator.fill(args["text"])
        return ToolResult.success(f"Filled field {target}.")


class PressKeyTool(BaseTool):
    name = "press_key"
    description = "Press a key in the browser page."
    risk_level = RiskLevel.LOW_RISK_OPEN
    parameters_schema = {
        "type": "object",
        "properties": {"key": {"type": "string"}},
        "required": ["key"],
    }

    def __init__(self, session: BrowserSession):
        self.session = session

    def classify_risk(self, args: dict[str, Any]) -> RiskLevel:
        key = _normalize_key(str(args.get("key", "")))
        if key in {"enter", "control+enter", "ctrl+enter", "meta+enter"}:
            return RiskLevel.EXTERNAL_COMMITMENT
        return RiskLevel.LOW_RISK_OPEN

    def execute(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        if context.dry_run:
            return ToolResult.success(f"Would press {args['key']}.")
        self.session.page.keyboard.press(args["key"])
        return ToolResult.success(f"Pressed {args['key']}.")


class ExtractVisibleTextTool(BaseTool):
    name = "extract_visible_text"
    description = "Extract visible text from the current browser page."
    risk_level = RiskLevel.READ_ONLY
    parameters_schema = {"type": "object", "properties": {}, "required": []}

    def __init__(self, session: BrowserSession):
        self.session = session

    def execute(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        text = self.session.page.locator("body").inner_text(timeout=5000)
        return ToolResult.success("Extracted visible text.", {"text": text})


class CloseBrowserTool(BaseTool):
    name = "close_browser"
    description = "Close the Playwright browser session."
    risk_level = RiskLevel.LOW_RISK_OPEN
    parameters_schema = {"type": "object", "properties": {}, "required": []}

    def __init__(self, session: BrowserSession):
        self.session = session

    def execute(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        if context.dry_run:
            return ToolResult.success("Would close browser.")
        return self.session.close()


def browser_tools(config: DumboConfig) -> list[BaseTool]:
    session = BrowserSession(config)
    return [
        LaunchBrowserTool(session),
        OpenUrlTool(session),
        BrowserAccessibilitySnapshotTool(session),
        ClickByRoleOrTextTool(session),
        FillFieldTool(session),
        PressKeyTool(session),
        ExtractVisibleTextTool(session),
        CloseBrowserTool(session),
    ]


def _normalize_key(value: str) -> str:
    return value.strip().casefold().replace(" ", "").replace("control", "ctrl")


def _is_local_or_private_url(url: str) -> bool:
    parsed = urlparse(url)
    host = parsed.hostname
    if host is None:
        return False
    if host in {"localhost", "127.0.0.1", "::1"}:
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return host.endswith(".local")
    return address.is_private or address.is_loopback or address.is_link_local


def _url_is_trusted(url: str, allowlist: tuple[str, ...]) -> bool:
    return any(url.startswith(item) for item in allowlist)
