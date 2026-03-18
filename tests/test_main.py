"""CLI 本体の dry run テスト。"""

# pyright: reportMissingImports=false

import io
import json
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import main


def run_cli(tmp_path: Path, *args: str) -> tuple[int, str, str]:
    """CLI を同一プロセス内で実行する。"""
    stdout = io.StringIO()
    stderr = io.StringIO()
    previous_cwd = Path.cwd()
    try:
        import os

        os.chdir(tmp_path)
        with redirect_stdout(stdout), redirect_stderr(stderr):
            try:
                main.main(args)
            except SystemExit as exc:
                exit_code = 0 if exc.code is None else int(exc.code)
                return exit_code, stdout.getvalue(), stderr.getvalue()
        return 0, stdout.getvalue(), stderr.getvalue()
    finally:
        import os

        os.chdir(previous_cwd)


def parse_json_output(exit_code: int, stdout: str, stderr: str) -> Any:
    """標準出力を JSON として読む。"""
    assert exit_code == 0, stderr
    return json.loads(stdout)


def prepare_approvable_plan(plan_path: Path, replacements: dict[str, str]) -> None:
    """承認可能な内容へ最小限書き換える。"""
    text = plan_path.read_text(encoding="utf-8")
    for old, new in replacements.items():
        text = text.replace(old, new)
    plan_path.write_text(text, encoding="utf-8")


def test_plan_to_ticket_and_run_root_flow(tmp_path: Path) -> None:
    """plan 生成から root 実行までの基本フローが動く。"""
    request_text = "CLI で仕様レビュー駆動の作業を整理したい"

    exit_code, stdout, stderr = run_cli(tmp_path, "plan", request_text)
    assert exit_code == 0, stderr
    plan_relpath = Path(stdout.strip())
    plan_path = tmp_path / plan_relpath
    assert plan_path.exists()

    plan_id = plan_path.stem
    prepare_approvable_plan(
        plan_path,
        {
            "TODO: 未確定事項 を具体化する": "未確定の論点は dry run では継続可能と明記する",
            "TODO: 差し戻し条件 を具体化する": "受け入れ条件を満たさない場合は差し戻す",
            "TODO: 検証戦略 を具体化する": "pytest と pyright を優先して実行する",
        },
    )

    assert run_cli(tmp_path, "approve", plan_id, "in_review")[0] == 0
    assert run_cli(tmp_path, "approve", plan_id, "approved")[0] == 0

    exit_code, stdout, stderr = run_cli(tmp_path, "ticket", plan_id)
    assert exit_code == 0, stderr
    ticket_paths = [tmp_path / Path(line) for line in stdout.splitlines() if line.strip()]
    assert len(ticket_paths) == 4
    assert all(path.exists() for path in ticket_paths)

    root_path = next(path for path in ticket_paths if path.stem.endswith("-root"))
    exit_code, stdout, stderr = run_cli(tmp_path, "run", root_path.stem)
    result = parse_json_output(exit_code, stdout, stderr)
    assert isinstance(result, list)
    assert [item["status"] for item in result] == ["review_pending", "done", "done", "done"]

    exit_code, stdout, stderr = run_cli(tmp_path, "review", "queue")
    queue = parse_json_output(exit_code, stdout, stderr)
    assert queue == []

    exit_code, stdout, stderr = run_cli(tmp_path, "artifacts", plan_id)
    artifacts = parse_json_output(exit_code, stdout, stderr)
    artifact_paths = {item["path"]: item["exists"] for item in artifacts["items"]}
    assert any(path.endswith(".log") and exists == "true" for path, exists in artifact_paths.items())
    assert any(path.endswith(".md") and exists == "true" for path, exists in artifact_paths.items())


