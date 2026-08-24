"""数据库初始化脚本 —— 往 MySQL 灌入演示数据（种子数据）.

作用（相当于 Java 项目里的 data.sql / Flyway 初始化脚本）：
    1. 创建演示用账号（住户 / 物业 / 维修师傅）
    2. 把 houses.json 里的 3 套演示房屋导入 house 表
    3. 把房屋设备清单导入 house_device 表
    4. 把历史维修记录导入 repair_order 表（状态=已完成）
    5. 把户型、管线布局等静态档案信息提取到 house_profiles.json

特点：可重复执行（幂等）——
    已经存在的房屋/账号会自动跳过，不会重复插入或覆盖数据。

运行方式（在 backend 目录下）：
    venv\\Scripts\\python.exe init_database.py

注意：后端服务每次启动时也会自动检查，发现 house 表为空会
自动执行一次本脚本（见 app/main.py 的 startup 钩子）。
"""
import hashlib
import json
import sys
from datetime import datetime

from app.config import HOUSES_FILE, HOUSE_PROFILES_FILE
from app.database import query_one, query_all, execute, execute_return_id


def hash_password(plain: str) -> str:
    """把明文密码哈希后存储.

    【安全提示】演示项目用简单的 SHA256 即可；
    正式上线应换成加盐哈希（如 bcrypt / argon2），
    相当于 Java 里的 Spring Security PasswordEncoder。
    """
    return hashlib.sha256(plain.encode("utf-8")).hexdigest()


def seed_users():
    """创建演示账号（已存在则跳过）."""
    # (用户名, 姓名, 手机号, 角色)
    demo_users = [
        ("resident1", "张三", "13800000001", "RESIDENT"),   # 住户
        ("property1", "物业管理员", "13800000002", "PROPERTY"),  # 物业
        ("repairer1", "王工", "13800000003", "REPAIRER"),    # 维修师傅
        ("repairer2", "李工", "13800000004", "REPAIRER"),
        ("repairer3", "张工", "13800000005", "REPAIRER"),
        ("admin", "系统管理员", "13800000000", "ADMIN"),
    ]
    for username, real_name, phone, role in demo_users:
        exists = query_one("SELECT id FROM `user` WHERE username = %s", (username,))
        if exists:
            print(f"  账号已存在，跳过：{username}（{real_name}）")
            continue
        execute(
            "INSERT INTO `user` (username, password, real_name, phone, role, status)"
            " VALUES (%s, %s, %s, %s, %s, 1)",
            (username, hash_password("123456"), real_name, phone, role),
        )
        print(f"  创建账号：{username}（{real_name}，角色 {role}，初始密码 123456）")


def find_user_id(real_name: str) -> int | None:
    """按姓名查找用户 id（用于历史维修记录的维修师傅匹配）."""
    row = query_one(
        "SELECT id FROM `user` WHERE real_name = %s ORDER BY id LIMIT 1", (real_name,)
    )
    return row["id"] if row else None


