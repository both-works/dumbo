from __future__ import annotations

import importlib.util
import json
from dataclasses import asdict
from typing import Annotated

import typer

from dumbo.agent.approval import ApprovalMode, prompt_for_approval
from dumbo.agent.loop import AgentLoop, ToolExecutor
from dumbo.agent.model_router import (
    build_doctor_report,
    collect_hardware_info,
    model_is_available,
    recommend_profile,
)
from dumbo.agent.ollama_client import OllamaClient, OllamaError
from dumbo.config import list_model_profiles, load_config, load_model_profile
from dumbo.logging_setup import setup_logging
from dumbo.memory.sqlite_store import SQLiteMemoryStore
from dumbo.paths import app_paths, ensure_app_dirs, repository_root
from dumbo.skills.library import SkillLibrary
from dumbo.skills.recorder import TeachRecorder
from dumbo.skills.runner import SkillRunner
from dumbo.skills.schema import validate_skill_against_registry
from dumbo.tools.audit import AuditLog
from dumbo.tools.factory import build_default_registry
from dumbo.tools.policy import PolicyEngine

app = typer.Typer(no_args_is_help=True, help="Dumbo local-first desktop assistant.")
models_app = typer.Typer(no_args_is_help=True, help="Manage local model recommendations and pulls.")
memory_app = typer.Typer(no_args_is_help=True, help="Inspect and delete local memory.")
skills_app = typer.Typer(no_args_is_help=True, help="Manage local reusable skills.")
audit_app = typer.Typer(no_args_is_help=True, help="Inspect the local audit log.")
config_app = typer.Typer(no_args_is_help=True, help="Inspect active configuration paths.")

app.add_typer(models_app, name="models")
app.add_typer(memory_app, name="memory")
app.add_typer(skills_app, name="skills")
app.add_typer(audit_app, name="audit")
app.add_typer(config_app, name="config")


@app.command()
def doctor() -> None:
    """Report OS, Python, Ollama, local models, profile recommendation, and paths."""
    runtime = _build_runtime()
    report = build_doctor_report(runtime.config, runtime.paths, runtime.ollama)
    for line in report.to_lines():
        typer.echo(line)
    typer.echo("Optional dependencies:")
    missing = []
    for name, module in {
        "Playwright": "playwright",
        "pywinauto": "pywinauto",
        "PyAutoGUI": "pyautogui",
        "faster-whisper": "faster_whisper",
        "sounddevice": "sounddevice",
        "webrtcvad": "webrtcvad",
    }.items():
        installed = _module_available(module)
        if not installed:
            missing.append(name)
        typer.echo(f"- {name}: {'installed' if installed else 'missing'}")
    if missing:
        typer.echo("Remediation:")
        typer.echo('- Browser extras: .\\.venv\\Scripts\\python.exe -m pip install -e ".[browser]"')
        typer.echo("- Browser binary: .\\.venv\\Scripts\\python.exe -m playwright install chromium")
        typer.echo('- Desktop extras: .\\.venv\\Scripts\\python.exe -m pip install -e ".[desktop]"')
        typer.echo('- Voice extras: .\\.venv\\Scripts\\python.exe -m pip install -e ".[voice]"')


@app.command()
def ask(
    prompt: Annotated[str, typer.Argument(help="User request to handle.")],
    yes: Annotated[
        bool,
        typer.Option(
            "--yes",
            help=(
                "Approve only eligible low-risk write actions. Shell, destructive, "
                "privileged, and external actions still require interactive approval."
            ),
        ),
    ] = False,
    no_model: Annotated[
        bool,
        typer.Option("--no-model", help="Use only deterministic local intent parsing."),
    ] = False,
) -> None:
    """Handle a single request through the agent loop."""
    runtime = _build_runtime()
    approval_mode = ApprovalMode.ALLOW_LOW_RISK_ONLY if yes else ApprovalMode.INTERACTIVE
    response = runtime.agent.run(prompt, approval_mode=approval_mode, prefer_ollama=not no_model)
    typer.echo(response.final_text)


@app.command()
def chat(
    yes: Annotated[
        bool,
        typer.Option(
            "--yes",
            help=(
                "Approve only eligible low-risk write actions. Risky actions still prompt "
                "every time."
            ),
        ),
    ] = False,
) -> None:
    """Start a simple text chat loop."""
    runtime = _build_runtime()
    approval_mode = ApprovalMode.ALLOW_LOW_RISK_ONLY if yes else ApprovalMode.INTERACTIVE
    typer.echo("Dumbo chat. Type /quit to exit.")
    while True:
        prompt = typer.prompt("you")
        if prompt.strip().casefold() in {"/q", "/quit", "exit"}:
            break
        response = runtime.agent.run(prompt, approval_mode=approval_mode)
        typer.echo(f"dumbo: {response.final_text}")


@app.command()
def voice() -> None:
    """Start the local Enter-to-record fixed-window voice loop when configured."""
    runtime = _build_runtime()
    from dumbo.voice.loop import run_enter_to_record_voice_loop

    result = run_enter_to_record_voice_loop(
        runtime.agent, runtime.config.voice, runtime.paths.cache_dir
    )
    typer.echo(result)


