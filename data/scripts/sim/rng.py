"""可复现的随机数流。

每个随机数流由 (数据集种子, 户号, 用途) 唯一确定，与遍历顺序无关：
只重算某一户、或者新增一种用途，都不会改变其它户、其它用途已经生成的结果。
"""
from __future__ import annotations

import zlib

import numpy as np


def _stream_key(name: str) -> int:
    return zlib.crc32(name.encode("utf-8"))


def stream(seed: int, *keys: str | int) -> np.random.Generator:
    """``stream(1001, "1302", "habits")`` → 独立的 numpy Generator。"""
    entropy = [int(seed)] + [k if isinstance(k, int) else _stream_key(str(k)) for k in keys]
    return np.random.default_rng(np.random.SeedSequence(entropy))
