"""主动感知所需的幂等数据库迁移：感知事件表、住户提醒表，工单来源字段。"""
from __future__ import annotations

from ..database import execute, query_one


def ensure_sensing_schema() -> None:
    """可在每次启动时安全重复执行。"""
    execute(
        "CREATE TABLE IF NOT EXISTS device_event ("
        " id INT AUTO_INCREMENT PRIMARY KEY,"
        " event_id VARCHAR(40) NOT NULL UNIQUE,"
        " house_id INT DEFAULT NULL,"
        " house_code VARCHAR(30) DEFAULT NULL,"
        " scope VARCHAR(20) NOT NULL,"
        " domain VARCHAR(20) NOT NULL,"
        " event_type VARCHAR(40) NOT NULL,"
        " severity VARCHAR(20) NOT NULL,"
        " priority VARCHAR(20) DEFAULT NULL,"
        " detected_at DATETIME NOT NULL,"
        " fault_summary VARCHAR(120) DEFAULT '',"
        " payload MEDIUMTEXT NOT NULL,"
        " decision MEDIUMTEXT DEFAULT NULL,"
        " diagnostics MEDIUMTEXT DEFAULT NULL,"
        " generated_by VARCHAR(20) DEFAULT 'RULE_ENGINE',"
        " source_ref VARCHAR(160) DEFAULT NULL,"
        " status VARCHAR(20) NOT NULL DEFAULT 'NOTIFIED',"
        " repair_order_id INT DEFAULT NULL,"
        " recheck_due DATE DEFAULT NULL,"
        " created_at DATETIME DEFAULT CURRENT_TIMESTAMP,"
        " updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,"
        " INDEX idx_event_house (house_code),"
        " INDEX idx_event_status (status)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )
    execute(
        "CREATE TABLE IF NOT EXISTS resident_notice ("
        " id INT AUTO_INCREMENT PRIMARY KEY,"
        " event_id VARCHAR(40) NOT NULL,"
        " house_code VARCHAR(30) NOT NULL,"
        " audience VARCHAR(20) NOT NULL,"
        " title VARCHAR(60) NOT NULL,"
        " content VARCHAR(400) NOT NULL,"
        " self_check_steps TEXT,"
        " show_repair_button TINYINT NOT NULL DEFAULT 1,"
        " status VARCHAR(20) NOT NULL DEFAULT 'UNREAD',"
        " repair_order_id INT DEFAULT NULL,"
        " created_at DATETIME DEFAULT CURRENT_TIMESTAMP,"
        " updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,"
        " UNIQUE KEY uk_notice (event_id, audience, house_code),"
        " INDEX idx_notice_house (house_code, status)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )
    _add_column_if_missing(
        "repair_order", "source",
        "VARCHAR(20) NOT NULL DEFAULT 'RESIDENT_CHAT' COMMENT 'RESIDENT_CHAT / AUTO_SENSOR'",
    )
    _add_column_if_missing("repair_order", "trigger_event_id", "VARCHAR(40) DEFAULT NULL")


def _add_column_if_missing(table: str, column: str, ddl: str) -> None:
    row = query_one(
        "SELECT COUNT(*) AS c FROM information_schema.COLUMNS"
        " WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = %s",
        (table, column),
    )
    if row and row["c"] == 0:
        execute(f"ALTER TABLE `{table}` ADD COLUMN `{column}` {ddl}")
