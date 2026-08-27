"""MySQL 数据库访问层 —— 所有数据库操作的统一入口.

设计思路（Java 对照）：
    - PyMySQL          ≈ mysql-connector-j（JDBC 驱动）
    - DBUtils 连接池   ≈ HikariCP（连接复用，避免每次请求都握手建连）
    - 本文件的查询助手 ≈ MyBatis 的 SqlSession / JdbcTemplate

背景知识（从 Java 转过来需要知道的差异）：
    1. 占位符：SQLite 用 ?，MySQL 驱动统一用 %s（注意：不是 Python 字符串
       格式化的 %s 拼接，参数是单独传给驱动的，天然防 SQL 注入）
    2. 事务：PyMySQL 默认不自动提交（autocommit=False），写操作后必须
       手动 conn.commit()，这一点和 JDBC 默认行为一致
    3. 连接用完必须归还连接池（本文件用「上下文管理器 with」自动处理，
       相当于 Java 的 try-with-resources）
"""
import json
from contextlib import contextmanager

import pymysql
from dbutils.pooled_db import PooledDB

from .config import (
    DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME, DB_POOL_SIZE,
)

# ------------------------------------------------------------------
# 创建全局连接池
# ------------------------------------------------------------------
# 整个后端进程只创建一次，所有请求共用（模块级变量，Python 进程启动时执行）
#
# 参数说明：
#   creator      底层驱动，用 PyMySQL
#   maxconnections 连接池最大连接数（相当于 HikariCP 的 maximumPoolSize）
#   mincached   启动时预热建立的空闲连接数
#   maxcached   池中最多保持的空闲连接数
#   blocking    连接耗尽时是否阻塞等待（True=等待，False=直接报错）
#   ping        取连接时探活（1=每次取都用 ping 检查连接是否存活，
#               防止远程 MySQL 因超时断开后拿到死连接）
#   charset     utf8mb4 支持完整的中文和 emoji
POOL = PooledDB(
    creator=pymysql,
    maxconnections=DB_POOL_SIZE,
    mincached=1,
    maxcached=DB_POOL_SIZE,
    blocking=True,
    ping=1,
    host=DB_HOST,
    port=DB_PORT,
    user=DB_USER,
    password=DB_PASSWORD,
    database=DB_NAME,
    charset="utf8mb4",
    # 返回字典形式的结果：{"id": 1, "name": "xx"}
    # （不设置的话返回元组 (1, "xx")，用下标取值容易出错）
    cursorclass=pymysql.cursors.DictCursor,
)


# ------------------------------------------------------------------
# 连接管理：上下文管理器（相当于 Java 的 try-with-resources）
# ------------------------------------------------------------------
@contextmanager
def get_conn():
    """从连接池借出一个数据库连接，用完自动归还.

    用法：
        with get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT ...", (参数,))
                rows = cursor.fetchall()
            conn.commit()   # 有写操作时需要提交事务
    """
    conn = POOL.connection()
    try:
        # yield 之前相当于 try 块开头，之后相当于 finally 块
        yield conn
    finally:
        # 无论中间是否抛异常，连接都会归还给连接池
        conn.close()


# ------------------------------------------------------------------
# 常用查询助手（推荐业务代码直接用这三个函数）
# ------------------------------------------------------------------
def query_all(sql: str, params: tuple = ()) -> list:
    """执行 SELECT，返回所有行（每行是一个字典组成的列表）."""
    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchall()


def query_one(sql: str, params: tuple = ()) -> dict | None:
    """执行 SELECT，返回第一行（字典）；没有结果时返回 None."""
    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchone()


def execute(sql: str, params: tuple = ()) -> int:
    """执行 INSERT / UPDATE / DELETE，自动提交事务.

    返回值：受影响的行数（比如插入了 1 条就返回 1）.
    需要拿到自增主键 id 时，改用 execute_return_id().
    """
    with get_conn() as conn:
        with conn.cursor() as cursor:
            affected = cursor.execute(sql, params)
            conn.commit()  # 写操作必须提交，否则数据不会真正落库
            return affected


def execute_return_id(sql: str, params: tuple = ()) -> int:
    """执行 INSERT 并返回这条记录的自增主键 id.

    用法：new_id = execute_return_id("INSERT INTO house(...) VALUES(...)", (...))
    """
    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
            conn.commit()
            # LAST_INSERT_ID() 是 MySQL 函数，返回本次连接最后插入的自增 id
            cursor.execute("SELECT LAST_INSERT_ID() AS id")
            return cursor.fetchone()["id"]


def execute_many(sql: str, params_list: list) -> int:
    """批量执行同一条 SQL（常用于批量插入种子数据）."""
    with get_conn() as conn:
        with conn.cursor() as cursor:
            affected = cursor.executemany(sql, params_list)
            conn.commit()
            return affected


# ------------------------------------------------------------------
# 兼容层：旧代码使用的辅助函数（保留同名，减少改动面）
# ------------------------------------------------------------------
def parse_json_field(text, default=None):
    """把数据库 TEXT 字段里存的 JSON 字符串解析回 Python 对象.

    存 JSON 到 TEXT 列是常见做法（相当于把对象序列化成 JSON 字符串存库）.
    解析失败时返回 default，避免一条脏数据搞崩整个接口。
    """
    if not text:
        return default
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return default
