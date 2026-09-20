"""住户房屋绑定（services/user_house.py）的单元测试.

不连 MySQL：用内存 SQLite 顶替 app.database（见 tests/fake_db.py），
表结构与 local_schema.sql 中的 user / house / user_house 对应。
"""
import unittest

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fake_db  # noqa: E402

CONN = fake_db.install()

from app.services import user_house as uh  # noqa: E402  必须在替换 app.database 之后导入


class UserHouseTest(unittest.TestCase):
    def setUp(self):
        CONN.executescript(
            """
            DROP TABLE IF EXISTS user; DROP TABLE IF EXISTS house; DROP TABLE IF EXISTS user_house;
            CREATE TABLE user (id INTEGER PRIMARY KEY, username TEXT UNIQUE, role TEXT);
            CREATE TABLE house (id INTEGER PRIMARY KEY, house_code TEXT UNIQUE);
            CREATE TABLE user_house (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, house_code TEXT,
                                     relation TEXT DEFAULT 'OWNER', UNIQUE (user_id, house_code));
            INSERT INTO user VALUES (1, 'resident1', 'RESIDENT'), (2, 'repairer1', 'REPAIRER'), (3, 'resident2', 'RESIDENT');
            INSERT INTO house (house_code) VALUES ('1302'), ('805'), ('503'), ('A-01');
            """
        )

    def test_seed_binds_resident1_once_and_respects_existing(self):
        uh.seed_default_bindings()
        uh.seed_default_bindings()
        self.assertEqual(uh.list_bindings(1), [{"house_code": "1302", "relation": "OWNER"}])
        # 后台改绑后再次启动，不应被默认绑定覆盖
        uh.set_bindings(1, [{"house_code": "805", "relation": "TENANT"}])
        uh.seed_default_bindings()
        self.assertEqual(uh.house_codes_of(1), ["805"])

    def test_set_bindings_replaces_and_dedupes(self):
        uh.set_bindings(3, [{"house_code": "1302"}, {"house_code": "705", "relation": "tenant"}, {"house_code": "1302"}])
        self.assertEqual(uh.list_bindings(3), [
            {"house_code": "1302", "relation": "OWNER"},
            {"house_code": "705", "relation": "TENANT"},  # 705 只在模拟楼栋里，也可绑定
        ])
        uh.set_bindings(3, [])
        self.assertEqual(uh.list_bindings(3), [])

    def test_invalid_input_changes_nothing(self):
        uh.set_bindings(3, [{"house_code": "1302"}])
        for bad in ([{"house_code": "9999"}], [{"house_code": "805", "relation": "FRIEND"}], [{"house_code": " "}]):
            with self.assertRaises(uh.BindingError):
                uh.set_bindings(3, [{"house_code": "503"}, *bad])
        self.assertEqual(uh.house_codes_of(3), ["1302"])

    def test_only_residents_can_bind(self):
        with self.assertRaises(uh.BindingError):
            uh.set_bindings(2, [{"house_code": "1302"}])
        uh.set_bindings(2, [])  # 非住户提交空列表（清空）是允许的
        with self.assertRaises(LookupError):
            uh.set_bindings(404, [])

    def test_bindable_codes_merge_archive_and_sim(self):
        codes = {h["house_code"]: h["source"] for h in uh.bindable_house_codes()}
        self.assertEqual(codes["1302"], "ARCHIVE")
        self.assertEqual(codes["A-01"], "ARCHIVE")  # 只在 house 表
        self.assertEqual(codes["705"], "SIM")
        self.assertEqual(len([c for c, s in codes.items() if s == "SIM"]), 108 - 3)

    def test_bindings_cleanup(self):
        uh.set_bindings(1, [{"house_code": "A-01"}, {"house_code": "805"}])
        uh.set_bindings(3, [{"house_code": "805"}])
        self.assertEqual(uh.bindings_by_user([1, 3, 2]), {
            1: [{"house_code": "A-01", "relation": "OWNER"}, {"house_code": "805", "relation": "OWNER"}],
            3: [{"house_code": "805", "relation": "OWNER"}],
            2: [],
        })
        # 删除正式档案：805 仍在模拟楼栋中保留绑定，A-01 不在则清掉
        uh.delete_house_bindings_if_invalid("805")
        uh.delete_house_bindings_if_invalid("A-01")
        self.assertEqual(uh.house_codes_of(1), ["805"])
        uh.delete_user_bindings(1)
        self.assertEqual(uh.house_codes_of(1), [])


if __name__ == "__main__":
    unittest.main()