@models_app.command("recommend")
def models_recommend() -> None:
    """Detect hardware and print a model profile recommendation."""
    hardware = collect_hardware_info()
    profile, decision_log = recommend_profile(hardware)
    typer.echo(f"Recommended profile: {profile}")
    typer.echo(f"OS: {hardware.os_name} {hardware.os_version}")
    typer.echo(f"Python: {hardware.python_version}")
    typer.echo(f"RAM: {hardware.ram_gb if hardware.ram_gb is not None else 'unknown'} GB")
    typer.echo("Decision logic:")
    for line in decision_log:
        typer.echo(f"- {line}")
    typer.echo("Available profiles:")
    for name in list_model_profiles():
        loaded = load_model_profile(name)
        typer.echo(
            f"- {name}: planner={loaded.planner_model}, vision={loaded.vision_model}, "
            f"embedding={loaded.embedding_model}"
        )


@models_app.command("pull")
def models_pull(
    profile: Annotated[str, typer.Option("--profile", help="Profile to pull.")] = "recommended",
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Show models without pulling.")
    ] = False,
) -> None:
    """Pull only the Ollama models used by the selected profile."""
    runtime = _build_runtime(profile_name=profile)
    pull_client = OllamaClient(
        base_url=runtime.config.ollama.base_url,
        timeout_seconds=runtime.config.ollama.pull_timeout_seconds,
    )
    selected = runtime.profile
    typer.echo(f"Selected profile: {selected.name}")
    for model in selected.ollama_models:
        if dry_run:
            typer.echo(f"Would pull {model}")
            continue
        typer.echo(f"Pulling {model}...")
        try:
            pull_client.pull(model)
        except OllamaError as exc:
            typer.echo(f"Failed to pull {model}: {exc}", err=True)
            raise typer.Exit(1) from exc
        typer.echo(f"Pulled {model}")
    if selected.optional_planner_model:
        typer.echo(
            f"Optional model not pulled automatically: {selected.optional_planner_model}. "
            "Use an explicit Ollama pull only after confirming hardware capacity."
        )


@models_app.command("test")
def models_test(
    profile: Annotated[str, typer.Option("--profile", help="Profile to test.")] = "recommended",
) -> None:
    """Check profile models against the local Ollama service."""
    runtime = _build_runtime(profile_name=profile)
    try:
        local = set(runtime.ollama.tags())
    except OllamaError as exc:
        typer.echo(f"Ollama is unavailable: {exc}", err=True)
        raise typer.Exit(1) from exc
    for model in runtime.profile.ollama_models:
        present = model_is_available(local, model)
        typer.echo(f"{model}: {'present' if present else 'missing'}")
    if model_is_available(local, runtime.profile.planner_model):
        response = runtime.ollama.chat(
            model=runtime.profile.planner_model,
            messages=[{"role": "user", "content": "Reply with exactly: ok"}],
            stream=False,
        )
        typer.echo(f"Planner response: {response.get('message', {}).get('content', '').strip()}")
    if model_is_available(local, runtime.profile.embedding_model):
        vector = runtime.ollama.embed(runtime.profile.embedding_model, "dumbo model test")
        typer.echo(f"Embedding dimensions: {len(vector)}")


@memory_app.command("list")
def memory_list() -> None:
    """List inspectable local memory facts."""
    runtime = _build_runtime()
    facts = runtime.memory_store.list_facts()
    if not facts:
        typer.echo("No memory facts stored.")
        return
    for fact in facts:
        typer.echo(json.dumps(asdict(fact), ensure_ascii=True))


@memory_app.command("forget")
def memory_forget(key: Annotated[str, typer.Argument(help="Memory key to delete.")]) -> None:
    """Delete a memory fact by key."""
    runtime = _build_runtime()
    deleted = runtime.memory_store.forget(key)
    typer.echo("Deleted." if deleted else "No matching memory fact.")


@skills_app.command("list")
def skills_list() -> None:
    """List locally saved skills."""
    runtime = _build_runtime()
    names = runtime.skill_library.list_names()
    if not names:
        typer.echo("No skills defined.")
        return
    for name in names:
        typer.echo(name)


@skills_app.command("run")
def skills_run(
    name: Annotated[str, typer.Argument(help="Skill name.")],
    args: Annotated[
        list[str] | None,
        typer.Option("--arg", help="Skill placeholder value as key=value. Can be repeated."),
    ] = None,
    yes: Annotated[
        bool,
        typer.Option(
            "--yes",
            help="Approve only eligible low-risk skill steps. Risky steps still require approval.",
        ),
    ] = False,
) -> None:
    """Run a saved skill through the same policy/audit tool executor."""
    runtime = _build_runtime()
    skill = runtime.skill_library.load(name)
    executor = ToolExecutor(runtime.registry, runtime.policy, runtime.audit)
    runner = SkillRunner(executor)
    results = runner.run(
        skill,
        context=runtime.tool_context_for(f"skills run {name}"),
        placeholders=_parse_key_value_options(args or []),
        approval_mode=ApprovalMode.ALLOW_LOW_RISK_ONLY if yes else ApprovalMode.INTERACTIVE,
        approval_callback=prompt_for_approval,
    )
    for result in results:
        typer.echo(json.dumps(asdict(result), ensure_ascii=True))


