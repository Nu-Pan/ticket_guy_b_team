"""ticket_guy_b_team の CLI 本体。"""

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence, cast

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
DEFAULT_PRIORITY = "high"
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


def utc_now() -> str:
    """現在時刻を UTC 文字列で返す。"""
    return datetime.now(timezone.utc).strftime(TIMESTAMP_FORMAT)


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
    for relative in ["plans", "tickets", "reviews", "logs"]:
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
    output_lines = [f"- {output}" for output in outputs]
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


def write_log(ticket_id: str, message: str, base_dir: Path | None = None) -> Path:
    """ログファイルを保存する。"""
    path = artifacts_root(base_dir) / "logs" / f"{ticket_id}.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(message.rstrip() + "\n", encoding="utf-8")
    return path


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
            "outputs": [f"artifacts/logs/{worker_id}.log"],
            "body": build_ticket_body(
                title=f"Implement {slug}",
                purpose="承認済み計画に対する最小実装とローカル検証を行う",
                outputs=[f"artifacts/logs/{worker_id}.log"],
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
            "outputs": [f"artifacts/logs/{root_id}.log"],
            "body": build_ticket_body(
                title=f"Root {slug}",
                purpose="配下チケットの依存に従って実行全体を管理する",
                outputs=[f"artifacts/logs/{root_id}.log"],
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


def update_ticket_status(ticket_id: str, next_status: str, base_dir: Path | None = None) -> None:
    """チケット状態を更新する。"""
    document = load_ticket(ticket_id, base_dir)
    document.metadata["status"] = next_status
    write_ticket(ticket_id, document.metadata, document.body, base_dir)


def create_run_graph(base_dir: Path | None = None) -> Callable[[dict[str, object]], dict[str, object]]:
    """dry run 用のワークフローを構築する。"""
    graph = StateGraph(dict)
    graph.add_node("load", lambda state: node_load(state, base_dir))
    graph.add_node("check", lambda state: node_check_dependencies(state, base_dir))
    graph.add_node("execute", lambda state: node_execute(state, base_dir))
    graph.add_node("finalize", lambda state: node_finalize(state, base_dir))
    graph.set_entry_point("load")
    graph.add_edge("load", "check")
    graph.add_conditional_edges(
        "check",
        lambda state: "execute" if bool(state["dependencies_ok"]) else "finalize",
        {"execute": "execute", "finalize": "finalize"},
    )
    graph.add_edge("execute", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile().invoke


def node_load(state: dict[str, object], base_dir: Path | None) -> dict[str, object]:
    """チケット文書を読み込む。"""
    ticket_id = str(state["ticket_id"])
    document = load_ticket(ticket_id, base_dir)
    errors = validate_ticket_document(document)
    if errors:
        raise typer.Exit(1, "\n".join(errors))
    state["document"] = document
    state["dependencies"] = parse_dependencies(document.metadata)
    return state


def node_check_dependencies(state: dict[str, object], base_dir: Path | None) -> dict[str, object]:
    """依存解決可否を確認する。"""
    dependencies = cast(list[Dependency], state["dependencies"])
    missing = [dependency for dependency in dependencies if not dependency_satisfied(dependency, base_dir)]
    state["dependencies_ok"] = not missing
    state["missing_dependencies"] = missing
    return state


def node_execute(state: dict[str, object], base_dir: Path | None) -> dict[str, object]:
    """チケット種別ごとの dry run を実行する。"""
    document = cast(Document, state["document"])
    metadata = document.metadata
    ticket_id = str(metadata["ticket_id"])
    ticket_type = str(metadata["ticket_type"])
    metadata["status"] = "running"
    write_ticket(ticket_id, metadata, document.body, base_dir)

    # 種別ごとの最小成果物を出力する。
    if ticket_type == "worker":
        log_path = write_log(ticket_id, "worker executed in dry run mode", base_dir)
        metadata["status"] = "review_pending"
        state["artifacts"] = [str(log_path.relative_to(runtime_root(base_dir)))]
    elif ticket_type == "review":
        target_ticket_id = str(metadata.get("target_ticket_id", ""))
        target_document = load_ticket(target_ticket_id, base_dir)
        target_status = str(target_document.metadata.get("status"))
        if target_status != "review_pending":
            metadata["status"] = "blocked"
            write_log(ticket_id, "review blocked because target is not review_pending", base_dir)
            state["artifacts"] = []
        else:
            review_path = write_review_result(ticket_id, target_ticket_id, "pass", False, base_dir)
            metadata["status"] = "done"
            update_ticket_status(target_ticket_id, "done", base_dir)
            state["artifacts"] = [str(review_path.relative_to(runtime_root(base_dir)))]
    elif ticket_type == "integration":
        target_ticket_id = str(metadata.get("target_ticket_id", ""))
        review_path = write_review_result(ticket_id, target_ticket_id, "pass", False, base_dir)
        metadata["status"] = "done"
        state["artifacts"] = [str(review_path.relative_to(runtime_root(base_dir)))]
    elif ticket_type == "root":
        children = metadata.get("children", [])
        if not isinstance(children, list):
            children = []
        child_ids = [str(child) for child in children]
        if child_ids and all(str(load_ticket(child, base_dir).metadata.get("status")) == "done" for child in child_ids):
            metadata["status"] = "done"
        else:
            metadata["status"] = "running"
        log_path = write_log(ticket_id, f"root evaluated children={json.dumps(child_ids)}", base_dir)
        state["artifacts"] = [str(log_path.relative_to(runtime_root(base_dir)))]
    else:
        metadata["status"] = "failed"
        write_log(ticket_id, f"unknown ticket type: {ticket_type}", base_dir)
        state["artifacts"] = []

    write_ticket(ticket_id, metadata, document.body, base_dir)
    state["document"] = load_ticket(ticket_id, base_dir)
    return state


def node_finalize(state: dict[str, object], base_dir: Path | None) -> dict[str, object]:
    """依存未解決時や終了時の状態を確定する。"""
    document = cast(Document, state["document"])
    metadata = document.metadata
    if not bool(state["dependencies_ok"]):
        metadata["status"] = "blocked"
        missing = [
            {"ticket_id": dependency.ticket_id, "required_state": dependency.required_state}
            for dependency in cast(list[Dependency], state["missing_dependencies"])
        ]
        write_log(str(metadata["ticket_id"]), f"blocked: {json.dumps(missing)}", base_dir)
        write_ticket(str(metadata["ticket_id"]), metadata, document.body, base_dir)
        state["document"] = load_ticket(str(metadata["ticket_id"]), base_dir)
    return state


def run_ticket(ticket_id: str, base_dir: Path | None = None) -> dict[str, object]:
    """単一チケットの dry run を実行する。"""
    ensure_artifact_dirs(base_dir)
    state = create_run_graph(base_dir)({"ticket_id": ticket_id})
    document = cast(Document, state["document"])
    metadata = document.metadata
    return {
        "ticket_id": metadata["ticket_id"],
        "ticket_type": metadata["ticket_type"],
        "status": metadata["status"],
        "artifacts": state.get("artifacts", []),
        "missing_dependencies": [
            {"ticket_id": dependency.ticket_id, "required_state": dependency.required_state}
            for dependency in cast(list[Dependency], state.get("missing_dependencies", []))
        ],
    }


def run_root_ticket(ticket_id: str, base_dir: Path | None = None) -> list[dict[str, object]]:
    """root ticket 配下を依存順で逐次 dry run する。"""
    root_document = load_ticket(ticket_id, base_dir)
    children = root_document.metadata.get("children", [])
    if not isinstance(children, list):
        children = []
    ordered_ids = [str(child) for child in children] + [ticket_id]
    return [run_ticket(current_id, base_dir) for current_id in ordered_ids]


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
        log_path = root / "logs" / f"{identifier}.log"
        for kind, path in [("review", review_path), ("log", log_path)]:
            result["items"].append(
                {"kind": kind, "path": str(path.relative_to(runtime_root(base_dir))), "exists": str(path.exists()).lower()}
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
def run(ticket_id: str) -> None:
    """チケットまたは root ticket を dry run 実行する。"""
    document = load_ticket(ticket_id)
    if str(document.metadata.get("ticket_type")) == "root":
        result = run_root_ticket(ticket_id)
    else:
        result = [run_ticket(ticket_id)]
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
