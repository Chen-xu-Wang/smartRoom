"""参数库读取与出处校验。

``sim_params.yaml`` 中每个参数叶子都是 ``{value, unit, source[, note, verify]}``。
读取时强制校验：没有 source、source 未在 ``sources`` 中登记、或者出现裸值，都直接报错，
保证"每个参数都有出处"这条可信度底线不会在后续修改中被悄悄破坏。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .paths import PARAMS_FILE, PRICE_FILE

LEAF_KEYS = {"value", "unit", "source", "note", "verify"}
RESERVED_TOP_LEVEL = {"meta", "sources"}


class ParamsError(ValueError):
    """参数库结构或出处不合规。"""


@dataclass(frozen=True)
class Leaf:
    path: str
    value: Any
    unit: str
    source: str
    note: str
    verify: bool


class Params:
    """只读参数访问：``params["water.supply.prv_setpoint_mpa"]`` 返回 value。"""

    def __init__(self, raw: dict, leaves: dict[str, Leaf]):
        self.raw = raw
        self.leaves = leaves
        self.sources: dict[str, str] = raw["sources"]

    def __getitem__(self, path: str) -> Any:
        try:
            return self.leaves[path].value
        except KeyError:
            raise KeyError(f"参数不存在：{path}") from None

    def leaf(self, path: str) -> Leaf:
        return self.leaves[path]

    def unverified(self) -> list[Leaf]:
        """引自标准、但尚未与原文逐条核对的参数。"""
        return [leaf for leaf in self.leaves.values() if leaf.verify]


def _is_leaf(node: Any) -> bool:
    return isinstance(node, dict) and "value" in node and "source" in node


def _collect(node: Any, path: str, sources: dict, leaves: dict[str, Leaf]) -> None:
    if _is_leaf(node):
        extra = set(node) - LEAF_KEYS
        if extra:
            raise ParamsError(f"{path}: 叶子节点含未知键 {sorted(extra)}")
        if node["source"] not in sources:
            raise ParamsError(f"{path}: source {node['source']!r} 未在 sources 中登记")
        if "unit" not in node:
            raise ParamsError(f"{path}: 缺少 unit（无量纲请写空字符串）")
        leaves[path] = Leaf(
            path=path,
            value=node["value"],
            unit=node["unit"],
            source=node["source"],
            note=node.get("note", ""),
            verify=bool(node.get("verify", False)),
        )
        return
    if isinstance(node, dict):
        if "value" in node or "source" in node:
            raise ParamsError(f"{path}: 叶子节点须同时包含 value 与 source")
        for key, child in node.items():
            _collect(child, f"{path}.{key}" if path else str(key), sources, leaves)
        return
    raise ParamsError(f"{path}: 出现裸值 {node!r}，须写成 {{value, unit, source}}")


def load_params(path: Path = PARAMS_FILE) -> Params:
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    if not isinstance(raw, dict) or "sources" not in raw:
        raise ParamsError("参数库缺少 sources 段")
    leaves: dict[str, Leaf] = {}
    for key, node in raw.items():
        if key in RESERVED_TOP_LEVEL:
            continue
        _collect(node, key, raw["sources"], leaves)
    return Params(raw, leaves)


def load_prices(path: Path = PRICE_FILE) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)
