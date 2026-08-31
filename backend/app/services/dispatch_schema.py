"""智能调度所需的幂等数据库迁移与维修人员画像。"""
from __future__ import annotations

import json

from ..database import execute


DEFAULT_PROFILES = [
    {
        "username": "repairer1",
        "skills": ["水电维修", "电工维修", "综合维修"],
        "max_active_orders": 3,
        "daily_capacity": 5,
    },
    {
        "username": "repairer2",
        "skills": ["空调维修", "电工维修", "综合维修"],
        "max_active_orders": 2,
        "daily_capacity": 4,
    },
    {
        "username": "repairer3",
        "skills": ["门窗维修", "油漆维修", "综合维修"],
        "max_active_orders": 3,
        "daily_capacity": 5,
    },
]


def ensure_dispatch_schema() -> None:
    """创建智能派单画像表；可在每次启动时安全重复执行。"""
    execute(
        "CREATE TABLE IF NOT EXISTS repairer_profile ("
        " user_id INT NOT NULL PRIMARY KEY,"
        " skills TEXT NOT NULL,"
        " max_active_orders INT NOT NULL DEFAULT 3,"
        " daily_capacity INT NOT NULL DEFAULT 5,"
        " on_duty TINYINT NOT NULL DEFAULT 1,"
        " preferred_buildings VARCHAR(255) DEFAULT '',"
        " last_assigned_at DATETIME DEFAULT NULL,"
        " created_at DATETIME DEFAULT CURRENT_TIMESTAMP,"
        " updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,"
        " INDEX idx_profile_duty (on_duty)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )


def seed_default_profiles() -> None:
    """按稳定 username 给维修工补画像，不覆盖物业已调整的配置。"""
    for profile in DEFAULT_PROFILES:
        execute(
            "INSERT INTO repairer_profile"
            " (user_id, skills, max_active_orders, daily_capacity, on_duty)"
            " SELECT id, %s, %s, %s, 1 FROM `user` WHERE username = %s"
            " ON DUPLICATE KEY UPDATE user_id = VALUES(user_id)",
            (
                json.dumps(profile["skills"], ensure_ascii=False),
                profile["max_active_orders"],
                profile["daily_capacity"],
                profile["username"],
            ),
        )