def test_review_queue_lists_review_pending_worker(tmp_path: Path) -> None:
    """worker 実行後は review queue に現れる。"""
    exit_code, stdout, stderr = run_cli(tmp_path, "plan", "worker の review queue を確認したい")
    assert exit_code == 0, stderr
    plan_id = Path(stdout.strip()).stem
    plan_path = tmp_path / stdout.strip()
    prepare_approvable_plan(
        plan_path,
        {
            "TODO: 未確定事項 を具体化する": "未確定事項は別チケットで管理する",
            "TODO: 差し戻し条件 を具体化する": "仕様不整合なら差し戻す",
            "TODO: 検証戦略 を具体化する": "dry run で pytest を実行する",
        },
    )

    assert run_cli(tmp_path, "approve", plan_id, "in_review")[0] == 0
    assert run_cli(tmp_path, "approve", plan_id, "approved")[0] == 0
    _, stdout, _ = run_cli(tmp_path, "ticket", plan_id)
    worker_id = next(Path(line).stem for line in stdout.splitlines() if "-worker-" in line)

    exit_code, stdout, stderr = run_cli(tmp_path, "run", worker_id)
    worker_result = parse_json_output(exit_code, stdout, stderr)
    assert worker_result[0]["status"] == "review_pending"

    exit_code, stdout, stderr = run_cli(tmp_path, "review", "queue")
    queue = parse_json_output(exit_code, stdout, stderr)
    assert len(queue) == 1
    assert queue[0]["ticket_id"] == worker_id
    assert queue[0]["status"] == "review_pending"


def test_approve_rejects_blank_required_sections(tmp_path: Path) -> None:
    """承認時に必須 section が TODO のままなら失敗する。"""
    exit_code, stdout, stderr = run_cli(tmp_path, "plan", "未完成の plan を弾きたい")
    assert exit_code == 0, stderr
    plan_id = Path(stdout.strip()).stem

    exit_code, _, stderr = run_cli(tmp_path, "approve", plan_id, "in_review")
    assert exit_code == 1
    assert "section is empty: 未確定事項" in stderr


def test_artifacts_marks_missing_outputs_before_run(tmp_path: Path) -> None:
    """未実行チケットの成果物は exists=false と表示される。"""
    exit_code, stdout, stderr = run_cli(tmp_path, "plan", "成果物の存在確認をしたい")
    assert exit_code == 0, stderr
    plan_id = Path(stdout.strip()).stem
    plan_path = tmp_path / stdout.strip()
    prepare_approvable_plan(
        plan_path,
        {
            "TODO: 未確定事項 を具体化する": "未確定事項は無い",
            "TODO: 差し戻し条件 を具体化する": "失敗時は差し戻す",
            "TODO: 検証戦略 を具体化する": "dry run で確認する",
        },
    )

    assert run_cli(tmp_path, "approve", plan_id, "in_review")[0] == 0
    assert run_cli(tmp_path, "approve", plan_id, "approved")[0] == 0
    _, stdout, _ = run_cli(tmp_path, "ticket", plan_id)
    worker_id = next(Path(line).stem for line in stdout.splitlines() if "-worker-" in line)

    exit_code, stdout, stderr = run_cli(tmp_path, "artifacts", worker_id)
    artifacts = parse_json_output(exit_code, stdout, stderr)
    outputs = [item for item in artifacts["items"] if item["kind"] == "output"]
    assert outputs
    assert all(item["exists"] == "false" for item in outputs)


