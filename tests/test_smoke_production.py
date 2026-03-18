"""本番モードの smoke test。"""

# pyright: reportMissingImports=false

import os
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
TICKETGUY_BIN = REPO_ROOT / ".venv" / "bin" / "ticketguy"
SMOKE_ENV = "TICKETGUY_RUN_PRODUCTION_SMOKE"
SMOKE_MODEL_ENV = "TICKETGUY_PRODUCTION_SMOKE_MODEL"


def run_ticketguy(workdir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """インストール済み console script から ticketguy を呼び出す。"""
    return subprocess.run(
        [str(TICKETGUY_BIN), *args],
        check=False,
        capture_output=True,
        text=True,
        cwd=workdir,
    )


@pytest.mark.skipif(os.environ.get(SMOKE_ENV) != "1", reason="production smoke is opt-in")
def test_production_smoke_minimal_project(tmp_path: Path) -> None:
    """最小プロジェクトに対して production mode を走らせる。"""
    subprocess.run(["git", "init", "-q"], check=True, cwd=tmp_path)
    (tmp_path / "app.py").write_text(
        'def hello() -> str:\n    """挨拶を返す。"""\n    return "bad"\n',
        encoding="utf-8",
    )
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_app.py").write_text(
        'from app import hello\n\n\ndef test_hello() -> None:\n    assert hello() == "hello"\n',
        encoding="utf-8",
    )

    plan_completed = run_ticketguy(tmp_path, "plan", "app.py の hello を hello に修正して tests を通す")
    assert plan_completed.returncode == 0, plan_completed.stderr
    plan_path = tmp_path / plan_completed.stdout.strip()
    text = plan_path.read_text(encoding="utf-8")
    text = text.replace("TODO: 未確定事項 を具体化する", "未確定事項なし")
    text = text.replace("TODO: 差し戻し条件 を具体化する", "pytest 失敗時は差し戻す")
    text = text.replace("TODO: 検証戦略 を具体化する", "pytest -q を実行する")
    plan_path.write_text(text, encoding="utf-8")
    plan_id = plan_path.stem

    assert run_ticketguy(tmp_path, "approve", plan_id, "in_review").returncode == 0
    assert run_ticketguy(tmp_path, "approve", plan_id, "approved").returncode == 0
    ticket_completed = run_ticketguy(tmp_path, "ticket", plan_id)
    assert ticket_completed.returncode == 0, ticket_completed.stderr
    root_id = next(Path(line).stem for line in ticket_completed.stdout.splitlines() if line.strip().endswith("-root.md"))

    model = os.environ.get(SMOKE_MODEL_ENV, "gpt-5.1-codex-mini")
    run_completed = run_ticketguy(tmp_path, "run", root_id, "production", model, "low")
    assert run_completed.returncode == 0, run_completed.stderr

    verification = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        check=False,
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert verification.returncode == 0, verification.stdout + verification.stderr
    assert 'return "hello"' in (tmp_path / "app.py").read_text(encoding="utf-8")