@skills_app.command("teach")
def skills_teach(
    name: Annotated[str, typer.Argument(help="Skill name.")],
    description: Annotated[str, typer.Option("--description", help="Skill description.")],
    steps: Annotated[
        list[str],
        typer.Option(
            "--step",
            help='Tool step JSON, e.g. {"tool":"open_app","args":{"name_or_path":"notepad"}}',
        ),
    ],
    intents: Annotated[
        list[str] | None,
        typer.Option("--intent", help="Example user intent. Can be repeated."),
    ] = None,
) -> None:
    """Teach a skill from explicit, registry-validated tool-step JSON."""
    runtime = _build_runtime()
    recorder = TeachRecorder(name=name, description=description, intent_examples=intents or [])
    for raw_step in steps:
        try:
            payload = json.loads(raw_step)
        except json.JSONDecodeError as exc:
            raise typer.BadParameter(f"Invalid --step JSON: {exc}") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("args"), dict):
            raise typer.BadParameter("--step must be an object with tool and args")
        tool_name = str(payload.get("tool", ""))
        tool = runtime.registry.get(tool_name)
        args = payload["args"]
        tool.validate_args(args)
        risk = (
            tool.classify_risk(args)
            if callable(getattr(tool, "classify_risk", None))
            else tool.risk_level
        )
        recorder.record_tool_call(tool_name, args, risk)

    skill = recorder.build()
    validate_skill_against_registry(skill, runtime.registry)
    typer.echo(json.dumps(skill.to_dict(), ensure_ascii=True, indent=2))
    if not typer.confirm("Save this skill?", default=False):
        typer.echo("Skill not saved.")
        return
    path = runtime.skill_library.save(skill)
    typer.echo(f"Saved skill to {path}")


@audit_app.command("tail")
def audit_tail(
    limit: Annotated[int, typer.Option("--limit", help="Number of audit rows to show.")] = 20,
) -> None:
    """Show recent local audit log rows."""
    runtime = _build_runtime()
    rows = runtime.audit.tail(limit)
    if not rows:
        typer.echo("No audit records.")
        return
    for row in rows:
        typer.echo(json.dumps(row, ensure_ascii=True))


@config_app.command("path")
def config_path() -> None:
    """Print config, app-data, audit, memory, and skills paths."""
    paths = ensure_app_dirs()
    typer.echo(f"Repository root: {repository_root()}")
    typer.echo(f"Default config: {repository_root() / 'config' / 'default.yaml'}")
    typer.echo(f"App data: {paths.data_dir}")
    typer.echo(f"Cache: {paths.cache_dir}")
    typer.echo(f"Logs: {paths.log_dir}")
    typer.echo(f"Audit DB: {paths.audit_db}")
    typer.echo(f"Memory DB: {paths.memory_db}")
    typer.echo(f"Skills: {paths.skills_dir}")


class Runtime:
    def __init__(self, profile_name: str | None = None):
        self.paths = ensure_app_dirs(app_paths())
        self.config = load_config()
        self.profile = load_model_profile(profile_name or self.config.app.profile)
        self.ollama = OllamaClient(
            base_url=self.config.ollama.base_url,
            timeout_seconds=self.config.ollama.request_timeout_seconds,
        )
        self.audit = AuditLog(self.paths.audit_db)
        self.memory_store = SQLiteMemoryStore(self.paths.memory_db)
        self.skill_library = SkillLibrary(self.paths.skills_dir)
        self.policy = PolicyEngine(self.config)
        self.registry = build_default_registry(
            config=self.config,
            profile=self.profile,
            paths=self.paths,
            memory_store=self.memory_store,
            skill_library=self.skill_library,
            ollama=self.ollama,
        )
        self.agent = AgentLoop(
            config=self.config,
            profile=self.profile,
            registry=self.registry,
            policy=self.policy,
            audit=self.audit,
            ollama=self.ollama,
            memory_store=self.memory_store,
            approval_callback=prompt_for_approval,
        )
        setup_logging(self.paths.log_dir)

    def tool_context_for(self, request: str):
        from dumbo.tools.base import ToolContext

        return ToolContext(
            user_request=request,
            model=self.profile.planner_model,
            timeout_seconds=self.config.app.tool_timeout_seconds,
        )


def _build_runtime(profile_name: str | None = None) -> Runtime:
    return Runtime(profile_name=profile_name)


def _module_available(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def _parse_key_value_options(values: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise typer.BadParameter("--arg values must use key=value syntax")
        key, item = value.split("=", 1)
        key = key.strip()
        if not key:
            raise typer.BadParameter("--arg key cannot be empty")
        result[key] = item
    return result