def test_internal_helpers_cover_error_paths(tmp_path: Path) -> None:
    """補助関数の分岐も直接確認する。"""
    assert main.normalize_plan_id("A b/c") == "a-b-c"
    assert main.slug_from_title("A B C D E") == "a-b-c-d"
    assert main.coerce_scalar("true") is True
    assert main.coerce_scalar("false") is False
    assert main.coerce_scalar("value") == "value"
    assert main.parse_yaml("name: value") == {"name": "value"}
    assert main.parse_yaml("list:\n  - one\n  - two") == {"list": ["one", "two"]}
    assert main.parse_yaml(
        "dependencies:\n  -\n    ticket_id: t1\n    required_state: done"
    ) == {"dependencies": [{"ticket_id": "t1", "required_state": "done"}]}
    assert main.parse_dependencies({"dependencies": [{"ticket_id": "t1", "required_state": "done"}]}) == [
        main.Dependency("t1", "done")
    ]
    assert main.parse_dependencies({"dependencies": "bad"}) == []
    assert main.section_is_blank("## 未確定事項\n- TODO: keep\n", "未確定事項") is True
    assert main.section_is_blank("## 未確定事項\n- fixed\n", "未確定事項") is False
    assert main.validate_ticket_document(main.Document({"status": "bad"}, "")) == [
        "ticket status is invalid",
        *[f"missing section: {section}" for section in main.TICKET_REQUIRED_SECTIONS],
    ]

    main.ensure_artifact_dirs(tmp_path)
    log_path = main.write_log("sample", "message", tmp_path)
    assert log_path.exists()
    review_path = main.write_review_result("review-1", "worker-1", "pass", False, tmp_path)
    assert review_path.exists()

    bad_plan_path = main.save_plan("bad plan", base_dir=tmp_path)
    with pytest.raises(main.typer.Exit):
        main.update_plan_status(bad_plan_path.stem, "approved", tmp_path)

    ready_plan_path = main.save_plan("ready plan", base_dir=tmp_path)
    prepare_approvable_plan(
        ready_plan_path,
        {
            "TODO: 未確定事項 を具体化する": "継続可能",
            "TODO: 差し戻し条件 を具体化する": "失敗時に差し戻す",
            "TODO: 検証戦略 を具体化する": "dry run で確認する",
        },
    )
    main.update_plan_status(ready_plan_path.stem, "in_review", tmp_path)
    main.update_plan_status(ready_plan_path.stem, "approved", tmp_path)
    ticket_paths = main.build_ticket_set(ready_plan_path.stem, tmp_path)
    assert len(ticket_paths) == 4

    worker_id = next(path.stem for path in ticket_paths if "-worker-" in path.stem)
    review_id = next(path.stem for path in ticket_paths if "-review-" in path.stem)
    integration_id = next(path.stem for path in ticket_paths if "-integration-" in path.stem)
    root_id = next(path.stem for path in ticket_paths if path.stem.endswith("-root"))

    blocked_review = main.run_ticket(review_id, tmp_path)
    assert blocked_review["status"] == "blocked"
    blocked_root = main.run_ticket(root_id, tmp_path)
    assert blocked_root["status"] == "blocked"
    worker_result = main.run_ticket(worker_id, tmp_path)
    assert worker_result["status"] == "review_pending"
    review_result = main.run_ticket(review_id, tmp_path)
    assert review_result["status"] == "done"
    integration_result = main.run_ticket(integration_id, tmp_path)
    assert integration_result["status"] == "done"
    root_result = main.run_ticket(root_id, tmp_path)
    assert root_result["status"] == "done"

    queue = main.collect_review_queue(tmp_path)
    assert queue == []
    plan_artifacts = main.collect_artifacts(ready_plan_path.stem, tmp_path)
    assert plan_artifacts["items"]
    ticket_artifacts = main.collect_artifacts(worker_id, tmp_path)
    assert ticket_artifacts["items"]
    assert main.dependency_satisfied(main.Dependency(integration_id, "done"), tmp_path) is True

    unknown_ticket_id = f"{ready_plan_path.stem}-unknown"
    body = main.build_ticket_body("Unknown", "bad type", ["artifacts/logs/x.log"], [])
    main.write_ticket(
        unknown_ticket_id,
        {
            "ticket_id": unknown_ticket_id,
            "ticket_type": "mystery",
            "status": "todo",
            "plan_id": ready_plan_path.stem,
            "owner_role": "implementation",
            "priority": "low",
            "dependencies": [],
            "outputs": ["artifacts/logs/x.log"],
        },
        body,
        tmp_path,
    )
    assert main.run_ticket(unknown_ticket_id, tmp_path)["status"] == "failed"

    with pytest.raises(main.typer.Exit):
        main.collect_artifacts("missing", tmp_path)