def seed_houses() -> dict:
    """导入演示房屋和设备，返回 {房屋编号: house表id} 的映射."""
    with open(HOUSES_FILE, "r", encoding="utf-8") as f:
        houses = json.load(f)

    # house_code -> house 表自增 id 的映射，后续插设备/工单要用
    house_id_map = {}
    # 房屋静态档案补充信息（户型/管线布局等），单独存本地 JSON
    profiles = {}

    for h in houses:
        code = h["houseId"]
        exists = query_one("SELECT id FROM house WHERE house_code = %s", (code,))
        if exists:
            house_id_map[code] = exists["id"]
            print(f"  房屋已存在，跳过：{code}")
        else:
            house_id = execute_return_id(
                "INSERT INTO house (house_code, building_no, unit_no, room_no,"
                " qr_token, area, status)"
                " VALUES (%s, %s, %s, %s, %s, %s, 1)",
                (code, h["building"], h.get("unit"), h["room"],
                 h["qrCode"], h.get("area")),
            )
            house_id_map[code] = house_id
            print(f"  导入房屋：{code}（{h['building']}{h['room']}，house.id={house_id}）")

        # ---------- 导入设备清单到 house_device 表 ----------
        existing_devices = query_all(
            "SELECT device_code FROM house_device WHERE house_id = %s",
            (house_id_map[code],),
        )
        existing_codes = {d["device_code"] for d in existing_devices}

        for category, items in h.get("components", {}).items():
            for item in items:
                if item["id"] in existing_codes:
                    continue
                execute(
                    "INSERT INTO house_device (house_id, device_code, device_name,"
                    " device_type, location, brand, model, install_date, status, remark)"
                    " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        house_id_map[code],
                        item["id"],                       # 设备编号，如 PL-1302-K-01
                        item["name"],                     # 设备名称，如 冷水管
                        category,                         # 设备类型：plumbing/electrical...
                        item.get("location"),             # 所在区域
                        item.get("manufacturer"),         # 品牌 → 对应 JSON 里的 manufacturer
                        item.get("spec"),                 # 型号 → 对应 JSON 里的 spec
                        item.get("installDate"),          # 安装日期
                        "NORMAL",                         # 设备状态正常
                        f"保修期：{item.get('warrantyPeriod', '未知')}",  # 保修信息放备注
                    ),
                )
        device_count = query_one(
            "SELECT COUNT(*) AS c FROM house_device WHERE house_id = %s",
            (house_id_map[code],),
        )["c"]
        print(f"    设备清单：共 {device_count} 条")

        # ---------- 提取静态档案信息到 house_profiles.json ----------
        profiles[code] = {
            "floor": h.get("floor"),                     # 楼层
            "layout": h.get("layout"),                   # 户型
            "micModuleId": h.get("micModuleId"),         # MiC 模块编号
            "productionDate": h.get("productionDate"),   # 生产日期
            "deliveryDate": h.get("deliveryDate"),       # 交付日期
            "digitalId": h.get("digitalId"),             # 数字档案编号
            "warranty": h.get("warranty"),               # 整体质保说明
            "pipelineLayout": h.get("pipelineLayout", {}),  # 管线布局
        }

    # 把静态档案信息写入本地文件（运行时由 archive.py 读取）
    with open(HOUSE_PROFILES_FILE, "w", encoding="utf-8") as f:
        json.dump(profiles, f, ensure_ascii=False, indent=2)
    print(f"  静态档案信息已写入：{HOUSE_PROFILES_FILE}")

    return house_id_map


def seed_maintenance_history(house_id_map: dict):
    """把 houses.json 里的历史维修记录导入为已完成的工单.

    这样「维修历史查询」和「重复维修预警」功能就有真实数据可用。
    """
    with open(HOUSES_FILE, "r", encoding="utf-8") as f:
        houses = json.load(f)

    reporter_id = find_user_id("张三")  # 历史工单统一记到演示住户名下

    for h in houses:
        code = h["houseId"]
        for m in h.get("maintenanceRecords", []):
            # 用 order_no 判断是否已导入过
            exists = query_one(
                "SELECT id FROM repair_order WHERE order_no = %s", (m["orderId"],)
            )
            if exists:
                print(f"  历史工单已存在，跳过：{m['orderId']}")
                continue

            repairer_id = find_user_id(m.get("repairPerson"))
            order_id = execute_return_id(
                "INSERT INTO repair_order (order_no, reporter_id, house_id,"
                " original_description, ai_summary, repair_category, location,"
                " priority, info_status, status, assigned_to, completed_at)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    m["orderId"],          # 沿用原来的工单号，如 WO-503-001
                    reporter_id,
                    house_id_map[code],
                    m["fault"],            # 原始描述 → 故障现象
                    m["fault"],            # AI 摘要 → 历史数据直接用故障描述
                    None,                  # 故障类别（历史数据暂无分类）
                    m["location"],
                    "NORMAL",              # 优先级
                    "COMPLETE",
                    "COMPLETED",           # 历史记录都是已完成状态
                    repairer_id,
                    f"{m['date']} 00:00:00",
                ),
            )
            # 补一条「维修完成」操作流水，记录实际故障原因和处理措施
            execute(
                "INSERT INTO repair_record (repair_order_id, operator_id, operator_type,"
                " action_type, before_status, after_status, description)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (
                    order_id, repairer_id, "REPAIRER", "COMPLETE_REPAIR",
                    "PROCESSING", "COMPLETED",
                    json.dumps({
                        "实际故障": m["cause"],
                        "处理措施": m["action"],
                        "维修人": m["repairPerson"],
                        "结果": m["result"],
                    }, ensure_ascii=False),
                ),
            )
            print(f"  导入历史工单：{m['orderId']}（{m['location']} - {m['fault']}）")


def main():
    print("=" * 50)
    print("开始初始化数据库演示数据 ...")
    print("=" * 50)

    print("\n[1/3] 创建演示账号：")
    seed_users()

    print("\n[2/3] 导入房屋与设备档案：")
    house_id_map = seed_houses()

    print("\n[3/3] 导入历史维修记录：")
    seed_maintenance_history(house_id_map)

    print("\n" + "=" * 50)
    print("初始化完成！")
    print(f"完成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)


if __name__ == "__main__":
    main()
