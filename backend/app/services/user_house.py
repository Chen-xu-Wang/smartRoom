"""住户与房屋的绑定关系（user_house 表）.

一个住户可以绑定多套房（业主 / 租户），一套房也可以绑定多个住户。
绑定用 house_code（如 1302）而不是 house.id：主动感知事件、提醒和 3D 孪生都按房号定位，
而 1栋 108 户里只有少数进入了 house 表（一房一码正式档案），其余是模拟扩展档案。

可绑定的房号 = house 表里的房屋 ∪ 模拟楼栋 sim_building.json 里的住户。
"""
from __future__ import annotations

import json
from functools import lru_cache

from ..config import SIM_BUILDING_FILE
from ..database import execute, query_all, query_one

RELATIONS = {"OWNER": "业主", "TENANT": "租户"}


def ensure_user_house_schema() -> None:
    """幂等建表，可在每次启动时安全重复执行."""
    execute(
        "CREATE TABLE IF NOT EXISTS user_house ("
        " id INT AUTO_INCREMENT PRIMARY KEY,"
        " user_id INT NOT NULL,"
        " house_code VARCHAR(30) NOT NULL,"
        " relation VARCHAR(20) NOT NULL DEFAULT 'OWNER' COMMENT 'OWNER / TENANT',"
        " created_at DATETIME DEFAULT CURRENT_TIMESTAMP,"
        " UNIQUE KEY uk_user_house (user_id, house_code),"
        " INDEX idx_user_house_code (house_code)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )


# 演示账号的默认绑定：(用户名, 房号, 关系)
DEFAULT_BINDINGS = [("resident1", "1302", "OWNER")]


def seed_default_bindings() -> None:
    """给演示账号补齐默认绑定；该账号已有任何绑定时不动（尊重后台的修改）."""
    for username, house_code, relation in DEFAULT_BINDINGS:
        user = query_one("SELECT id FROM `user` WHERE username = %s AND role = 'RESIDENT'", (username,))
        if not user:
            continue
        has_any = query_one("SELECT COUNT(*) AS c FROM user_house WHERE user_id = %s", (user["id"],))
        if has_any and has_any["c"] > 0:
            continue
        execute(
            "INSERT INTO user_house (user_id, house_code, relation) VALUES (%s, %s, %s)",
            (user["id"], house_code, relation),
        )
        print(f"  绑定房屋：{username} → {house_code}（{RELATIONS[relation]}）")


@lru_cache(maxsize=1)
def _sim_house_codes() -> frozenset[str]:
    try:
        with open(SIM_BUILDING_FILE, "r", encoding="utf-8") as f:
            return frozenset(str(h["house_id"]) for h in json.load(f).get("houses", []))
    except (OSError, ValueError, KeyError):
        return frozenset()


def bindable_house_codes() -> list[dict]:
    """可绑定的房号清单，source 标明来自正式档案（ARCHIVE）还是模拟楼栋（SIM）."""
    archive = {r["house_code"] for r in query_all("SELECT house_code FROM house")}
    codes = archive | _sim_house_codes()
    return [
        {"house_code": c, "source": "ARCHIVE" if c in archive else "SIM"}
        for c in sorted(codes, key=lambda c: (len(c), c))
    ]


def is_bindable(house_code: str) -> bool:
    if house_code in _sim_house_codes():
        return True
    return query_one("SELECT id FROM house WHERE house_code = %s", (house_code,)) is not None


def list_bindings(user_id: int) -> list[dict]:
    rows = query_all(
        "SELECT house_code, relation FROM user_house WHERE user_id = %s ORDER BY id",
        (user_id,),
    )
    return [{"house_code": r["house_code"], "relation": r["relation"]} for r in rows]


def house_codes_of(user_id: int) -> list[str]:
    return [b["house_code"] for b in list_bindings(user_id)]


def bindings_by_user(user_ids: list[int]) -> dict[int, list[dict]]:
    """批量查询，避免用户列表逐个查库."""
    if not user_ids:
        return {}
    placeholders = ",".join(["%s"] * len(user_ids))
    rows = query_all(
        f"SELECT user_id, house_code, relation FROM user_house WHERE user_id IN ({placeholders}) ORDER BY id",
        tuple(user_ids),
    )
    out: dict[int, list[dict]] = {uid: [] for uid in user_ids}
    for r in rows:
        out.setdefault(r["user_id"], []).append({"house_code": r["house_code"], "relation": r["relation"]})
    return out


class BindingError(ValueError):
    """绑定参数不合法（由接口层转成 400）."""


def set_bindings(user_id: int, houses: list[dict]) -> list[dict]:
    """整体替换某住户的绑定（后台编辑时提交完整清单）；先全部校验，任何一项不合法都不改动."""
    user = query_one("SELECT role FROM `user` WHERE id = %s", (user_id,))
    if not user:
        raise LookupError("用户不存在")
    if user["role"] != "RESIDENT" and houses:
        raise BindingError("只有住户账号可以绑定房屋")
    cleaned: dict[str, str] = {}
    for h in houses:
        code = str(h.get("house_code") or "").strip()
        relation = str(h.get("relation") or "OWNER").upper()
        if not code:
            raise BindingError("房号不能为空")
        if relation not in RELATIONS:
            raise BindingError("关系只能是 OWNER（业主）或 TENANT（租户）")
        if not is_bindable(code):
            raise BindingError(f"房号 {code} 不存在")
        cleaned[code] = relation
    execute("DELETE FROM user_house WHERE user_id = %s", (user_id,))
    for code, relation in cleaned.items():
        execute("INSERT INTO user_house (user_id, house_code, relation) VALUES (%s, %s, %s)", (user_id, code, relation))
    return [{"house_code": c, "relation": r} for c, r in cleaned.items()]


def delete_user_bindings(user_id: int) -> None:
    execute("DELETE FROM user_house WHERE user_id = %s", (user_id,))


def delete_house_bindings_if_invalid(house_code: str) -> None:
    """正式档案删除后，若该房号也不在模拟楼栋中，清掉悬空的绑定."""
    if house_code not in _sim_house_codes():
        execute("DELETE FROM user_house WHERE house_code = %s", (house_code,))
