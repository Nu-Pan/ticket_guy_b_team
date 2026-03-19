"""ticket_guy_b_team の CLI 本体。"""

import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, NotRequired, Sequence, TypedDict, cast

import typer
from langgraph.graph import END, StateGraph


PLAN_REQUIRED_SECTIONS = [
    "目的",
    "スコープ外",
    "成果物",
    "制約",
    "受け入れ条件",
    "作業分解",
    "未確定事項",
    "依存関係マップ",
    "想定リスク",
    "差し戻し条件",
    "検証戦略",
]
TICKET_REQUIRED_SECTIONS = [
    "Title",
    "Purpose",
    "Inputs",
    "Outputs",
    "Scope",
    "Out of Scope",
    "Dependencies",
    "Steps",
    "Acceptance Criteria",
    "Verification",
    "Risks / Notes",
    "Priority",
    "Owner Role",
    "Blocking Conditions",
    "Rollback / Abort",
    "Artifacts Path",
]
PLAN_STATUSES = {"draft", "in_review", "approved"}
TICKET_STATUSES = {"todo", "blocked", "running", "review_pending", "done", "failed"}
REVIEW_RESULTS = {"pass", "fail"}
TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
RUN_ID_FORMAT = "%Y%m%d%H%M%S%f"
DEFAULT_PRIORITY = "high"
RUN_MODES = {"dry-run", "production"}
DEFAULT_PRODUCTION_MODEL = "gpt-5.4"
DEFAULT_REASONING_EFFORT = "medium"
APP = typer.Typer()
review_app = typer.Typer()
APP.add_typer(review_app, name="review")


@dataclass(frozen=True)
class Dependency:
    """チケット依存条件を表す。"""

    ticket_id: str
    required_state: str


@dataclass
class Document:
    """front matter と本文を持つ Markdown 文書。"""

    metadata: dict[str, object]
    body: str


@dataclass(frozen=True)
class RunConfig:
    """実行モードとモデル設定を表す。"""

    mode: str = "dry-run"
    model: str = DEFAULT_PRODUCTION_MODEL
    reasoning_effort: str = DEFAULT_REASONING_EFFORT


@dataclass(frozen=True)
class RunArtifacts:
    """1 回の ticket 実行で使う成果物パスを表す。"""

    run_id: str
    log_path: Path
    message_path: Path


class RunState(TypedDict):
    """LangGraph が流す実行状態。"""

    ticket_id: str
    document: NotRequired[Document]
    dependencies: NotRequired[list[Dependency]]
    dependencies_ok: NotRequired[bool]
    missing_dependencies: NotRequired[list[Dependency]]
    artifacts: NotRequired[list[str]]


def utc_now() -> str:
    """現在時刻を UTC 文字列で返す。"""
    return datetime.now(timezone.utc).strftime(TIMESTAMP_FORMAT)


def generate_run_id() -> str:
    """ログファイル名に使う実行 ID を返す。"""
    return datetime.now(timezone.utc).strftime(RUN_ID_FORMAT)


def repo_root() -> Path:
    """リポジトリルートを返す。"""
    return Path(__file__).resolve().parents[1]


def runtime_root(base_dir: Path | None = None) -> Path:
    """成果物の保存先となる実行ルートを返す。"""
    return base_dir or Path.cwd()


def artifacts_root(base_dir: Path | None = None) -> Path:
    """成果物ルートを返す。"""
    return runtime_root(base_dir) / "artifacts"


def ensure_artifact_dirs(base_dir: Path | None = None) -> None:
    """必要な成果物ディレクトリを作成する。"""
    root = artifacts_root(base_dir)
    for relative in ["plans", "tickets", "reviews", "logs", "messages"]:
        (root / relative).mkdir(parents=True, exist_ok=True)


def front_matter_dump(metadata: Mapping[str, object]) -> str:
    """単純な YAML front matter 文字列を生成する。"""
    lines: list[str] = ["---"]
    for key, value in metadata.items():
        lines.extend(_dump_yaml_line(key, value, indent=0))
    lines.append("---")
    return "\n".join(lines)


def _dump_yaml_line(key: str, value: object, indent: int) -> list[str]:
    """最小限の YAML 形式へ変換する。"""
    prefix = " " * indent
    if isinstance(value, list):
        lines = [f"{prefix}{key}:"]
        for item in value:
            if isinstance(item, dict):
                lines.append(f"{prefix}  -")
                for child_key, child_value in item.items():
                    lines.extend(_dump_yaml_line(child_key, child_value, indent + 4))
            else:
                lines.append(f"{prefix}  - {item}")
        return lines
    if isinstance(value, dict):
        lines = [f"{prefix}{key}:"]
        for child_key, child_value in value.items():
            lines.extend(_dump_yaml_line(child_key, child_value, indent + 2))
        return lines
    return [f"{prefix}{key}: {value}"]


def parse_document(path: Path) -> Document:
    """Markdown front matter 文書を読み込む。"""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError(f"front matter is required: {path}")
    _, metadata_block, body = text.split("---\n", 2)
    metadata = parse_yaml(metadata_block.strip())
    return Document(metadata=metadata, body=body.lstrip("\n"))


