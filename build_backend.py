"""外部依存なしで editable install を提供する最小 build backend。"""

import base64
import csv
import hashlib
import os
from pathlib import Path
import tempfile
import tomllib
from typing import Any
import zipfile


ROOT = Path(__file__).resolve().parent


def _project_metadata() -> dict[str, Any]:
    """`pyproject.toml` から必要最小限の project metadata を読む。"""
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return data["project"]


def _dist_info_dir() -> str:
    """dist-info ディレクトリ名を返す。"""
    metadata = _project_metadata()
    name = str(metadata["name"]).replace("-", "_")
    version = str(metadata["version"])
    return f"{name}-{version}.dist-info"


def _wheel_filename() -> str:
    """wheel ファイル名を返す。"""
    metadata = _project_metadata()
    name = str(metadata["name"]).replace("-", "_")
    version = str(metadata["version"])
    return f"{name}-{version}-py3-none-any.whl"


def _metadata_text() -> str:
    """METADATA 内容を返す。"""
    metadata = _project_metadata()
    lines = [
        "Metadata-Version: 2.1",
        f"Name: {metadata['name']}",
        f"Version: {metadata['version']}",
        f"Summary: {metadata.get('description', '')}",
        "",
    ]
    return "\n".join(lines)


def _wheel_text() -> str:
    """WHEEL 内容を返す。"""
    return "\n".join(
        [
            "Wheel-Version: 1.0",
            "Generator: ticket_guy_b_team.build_backend",
            "Root-Is-Purelib: true",
            "Tag: py3-none-any",
            "",
        ]
    )


def _entry_points_text() -> str:
    """entry_points.txt 内容を返す。"""
    scripts = _project_metadata().get("scripts", {})
    lines = ["[console_scripts]"]
    for name, target in scripts.items():
        lines.append(f"{name} = {target}")
    lines.append("")
    return "\n".join(lines)


def _editable_pth_text() -> str:
    """editable install 用 `.pth` 内容を返す。"""
    src_path = ROOT / "src"
    return f"{src_path}\n"


def _hash_bytes(content: bytes) -> str:
    """RECORD 用の sha256 ハッシュを返す。"""
    digest = hashlib.sha256(content).digest()
    encoded = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return f"sha256={encoded}"


def _build_wheel_impl(wheel_directory: str) -> str:
    """editable / normal 共通の purelib wheel を作る。"""
    dist_info = _dist_info_dir()
    wheel_name = _wheel_filename()
    wheel_path = Path(wheel_directory) / wheel_name

    files: dict[str, bytes] = {
        f"{dist_info}/METADATA": _metadata_text().encode("utf-8"),
        f"{dist_info}/WHEEL": _wheel_text().encode("utf-8"),
        f"{dist_info}/entry_points.txt": _entry_points_text().encode("utf-8"),
        "ticket_guy_b_team_editable.pth": _editable_pth_text().encode("utf-8"),
    }

    record_rows: list[list[str]] = []
    for path, content in files.items():
        record_rows.append([path, _hash_bytes(content), str(len(content))])
    record_rows.append([f"{dist_info}/RECORD", "", ""])

    with tempfile.TemporaryDirectory() as temp_dir:
        record_path = Path(temp_dir) / "RECORD"
        with record_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerows(record_rows)
        files[f"{dist_info}/RECORD"] = record_path.read_bytes()

        with zipfile.ZipFile(wheel_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for path, content in files.items():
                zf.writestr(path, content)

    return wheel_name


def build_wheel(
    wheel_directory: str,
    config_settings: dict[str, Any] | None = None,
    metadata_directory: str | None = None,
) -> str:
    """通常 wheel を作る。"""
    del config_settings, metadata_directory
    os.makedirs(wheel_directory, exist_ok=True)
    return _build_wheel_impl(wheel_directory)


def build_editable(
    wheel_directory: str,
    config_settings: dict[str, Any] | None = None,
    metadata_directory: str | None = None,
) -> str:
    """editable wheel を作る。"""
    del config_settings, metadata_directory
    os.makedirs(wheel_directory, exist_ok=True)
    return _build_wheel_impl(wheel_directory)


def get_requires_for_build_wheel(config_settings: dict[str, Any] | None = None) -> list[str]:
    """wheel build に追加依存は無い。"""
    del config_settings
    return []


def get_requires_for_build_editable(config_settings: dict[str, Any] | None = None) -> list[str]:
    """editable build に追加依存は無い。"""
    del config_settings
    return []


def prepare_metadata_for_build_wheel(
    metadata_directory: str,
    config_settings: dict[str, Any] | None = None,
) -> str:
    """通常 build 用の metadata を出力する。"""
    del config_settings
    return _write_metadata_directory(metadata_directory)


def prepare_metadata_for_build_editable(
    metadata_directory: str,
    config_settings: dict[str, Any] | None = None,
) -> str:
    """editable build 用の metadata を出力する。"""
    del config_settings
    return _write_metadata_directory(metadata_directory)


def _write_metadata_directory(metadata_directory: str) -> str:
    """dist-info ディレクトリを作る。"""
    dist_info = Path(metadata_directory) / _dist_info_dir()
    dist_info.mkdir(parents=True, exist_ok=True)
    (dist_info / "METADATA").write_text(_metadata_text(), encoding="utf-8")
    (dist_info / "WHEEL").write_text(_wheel_text(), encoding="utf-8")
    (dist_info / "entry_points.txt").write_text(_entry_points_text(), encoding="utf-8")
    return dist_info.name
