from pathlib import Path

import pytest

from dumbo.config import DumboConfig, FilesystemConfig
from dumbo.tools.base import RiskLevel, ToolContext, ToolValidationError
from dumbo.tools.filesystem import (
    DeleteFileTool,
    ListDirTool,
    ReadTextFileTool,
    SearchFilesTool,
    WriteTextFileTool,
)


def _config(root: Path) -> DumboConfig:
    return DumboConfig(filesystem=FilesystemConfig(project_roots=(root.resolve(),)))


def test_list_read_and_search_inside_allowed_root(tmp_path: Path) -> None:
    (tmp_path / "invoice-123.pdf").write_text("pdf placeholder", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("hello", encoding="utf-8")
    config = _config(tmp_path)
    context = ToolContext(user_request="test", model="test")

    list_result = ListDirTool(config).execute({"path": str(tmp_path)}, context)
    assert list_result.ok
    assert {entry["name"] for entry in list_result.data["entries"]} == {
        "invoice-123.pdf",
        "notes.txt",
    }

    read_result = ReadTextFileTool(config).execute({"path": str(tmp_path / "notes.txt")}, context)
    assert read_result.data["content"] == "hello"

    search_result = SearchFilesTool(config).execute(
        {"query": "invoice", "roots": [str(tmp_path)], "extensions": ["pdf"], "max_results": 10},
        context,
    )
    assert search_result.ok
    assert search_result.data["results"][0]["name"] == "invoice-123.pdf"


def test_outside_root_is_rejected(tmp_path: Path) -> None:
    config = _config(tmp_path / "allowed")
    outside = tmp_path / "outside.txt"
    outside.write_text("no", encoding="utf-8")
    with pytest.raises(ToolValidationError):
        ReadTextFileTool(config).execute({"path": str(outside)}, ToolContext("test", "test"))


def test_write_overwrite_is_classified_destructive(tmp_path: Path) -> None:
    tool = WriteTextFileTool(_config(tmp_path))
    assert tool.classify_risk({"mode": "overwrite"}) == RiskLevel.DESTRUCTIVE


def test_delete_file_dry_run_does_not_delete(tmp_path: Path) -> None:
    target = tmp_path / "delete-me.txt"
    target.write_text("x", encoding="utf-8")
    tool = DeleteFileTool(_config(tmp_path))
    result = tool.execute(
        {"path": str(target)},
        ToolContext(user_request="test", model="test", dry_run=True),
    )
    assert result.ok
    assert target.exists()