def write_document(path: Path, metadata: Mapping[str, object], body: str) -> None:
    """Markdown front matter 文書を書き込む。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    content = f"{front_matter_dump(metadata)}\n\n{body.rstrip()}\n"
    path.write_text(content, encoding="utf-8")


def parse_yaml(text: str) -> dict[str, object]:
    """このアプリで必要な範囲の YAML を解析する。"""
    result: dict[str, object] = {}
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        raw_line = lines[index]
        if not raw_line.strip():
            index += 1
            continue
        if raw_line.startswith("  "):
            raise ValueError("top level indentation is not supported")
        if ":" not in raw_line:
            raise ValueError(f"invalid yaml line: {raw_line}")
        key, raw_value = raw_line.split(":", 1)
        key = key.strip()
        value = raw_value.strip()
        if value:
            result[key] = coerce_scalar(value)
            index += 1
            continue
        nested_lines: list[str] = []
        index += 1
        while index < len(lines):
            nested = lines[index]
            if nested.startswith("  "):
                nested_lines.append(nested)
                index += 1
                continue
            break
        result[key] = parse_nested_yaml(nested_lines)
    return result


def parse_nested_yaml(lines: list[str]) -> object:
    """入れ子の list / dict を解析する。"""
    if not lines:
        return ""
    first_line = next((line for line in lines if line.strip()), "")
    if first_line.startswith("  -"):
        return parse_yaml_list(lines)
    return parse_yaml_dict(lines, base_indent=2)


def parse_yaml_list(lines: list[str]) -> list[object]:
    """YAML のリストを解析する。"""
    items: list[object] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if stripped == "-":
            index += 1
            block: list[str] = []
            while index < len(lines) and lines[index].startswith("    "):
                block.append(lines[index][2:])
                index += 1
            items.append(parse_yaml_dict(block, base_indent=2))
            continue
        items.append(coerce_scalar(stripped[2:].strip()))
        index += 1
    return items


def parse_yaml_dict(lines: list[str], base_indent: int) -> dict[str, object]:
    """YAML の辞書を解析する。"""
    result: dict[str, object] = {}
    index = 0
    while index < len(lines):
        line = lines[index]
        trimmed = line[base_indent:]
        key, raw_value = trimmed.split(":", 1)
        key = key.strip()
        value = raw_value.strip()
        if value:
            result[key] = coerce_scalar(value)
            index += 1
            continue
        index += 1
        nested: list[str] = []
        while index < len(lines) and lines[index].startswith(" " * (base_indent + 2)):
            nested.append(lines[index])
            index += 1
        result[key] = parse_nested_yaml(nested)
    return result


def coerce_scalar(value: str) -> object:
    """スカラ値を Python 値へ変換する。"""
    if value in {"true", "false"}:
        return value == "true"
    return value


def normalize_plan_id(raw_value: str) -> str:
    """plan_id 用の安全な識別子へ変換する。"""
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in raw_value)
    collapsed = "-".join(part for part in cleaned.split("-") if part)
    return collapsed or "plan"


def slug_from_title(raw_value: str) -> str:
    """タイトルから短い slug を作る。"""
    parts = [part for part in normalize_plan_id(raw_value).split("-") if part]
    return "-".join(parts[:4]) or "item"


def request_from_plan(plan: Document) -> str:
    """計画書本文から元の要望行を取り出す。"""
    for line in plan.body.splitlines():
        if line.startswith("要望: "):
            return line.removeprefix("要望: ").strip()
    return str(plan.metadata.get("title", ""))


def build_plan_body(request_text: str) -> str:
    """計画書本文をテンプレート生成する。"""
    lines = [f"# 仕様書兼実行計画書", "", f"要望: {request_text}", ""]
    for section in PLAN_REQUIRED_SECTIONS:
        lines.extend([f"## {section}", f"- TODO: {section} を具体化する", ""])
    return "\n".join(lines).rstrip()


def build_ticket_body(title: str, purpose: str, outputs: list[str], dependencies: list[Dependency]) -> str:
    """チケット本文をテンプレート生成する。"""
    dependency_lines = ["- なし"] if not dependencies else [
        f"- {dependency.ticket_id} ({dependency.required_state})" for dependency in dependencies
    ]
    output_lines = ["- なし"] if not outputs else [f"- {output}" for output in outputs]
    sections: dict[str, list[str]] = {
        "Title": [title],
        "Purpose": [purpose],
        "Inputs": ["- 承認済みの plan と依存成果物"],
        "Outputs": output_lines,
        "Scope": ["- このチケットに紐づく成果物のみを扱う"],
        "Out of Scope": ["- 仕様外の機能追加"],
        "Dependencies": dependency_lines,
        "Steps": ["1. 入力と依存状態を確認する", "2. 成果物を生成または検証する", "3. 状態とログを保存する"],
        "Acceptance Criteria": ["- 指定された成果物が保存される", "- 状態遷移が仕様通りに更新される"],
        "Verification": ["- dry run 実行結果と保存ファイルを確認する"],
        "Risks / Notes": ["- dry run では外部実行を伴わない"],
        "Priority": [DEFAULT_PRIORITY],
        "Owner Role": ["implementation"],
        "Blocking Conditions": ["- 依存未解決または成果物不足"],
        "Rollback / Abort": ["- 失敗時は status を failed または blocked に更新する"],
        "Artifacts Path": [*output_lines],
    }
    lines = ["# Ticket", ""]
    for name in TICKET_REQUIRED_SECTIONS:
        lines.append(f"## {name}")
        lines.extend(sections[name])
        lines.append("")
    return "\n".join(lines).rstrip()


def parse_dependencies(metadata: dict[str, object]) -> list[Dependency]:
    """front matter から依存配列を復元する。"""
    raw_dependencies = metadata.get("dependencies", [])
    if not isinstance(raw_dependencies, list):
        return []
    dependencies: list[Dependency] = []
    for item in raw_dependencies:
        if not isinstance(item, dict):
            continue
        ticket_id = str(item.get("ticket_id", ""))
        required_state = str(item.get("required_state", ""))
        if ticket_id and required_state:
            dependencies.append(Dependency(ticket_id=ticket_id, required_state=required_state))
    return dependencies


def load_ticket(ticket_id: str, base_dir: Path | None = None) -> Document:
    """チケット文書を読み込む。"""
    return parse_document(artifacts_root(base_dir) / "tickets" / f"{ticket_id}.md")


def write_ticket(ticket_id: str, metadata: dict[str, object], body: str, base_dir: Path | None = None) -> None:
    """チケット文書を書き込む。"""
    write_document(artifacts_root(base_dir) / "tickets" / f"{ticket_id}.md", metadata, body)


def load_plan(plan_id: str, base_dir: Path | None = None) -> Document:
    """計画書を読み込む。"""
    return parse_document(artifacts_root(base_dir) / "plans" / f"{plan_id}.md")


def build_run_artifacts(ticket_id: str, base_dir: Path | None = None, run_id: str | None = None) -> RunArtifacts:
    """実行ごとのログ保存先を組み立てる。"""
    resolved_run_id = run_id or generate_run_id()
    root = artifacts_root(base_dir)
    return RunArtifacts(
        run_id=resolved_run_id,
        log_path=root / "logs" / f"{ticket_id}-{resolved_run_id}.jsonl",
        message_path=root / "messages" / f"{ticket_id}-{resolved_run_id}.txt",
    )


def latest_log_path_from_metadata(metadata: Mapping[str, object], base_dir: Path | None = None) -> Path | None:
    """チケット metadata に保存された最新ログパスを返す。"""
    raw_path = metadata.get("latest_log_path")
    if not isinstance(raw_path, str) or not raw_path:
        return None
    return runtime_root(base_dir) / raw_path


def write_log(path: Path, message: str) -> Path:
    """ログファイルへ生文字列を追記する。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(message.rstrip() + "\n")
    return path


