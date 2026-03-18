"""最小限の Typer 互換実装。"""

import inspect
import sys
from dataclasses import dataclass, field
from typing import Callable


class Exit(Exception):
    """CLI 中断用の例外。"""

    def __init__(self, exit_code: int = 0, message: str | None = None) -> None:
        """終了コードと表示メッセージを保持する。"""
        super().__init__(message or "")
        self.exit_code = exit_code
        self.message = message or ""


def echo(message: str) -> None:
    """標準出力へ出力する。"""
    print(message)


@dataclass
class _Command:
    """登録済みコマンド定義。"""

    name: str
    callback: Callable[..., None]


@dataclass
class Typer:
    """サブコマンドを解釈する最小限の CLI アプリ。"""

    commands: dict[str, _Command] = field(default_factory=dict)
    sub_apps: dict[str, "Typer"] = field(default_factory=dict)

    def command(self, name: str | None = None) -> Callable[[Callable[..., None]], Callable[..., None]]:
        """コマンドを登録する。"""

        def decorator(func: Callable[..., None]) -> Callable[..., None]:
            command_name = name or func.__name__.replace("_", "-")
            self.commands[command_name] = _Command(name=command_name, callback=func)
            return func

        return decorator

    def add_typer(self, app: "Typer", name: str) -> None:
        """サブアプリを登録する。"""
        self.sub_apps[name] = app

    def __call__(self, argv: list[str] | None = None) -> None:
        """コマンドラインを実行する。"""
        args = list(sys.argv[1:] if argv is None else argv)
        try:
            self._dispatch(args)
        except Exit as exc:
            if exc.message:
                print(exc.message, file=sys.stderr)
            raise SystemExit(exc.exit_code) from exc

    def _dispatch(self, args: list[str]) -> None:
        """再帰的にコマンドを解釈する。"""
        if not args:
            raise Exit(1, "command is required")
        head = args.pop(0)
        if head in self.sub_apps:
            self.sub_apps[head]._dispatch(args)
            return
        if head not in self.commands:
            raise Exit(1, f"unknown command: {head}")
        command = self.commands[head]
        parsed_args = self._parse_arguments(command.callback, args)
        command.callback(**parsed_args)

    def _parse_arguments(self, func: Callable[..., None], args: list[str]) -> dict[str, object]:
        """関数シグネチャに従って引数を割り当てる。"""
        signature = inspect.signature(func)
        parsed: dict[str, object] = {}
        position = 0
        for parameter in signature.parameters.values():
            if position >= len(args):
                if parameter.default is inspect._empty:
                    raise Exit(1, f"missing argument: {parameter.name}")
                parsed[parameter.name] = parameter.default
                continue
            parsed[parameter.name] = args[position]
            position += 1
        if position != len(args):
            raise Exit(1, "too many arguments")
        return parsed
