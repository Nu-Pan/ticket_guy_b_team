"""最小限の LangGraph 互換実装。"""

from dataclasses import dataclass, field
from typing import Callable


END = "__end__"


@dataclass
class StateGraph:
    """単純な状態遷移グラフ。"""

    _state_type: type
    _nodes: dict[str, Callable[[dict[str, object]], dict[str, object]]] = field(default_factory=dict)
    _edges: dict[str, str] = field(default_factory=dict)
    _conditional_edges: dict[str, tuple[Callable[[dict[str, object]], str], dict[str, str]]] = field(
        default_factory=dict
    )
    _entry_point: str | None = None

    def add_node(self, name: str, callback: Callable[[dict[str, object]], dict[str, object]]) -> None:
        """ノードを登録する。"""
        self._nodes[name] = callback

    def add_edge(self, source: str, target: str) -> None:
        """固定遷移を登録する。"""
        self._edges[source] = target

    def add_conditional_edges(
        self,
        source: str,
        condition: Callable[[dict[str, object]], str],
        mapping: dict[str, str],
    ) -> None:
        """条件分岐遷移を登録する。"""
        self._conditional_edges[source] = (condition, mapping)

    def set_entry_point(self, name: str) -> None:
        """開始ノードを登録する。"""
        self._entry_point = name

    def compile(self) -> "_CompiledGraph":
        """実行可能グラフへ変換する。"""
        if self._entry_point is None:
            raise ValueError("entry point is required")
        return _CompiledGraph(
            entry_point=self._entry_point,
            nodes=self._nodes,
            edges=self._edges,
            conditional_edges=self._conditional_edges,
        )


@dataclass
class _CompiledGraph:
    """実行可能なグラフ。"""

    entry_point: str
    nodes: dict[str, Callable[[dict[str, object]], dict[str, object]]]
    edges: dict[str, str]
    conditional_edges: dict[str, tuple[Callable[[dict[str, object]], str], dict[str, str]]]

    def invoke(self, state: dict[str, object]) -> dict[str, object]:
        """開始点から END まで状態を流す。"""
        current = self.entry_point
        current_state = dict(state)
        while current != END:
            current_state = self.nodes[current](current_state)
            if current in self.conditional_edges:
                condition, mapping = self.conditional_edges[current]
                current = mapping[condition(current_state)]
                continue
            current = self.edges[current]
        return current_state