def reset_log(path: Path) -> Path:
    """ログファイルを新規作成し直す。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    return path


def log_event(
    ticket_id: str,
    event: str,
    log_path: Path,
    **fields: object,
) -> Path:
    """JSONL 形式のイベントログを追記する。"""
    payload: dict[str, object] = {
        "timestamp": utc_now(),
        "event": event,
        "ticket_id": ticket_id,
    }
    for key, value in fields.items():
        if value is not None:
            payload[key] = value
    return write_log(log_path, json.dumps(payload, ensure_ascii=False))


def update_ticket_status(
    ticket_id: str,
    next_status: str,
    base_dir: Path | None = None,
    *,
    reason: str = "",
    log_path: Path | None = None,
) -> None:
    """チケット状態を更新し、状態遷移をログへ残す。"""
    document = load_ticket(ticket_id, base_dir)
    previous_status = str(document.metadata.get("status"))
    document.metadata["status"] = next_status
    write_ticket(ticket_id, document.metadata, document.body, base_dir)
    resolved_log_path = log_path or latest_log_path_from_metadata(document.metadata, base_dir)
    if resolved_log_path is None:
        resolved_log_path = artifacts_root(base_dir) / "logs" / f"{ticket_id}.jsonl"
    log_event(
        ticket_id,
        "status_transition",
        resolved_log_path,
        before=previous_status,
        after=next_status,
        reason=reason,
    )


def write_review_result(
    ticket_id: str,
    target_ticket_id: str,
    result: str,
    escalation_needed: bool,
    base_dir: Path | None = None,
) -> Path:
    """レビュー結果ファイルを保存する。"""
    metadata = {
        "ticket_id": ticket_id,
        "target_ticket_id": target_ticket_id,
        "result": result,
        "escalation_needed": str(escalation_needed).lower(),
    }
    body = "\n".join(
        [
            "# Review Result",
            "",
            "## 確認した受け入れ条件",
            "- 成果物が存在すること",
            "- 状態遷移が仕様に沿うこと",
            "",
            "## 残リスク",
            "- dry run のため外部統合は未検証",
            "",
            "## 人間エスカレーション要否",
            f"- {'必要' if escalation_needed else '不要'}",
        ]
    )
    path = artifacts_root(base_dir) / "reviews" / f"{ticket_id}.md"
    write_document(path, metadata, body)
    return path


def load_all_tickets(base_dir: Path | None = None) -> list[Document]:
    """全チケットを読み込む。"""
    ticket_dir = artifacts_root(base_dir) / "tickets"
    if not ticket_dir.exists():
        return []
    return [parse_document(path) for path in sorted(ticket_dir.glob("*.md"))]


def validate_plan_for_approval(document: Document) -> list[str]:
    """承認前の最低限検証を行う。"""
    errors: list[str] = []
    status = str(document.metadata.get("status", ""))
    if status not in PLAN_STATUSES:
        errors.append("status is invalid")
    for section in PLAN_REQUIRED_SECTIONS:
        if f"## {section}" not in document.body:
            errors.append(f"missing section: {section}")
    for must_have in ["未確定事項", "差し戻し条件", "検証戦略"]:
        if section_is_blank(document.body, must_have):
            errors.append(f"section is empty: {must_have}")
    return errors


def validate_ticket_document(document: Document) -> list[str]:
    """チケットの必須項目を検証する。"""
    errors: list[str] = []
    status = str(document.metadata.get("status", ""))
    if status not in TICKET_STATUSES:
        errors.append("ticket status is invalid")
    for section in TICKET_REQUIRED_SECTIONS:
        if f"## {section}" not in document.body:
            errors.append(f"missing section: {section}")
    return errors


def section_is_blank(body: str, section_name: str) -> bool:
    """指定 section に TODO しか無い状態を空扱いする。"""
    marker = f"## {section_name}\n"
    if marker not in body:
        return True
    _, tail = body.split(marker, 1)
    next_heading = tail.find("\n## ")
    section_body = tail if next_heading == -1 else tail[:next_heading]
    meaningful_lines = [line.strip() for line in section_body.splitlines() if line.strip()]
    if not meaningful_lines:
        return True
    return all("TODO" in line for line in meaningful_lines)


def save_plan(request_text: str, plan_id: str | None = None, base_dir: Path | None = None) -> Path:
    """計画書を新規生成または更新する。"""
    ensure_artifact_dirs(base_dir)
    created_at = utc_now()
    if plan_id is None:
        generated_id = normalize_plan_id(request_text)[:32]
        unique_suffix = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        plan_id = f"{generated_id}-{unique_suffix}"
    path = artifacts_root(base_dir) / "plans" / f"{plan_id}.md"
    title = request_text.splitlines()[0][:80]
    if path.exists():
        document = parse_document(path)
        created_at = str(document.metadata.get("created_at", created_at))
    metadata = {
        "plan_id": plan_id,
        "title": title,
        "status": "draft",
        "created_at": created_at,
        "updated_at": utc_now(),
    }
    body = build_plan_body(request_text)
    write_document(path, metadata, body)
    return path


def update_plan_status(plan_id: str, next_status: str, base_dir: Path | None = None) -> Path:
    """計画書状態を更新する。"""
    path = artifacts_root(base_dir) / "plans" / f"{plan_id}.md"
    document = parse_document(path)
    errors = validate_plan_for_approval(document)
    if errors:
        raise typer.Exit(1, "\n".join(errors))
    current_status = str(document.metadata.get("status"))
    if next_status == "in_review" and current_status in {"draft", "approved", "in_review"}:
        document.metadata["status"] = "in_review"
    elif next_status == "approved" and current_status == "in_review":
        document.metadata["status"] = "approved"
    else:
        raise typer.Exit(1, f"invalid status transition: {current_status} -> {next_status}")
    document.metadata["updated_at"] = utc_now()
    write_document(path, document.metadata, document.body)
    return path


def build_ticket_set(plan_id: str, base_dir: Path | None = None) -> list[Path]:
    """承認済み計画から定型チケット群を生成する。"""
    ensure_artifact_dirs(base_dir)
    plan = load_plan(plan_id, base_dir)
    if str(plan.metadata.get("status")) != "approved":
        raise typer.Exit(1, "plan must be approved before ticket generation")

    slug = slug_from_title(str(plan.metadata.get("title", plan_id)))
    worker_id = f"{plan_id}-worker-{slug}"
    review_id = f"{plan_id}-review-{slug}"
    integration_id = f"{plan_id}-integration-{slug}"
    root_id = f"{plan_id}-root"

    ticket_specs: list[dict[str, object]] = [
        {
            "ticket_id": worker_id,
            "ticket_type": "worker",
            "status": "todo",
            "owner_role": "implementation",
            "priority": DEFAULT_PRIORITY,
            "plan_id": plan_id,
            "dependencies": [],
            "outputs": [
                f"artifacts/logs/{worker_id}-<run_id>.jsonl",
                f"artifacts/messages/{worker_id}-<run_id>.txt",
            ],
            "body": build_ticket_body(
                title=f"Implement {slug}",
                purpose="承認済み計画に対する最小実装とローカル検証を行う",
                outputs=[
                    f"artifacts/logs/{worker_id}-<run_id>.jsonl",
                    f"artifacts/messages/{worker_id}-<run_id>.txt",
                ],
                dependencies=[],
            ),
        },
        {
            "ticket_id": review_id,
            "ticket_type": "review",
            "status": "todo",
            "owner_role": "review",
            "priority": DEFAULT_PRIORITY,
            "plan_id": plan_id,
            "dependencies": [{"ticket_id": worker_id, "required_state": "review_pending"}],
            "outputs": [f"artifacts/reviews/{review_id}.md"],
            "target_ticket_id": worker_id,
            "body": build_ticket_body(
                title=f"Review {slug}",
                purpose="worker ticket の成果物と受け入れ条件を検証する",
                outputs=[f"artifacts/reviews/{review_id}.md"],
                dependencies=[Dependency(worker_id, "review_pending")],
            ),
        },
        {
            "ticket_id": integration_id,
            "ticket_type": "integration",
            "status": "todo",
            "owner_role": "integration",
            "priority": DEFAULT_PRIORITY,
            "plan_id": plan_id,
            "dependencies": [{"ticket_id": review_id, "required_state": "done"}],
            "outputs": [f"artifacts/reviews/{integration_id}.md"],
            "target_ticket_id": review_id,
            "body": build_ticket_body(
                title=f"Integrate {slug}",
                purpose="review ticket の完了後に統合確認を行う",
                outputs=[f"artifacts/reviews/{integration_id}.md"],
                dependencies=[Dependency(review_id, "done")],
            ),
        },
        {
            "ticket_id": root_id,
            "ticket_type": "root",
            "status": "todo",
            "owner_role": "orchestrator",
            "priority": DEFAULT_PRIORITY,
            "plan_id": plan_id,
            "dependencies": [{"ticket_id": integration_id, "required_state": "done"}],
            "children": [worker_id, review_id, integration_id],
            "outputs": [f"artifacts/logs/{root_id}-<run_id>.jsonl"],
            "body": build_ticket_body(
                title=f"Root {slug}",
                purpose="配下チケットの依存に従って実行全体を管理する",
                outputs=[f"artifacts/logs/{root_id}-<run_id>.jsonl"],
                dependencies=[Dependency(integration_id, "done")],
            ),
        },
    ]

    paths: list[Path] = []
    for spec in ticket_specs:
        metadata = cast(dict[str, object], {key: value for key, value in spec.items() if key != "body"})
        body = str(spec["body"])
        path = artifacts_root(base_dir) / "tickets" / f"{spec['ticket_id']}.md"
        write_document(path, metadata, body)
        paths.append(path)
    return paths


def dependency_satisfied(dependency: Dependency, base_dir: Path | None = None) -> bool:
    """依存チケット状態を確認する。"""
    try:
        document = load_ticket(dependency.ticket_id, base_dir)
    except FileNotFoundError:
        return False
    return str(document.metadata.get("status")) == dependency.required_state


def create_run_graph(
    base_dir: Path | None = None,
    run_config: RunConfig | None = None,
    run_artifacts: RunArtifacts | None = None,
) -> Callable[[RunState], RunState]:
    """実行モードごとのワークフローを構築する。"""
    config = run_config or RunConfig()
    artifacts = run_artifacts or build_run_artifacts("unknown", base_dir)
    graph = StateGraph(RunState)
    graph.add_node("load", cast(Any, lambda state: node_load(cast(RunState, state), base_dir, artifacts)))
    graph.add_node("check", cast(Any, lambda state: node_check_dependencies(cast(RunState, state), base_dir, artifacts)))
    graph.add_node("execute", cast(Any, lambda state: node_execute(cast(RunState, state), base_dir, config, artifacts)))
    graph.add_node("finalize", cast(Any, lambda state: node_finalize(cast(RunState, state), base_dir, artifacts)))
    graph.set_entry_point("load")
    graph.add_edge("load", "check")
    graph.add_conditional_edges(
        "check",
        lambda state: "execute" if bool(state["dependencies_ok"]) else "finalize",
        {"execute": "execute", "finalize": "finalize"},
    )
    graph.add_edge("execute", "finalize")
    graph.add_edge("finalize", END)
    return cast(Callable[[RunState], RunState], graph.compile().invoke)


def node_load(state: RunState, base_dir: Path | None, run_artifacts: RunArtifacts) -> RunState:
    """チケット文書を読み込む。"""
    ticket_id = str(state["ticket_id"])
    document = load_ticket(ticket_id, base_dir)
    errors = validate_ticket_document(document)
    if errors:
        raise typer.Exit(1, "\n".join(errors))
    log_event(
        ticket_id,
        "run_load",
        run_artifacts.log_path,
        plan_id=document.metadata.get("plan_id"),
        ticket_type=document.metadata.get("ticket_type"),
        status=document.metadata.get("status"),
    )
    state["document"] = document
    state["dependencies"] = parse_dependencies(document.metadata)
    return state


def node_check_dependencies(state: RunState, base_dir: Path | None, run_artifacts: RunArtifacts) -> RunState:
    """依存解決可否を確認する。"""
    dependencies = cast(list[Dependency], state.get("dependencies", []))
    missing = [dependency for dependency in dependencies if not dependency_satisfied(dependency, base_dir)]
    state["dependencies_ok"] = not missing
    state["missing_dependencies"] = missing
    log_event(
        str(cast(Document, state.get("document")).metadata["ticket_id"]),
        "dependency_check",
        run_artifacts.log_path,
        dependencies=[dependency.__dict__ for dependency in dependencies],
        missing=[dependency.__dict__ for dependency in missing],
        dependencies_ok=not missing,
    )
    return state


def node_execute(
    state: RunState,
    base_dir: Path | None,
    run_config: RunConfig,
    run_artifacts: RunArtifacts,
) -> RunState:
    """チケット種別ごとの処理を実行する。"""
    document = cast(Document, state.get("document"))
    metadata = document.metadata
    ticket_id = str(metadata["ticket_id"])
    ticket_type = str(metadata["ticket_type"])
    previous_status = str(metadata.get("status"))
    metadata["status"] = "running"
    write_ticket(ticket_id, metadata, document.body, base_dir)
    log_event(
        ticket_id,
        "status_transition",
        run_artifacts.log_path,
        before=previous_status,
        after="running",
        reason="execution started",
    )
    log_event(
        ticket_id,
        "execute_start",
        run_artifacts.log_path,
        ticket_type=ticket_type,
        mode=run_config.mode,
        model=run_config.model,
        reasoning_effort=run_config.reasoning_effort,
    )

    # 種別とモードごとの最小処理を行う。
    if ticket_type == "worker":
        result = execute_worker_ticket(ticket_id, metadata, base_dir, run_config, run_artifacts)
    elif ticket_type == "review":
        result = execute_review_ticket(ticket_id, metadata, base_dir, run_config, run_artifacts)
    elif ticket_type == "integration":
        result = execute_integration_ticket(ticket_id, metadata, base_dir, run_config, run_artifacts)
    elif ticket_type == "root":
        result = execute_root_ticket(ticket_id, metadata, base_dir, run_artifacts)
    else:
        metadata["status"] = "failed"
        log_event(ticket_id, "execute_unknown_ticket_type", run_artifacts.log_path, ticket_type=ticket_type)
        result = [str(run_artifacts.log_path.relative_to(runtime_root(base_dir)))]

    state["artifacts"] = result
    write_ticket(ticket_id, metadata, document.body, base_dir)
    state["document"] = load_ticket(ticket_id, base_dir)
    log_event(
        ticket_id,
        "execute_end",
        run_artifacts.log_path,
        status=metadata.get("status"),
        artifacts=result,
    )
    return state


def execute_worker_ticket(
    ticket_id: str,
    metadata: dict[str, object],
    base_dir: Path | None,
    run_config: RunConfig,
    run_artifacts: RunArtifacts,
) -> list[str]:
    """worker ticket を実行する。"""
    if run_config.mode == "dry-run":
        log_event(ticket_id, "worker_dry_run", run_artifacts.log_path, mode=run_config.mode)
        metadata["status"] = "review_pending"
        log_event(
            ticket_id,
            "status_transition",
            run_artifacts.log_path,
            before="running",
            after="review_pending",
            reason="dry run completed",
        )
        return [str(run_artifacts.log_path.relative_to(runtime_root(base_dir)))]

    completed = run_codex_for_ticket(ticket_id, metadata, base_dir, run_config, run_artifacts)
    if completed.returncode == 0:
        metadata["status"] = "review_pending"
        log_event(
            ticket_id,
            "status_transition",
            run_artifacts.log_path,
            before="running",
            after="review_pending",
            reason="codex execution completed",
        )
    else:
        metadata["status"] = "failed"
        log_event(
            ticket_id,
            "status_transition",
            run_artifacts.log_path,
            before="running",
            after="failed",
            reason="codex execution failed",
        )
    artifacts = [str(run_artifacts.log_path.relative_to(runtime_root(base_dir)))]
    if run_artifacts.message_path.exists():
        artifacts.append(str(run_artifacts.message_path.relative_to(runtime_root(base_dir))))
    return artifacts


def execute_review_ticket(
    ticket_id: str,
    metadata: dict[str, object],
    base_dir: Path | None,
    run_config: RunConfig,
    run_artifacts: RunArtifacts,
) -> list[str]:
    """review ticket を実行する。"""
    target_ticket_id = str(metadata.get("target_ticket_id", ""))
    target_document = load_ticket(target_ticket_id, base_dir)
    target_status = str(target_document.metadata.get("status"))
    if target_status != "review_pending":
        metadata["status"] = "blocked"
        log_event(
            ticket_id,
            "review_blocked",
            run_artifacts.log_path,
            target_ticket_id=target_ticket_id,
            target_status=target_status,
            reason="target is not review_pending",
        )
        return []

    if run_config.mode == "dry-run":
        review_path = write_review_result(ticket_id, target_ticket_id, "pass", False, base_dir)
        metadata["status"] = "done"
        log_event(
            ticket_id,
            "status_transition",
            run_artifacts.log_path,
            before="running",
            after="done",
            reason="dry run review passed",
        )
        update_ticket_status(target_ticket_id, "done", base_dir, reason=f"review ticket {ticket_id} passed")
        return [
            str(review_path.relative_to(runtime_root(base_dir))),
            str(run_artifacts.log_path.relative_to(runtime_root(base_dir))),
        ]

    passed, details = run_acceptance_gate(ticket_id, base_dir)
    log_event(ticket_id, "acceptance_gate", run_artifacts.log_path, **details)
    review_path = write_review_result(ticket_id, target_ticket_id, "pass" if passed else "fail", not passed, base_dir)
    metadata["status"] = "done" if passed else "failed"
    log_event(
        ticket_id,
        "status_transition",
        run_artifacts.log_path,
        before="running",
        after=metadata["status"],
        reason="acceptance gate completed",
    )
    update_ticket_status(
        target_ticket_id,
        "done" if passed else "failed",
        base_dir,
        reason=f"review ticket {ticket_id} {'passed' if passed else 'failed'}",
    )
    return [
        str(review_path.relative_to(runtime_root(base_dir))),
        str(run_artifacts.log_path.relative_to(runtime_root(base_dir))),
    ]


def execute_integration_ticket(
    ticket_id: str,
    metadata: dict[str, object],
    base_dir: Path | None,
    run_config: RunConfig,
    run_artifacts: RunArtifacts,
) -> list[str]:
    """integration ticket を実行する。"""
    target_ticket_id = str(metadata.get("target_ticket_id", ""))
    if run_config.mode == "dry-run":
        review_path = write_review_result(ticket_id, target_ticket_id, "pass", False, base_dir)
        metadata["status"] = "done"
        log_event(
            ticket_id,
            "status_transition",
            run_artifacts.log_path,
            before="running",
            after="done",
            reason="dry run integration passed",
        )
        return [
            str(review_path.relative_to(runtime_root(base_dir))),
            str(run_artifacts.log_path.relative_to(runtime_root(base_dir))),
        ]

    passed, details = run_acceptance_gate(ticket_id, base_dir)
    log_event(ticket_id, "acceptance_gate", run_artifacts.log_path, **details)
    review_path = write_review_result(ticket_id, target_ticket_id, "pass" if passed else "fail", not passed, base_dir)
    metadata["status"] = "done" if passed else "failed"
    log_event(
        ticket_id,
        "status_transition",
        run_artifacts.log_path,
        before="running",
        after=metadata["status"],
        reason="integration gate completed",
    )
    return [
        str(review_path.relative_to(runtime_root(base_dir))),
        str(run_artifacts.log_path.relative_to(runtime_root(base_dir))),
    ]


def execute_root_ticket(
    ticket_id: str,
    metadata: dict[str, object],
    base_dir: Path | None,
    run_artifacts: RunArtifacts,
) -> list[str]:
    """root ticket を実行する。"""
    children = metadata.get("children", [])
    if not isinstance(children, list):
        children = []
    child_ids = [str(child) for child in children]
    if child_ids and all(str(load_ticket(child, base_dir).metadata.get("status")) == "done" for child in child_ids):
        metadata["status"] = "done"
    else:
        metadata["status"] = "running"
    log_event(ticket_id, "root_evaluated_children", run_artifacts.log_path, children=child_ids, status=metadata["status"])
    return [str(run_artifacts.log_path.relative_to(runtime_root(base_dir)))]


def build_codex_prompt(ticket_id: str, metadata: dict[str, object], base_dir: Path | None) -> str:
    """worker ticket 向けの Codex プロンプトを組み立てる。"""
    plan = load_plan(str(metadata["plan_id"]), base_dir)
    request_text = request_from_plan(plan)
    lines = [
        "承認済み plan に従って、現在のリポジトリへ最小変更で実装してください。",
        "日本語で考えてよいですが、コード・ログメッセージは既存規約に従ってください。",
        "作業後に、実施した変更と実行した検証を簡潔に最終メッセージへ書いてください。",
        f"ticket_id: {ticket_id}",
        f"plan_id: {metadata['plan_id']}",
        f"request: {request_text}",
        "",
        "plan body:",
        plan.body,
    ]
    return "\n".join(lines)


def run_codex_for_ticket(
    ticket_id: str,
    metadata: dict[str, object],
    base_dir: Path | None,
    run_config: RunConfig,
    run_artifacts: RunArtifacts,
) -> subprocess.CompletedProcess[str]:
    """Codex CLI を呼び出して worker ticket を実行する。"""
    prompt = build_codex_prompt(ticket_id, metadata, base_dir)
    command = [
        "codex",
        "exec",
        "--model",
        run_config.model,
        "-c",
        f'model_reasoning_effort="{run_config.reasoning_effort}"',
        "--sandbox",
        "workspace-write",
        "--skip-git-repo-check",
        "--cd",
        str(runtime_root(base_dir)),
        "--output-last-message",
        str(run_artifacts.message_path),
        prompt,
    ]
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    log_event(
        ticket_id,
        "external_command",
        run_artifacts.log_path,
        command=command,
        returncode=completed.returncode,
        stdout=completed.stdout.rstrip(),
        stderr=completed.stderr.rstrip(),
    )
    return completed


def run_acceptance_gate(ticket_id: str, base_dir: Path | None) -> tuple[bool, dict[str, object]]:
    """本番モードの review / integration 用受け入れゲートを実行する。"""
    workdir = runtime_root(base_dir)
    tests_dir = workdir / "tests"
    if not tests_dir.exists():
        return True, {
            "command": None,
            "returncode": 0,
            "stdout": "",
            "stderr": "",
            "result": "no tests directory; existence check only",
        }

    command = [sys.executable, "-m", "pytest", "-q"]
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        cwd=workdir,
    )
    return completed.returncode == 0, {
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout.rstrip(),
        "stderr": completed.stderr.rstrip(),
    }


def node_finalize(state: RunState, base_dir: Path | None, run_artifacts: RunArtifacts) -> RunState:
    """依存未解決時や終了時の状態を確定する。"""
    document = cast(Document, state.get("document"))
    metadata = document.metadata
    if not bool(state.get("dependencies_ok", False)):
        metadata["status"] = "blocked"
        missing = [
            {"ticket_id": dependency.ticket_id, "required_state": dependency.required_state}
            for dependency in cast(list[Dependency], state.get("missing_dependencies", []))
        ]
        log_event(
            str(metadata["ticket_id"]),
            "status_transition",
            run_artifacts.log_path,
            before="running",
            after="blocked",
            reason="missing dependencies",
            missing_dependencies=missing,
        )
        write_ticket(str(metadata["ticket_id"]), metadata, document.body, base_dir)
        state["document"] = load_ticket(str(metadata["ticket_id"]), base_dir)
    return state


def run_ticket(
    ticket_id: str,
    base_dir: Path | None = None,
    run_config: RunConfig | None = None,
) -> dict[str, object]:
    """単一チケットを実行する。"""
    ensure_artifact_dirs(base_dir)
    config = run_config or RunConfig()
    run_artifacts = build_run_artifacts(ticket_id, base_dir)
    reset_log(run_artifacts.log_path)
    document = load_ticket(ticket_id, base_dir)
    # 実行ごとの成果物を後続チケットや artifact 一覧から辿れるようにする。
    document.metadata["latest_run_id"] = run_artifacts.run_id
    document.metadata["latest_log_path"] = str(run_artifacts.log_path.relative_to(runtime_root(base_dir)))
    document.metadata["latest_message_path"] = str(run_artifacts.message_path.relative_to(runtime_root(base_dir)))
    write_ticket(ticket_id, document.metadata, document.body, base_dir)
    log_event(
        ticket_id,
        "run_started",
        run_artifacts.log_path,
        plan_id=document.metadata.get("plan_id"),
        ticket_type=document.metadata.get("ticket_type"),
        initial_status=document.metadata.get("status"),
        mode=config.mode,
        model=config.model,
        reasoning_effort=config.reasoning_effort,
        run_id=run_artifacts.run_id,
    )
    state = create_run_graph(base_dir, config, run_artifacts)({"ticket_id": ticket_id})
    document = cast(Document, state.get("document"))
    metadata = document.metadata
    result = {
        "ticket_id": metadata["ticket_id"],
        "ticket_type": metadata["ticket_type"],
        "status": metadata["status"],
        "run_id": run_artifacts.run_id,
        "artifacts": state.get("artifacts", []),
        "missing_dependencies": [
            {"ticket_id": dependency.ticket_id, "required_state": dependency.required_state}
            for dependency in cast(list[Dependency], state.get("missing_dependencies", []))
        ],
    }
    log_event(ticket_id, "run_finished", run_artifacts.log_path, result=result)
    return result


def run_root_ticket(
    ticket_id: str,
    base_dir: Path | None = None,
    run_config: RunConfig | None = None,
) -> list[dict[str, object]]:
    """root ticket 配下を依存順で逐次実行する。"""
    root_document = load_ticket(ticket_id, base_dir)
    children = root_document.metadata.get("children", [])
    if not isinstance(children, list):
        children = []
    ordered_ids = [str(child) for child in children] + [ticket_id]
    config = run_config or RunConfig()
    return [run_ticket(current_id, base_dir, config) for current_id in ordered_ids]


def collect_review_queue(base_dir: Path | None = None) -> list[dict[str, object]]:
    """review_pending チケット一覧を返す。"""
    queue: list[dict[str, object]] = []
    for document in load_all_tickets(base_dir):
        metadata = document.metadata
        if str(metadata.get("status")) != "review_pending":
            continue
        queue.append(
            {
                "ticket_id": str(metadata.get("ticket_id")),
                "ticket_type": str(metadata.get("ticket_type")),
                "status": str(metadata.get("status")),
                "priority": str(metadata.get("priority")),
                "dependencies": [
                    {"ticket_id": dependency.ticket_id, "required_state": dependency.required_state}
                    for dependency in parse_dependencies(metadata)
                ],
            }
        )
    return queue


def collect_artifacts(identifier: str, base_dir: Path | None = None) -> dict[str, list[dict[str, str]]]:
    """plan_id または ticket_id に紐づく成果物一覧を返す。"""
    root = artifacts_root(base_dir)
    result: dict[str, list[dict[str, str]]] = {"items": []}
    plan_path = root / "plans" / f"{identifier}.md"
    ticket_path = root / "tickets" / f"{identifier}.md"
    if plan_path.exists():
        result["items"].append({"kind": "plan", "path": str(plan_path.relative_to(runtime_root(base_dir))), "exists": "true"})
        for document in load_all_tickets(base_dir):
            if str(document.metadata.get("plan_id")) != identifier:
                continue
            ticket_id = str(document.metadata.get("ticket_id"))
            result["items"].extend(collect_artifacts(ticket_id, base_dir)["items"])
        return result
    if ticket_path.exists():
        document = parse_document(ticket_path)
        result["items"].append({"kind": "ticket", "path": str(ticket_path.relative_to(runtime_root(base_dir))), "exists": "true"})
        outputs = document.metadata.get("outputs", [])
        if isinstance(outputs, list):
            for output in outputs:
                output_path = runtime_root(base_dir) / str(output)
                result["items"].append(
                    {"kind": "output", "path": str(output), "exists": str(output_path.exists()).lower()}
                )
        review_path = root / "reviews" / f"{identifier}.md"
        for kind, path in [("review", review_path)]:
            result["items"].append(
                {"kind": kind, "path": str(path.relative_to(runtime_root(base_dir))), "exists": str(path.exists()).lower()}
            )
        for path in sorted((root / "logs").glob(f"{identifier}-*.jsonl")):
            result["items"].append({"kind": "log", "path": str(path.relative_to(runtime_root(base_dir))), "exists": "true"})
        for path in sorted((root / "messages").glob(f"{identifier}-*.txt")):
            result["items"].append(
                {"kind": "message", "path": str(path.relative_to(runtime_root(base_dir))), "exists": "true"}
            )
        return result
    raise typer.Exit(1, f"identifier not found: {identifier}")


@APP.command()
def plan(request_text: str, plan_id: str | None = None) -> None:
    """計画書を生成または更新する。"""
    path = save_plan(request_text=request_text, plan_id=plan_id)
    typer.echo(str(path.relative_to(runtime_root())))


@APP.command()
def approve(plan_id: str, status: str) -> None:
    """計画書状態を更新する。"""
    path = update_plan_status(plan_id=plan_id, next_status=status)
    typer.echo(str(path.relative_to(runtime_root())))


@APP.command()
def ticket(plan_id: str) -> None:
    """承認済み計画からチケット群を生成する。"""
    paths = build_ticket_set(plan_id=plan_id)
    for path in paths:
        typer.echo(str(path.relative_to(runtime_root())))


@APP.command()
def run(
    ticket_id: str,
    mode: str = "dry-run",
    model: str = DEFAULT_PRODUCTION_MODEL,
    reasoning_effort: str = DEFAULT_REASONING_EFFORT,
) -> None:
    """チケットまたは root ticket を実行する。"""
    if mode not in RUN_MODES:
        raise typer.Exit(1, f"invalid mode: {mode}")
    run_config = RunConfig(mode=mode, model=model, reasoning_effort=reasoning_effort)
    document = load_ticket(ticket_id)
    if str(document.metadata.get("ticket_type")) == "root":
        result = run_root_ticket(ticket_id, run_config=run_config)
    else:
        result = [run_ticket(ticket_id, run_config=run_config)]
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@review_app.command("queue")
def review_queue() -> None:
    """review_pending 一覧を表示する。"""
    typer.echo(json.dumps(collect_review_queue(), ensure_ascii=False, indent=2))


@APP.command()
def artifacts(identifier: str) -> None:
    """成果物パス一覧を表示する。"""
    typer.echo(json.dumps(collect_artifacts(identifier), ensure_ascii=False, indent=2))


def main(argv: Sequence[str] | None = None) -> None:
    """CLI エントリーポイント。"""
    APP(argv=list(argv) if argv is not None else None)


if __name__ == "__main__":
    main()
