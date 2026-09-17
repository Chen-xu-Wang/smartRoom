"""测试用：内存 SQLite 顶替 app.database（%s 占位符转成 ?），不连 MySQL.

多个测试文件共用同一个替身，必须在导入任何 app.services / app.security 之前调用 install()。
"""
import sqlite3
import sys
import types


def install() -> sqlite3.Connection:
    existing = sys.modules.get("app.database")
    if existing is not None and hasattr(existing, "SQLITE"):
        return existing.SQLITE

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row

    def _run(sql, params=()):
        return conn.execute(sql.replace("%s", "?"), params)

    def query_one(sql, params=()):
        row = _run(sql, params).fetchone()
        return dict(row) if row else None

    def query_all(sql, params=()):
        return [dict(r) for r in _run(sql, params).fetchall()]

    def execute(sql, params=()):
        cur = _run(sql, params)
        conn.commit()
        return cur.rowcount

    def execute_return_id(sql, params=()):
        cur = _run(sql, params)
        conn.commit()
        return cur.lastrowid

    fake = types.ModuleType("app.database")
    fake.SQLITE = conn
    fake.query_one, fake.query_all, fake.execute, fake.execute_return_id = query_one, query_all, execute, execute_return_id
    sys.modules["app.database"] = fake
    return conn
