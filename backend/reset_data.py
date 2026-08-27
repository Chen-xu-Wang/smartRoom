"""重置数据库中的演示数据（危险操作，会清空业务表！）.

作用：把工单、对话、流水等业务数据清空，房屋/设备/账号保留，
然后重新导入 houses.json 里的历史维修记录，恢复到初始演示状态。

【警告】这个脚本会 DELETE 数据库里的数据，且不可恢复！
        仅在自己的开发/演示环境中使用。

运行方式（在 backend 目录下）：
    venv\\Scripts\\python.exe reset_data.py
"""
import sys
from pathlib import Path

# 把 backend 目录加入模块搜索路径（因为本脚本在 backend 根目录）
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.database import execute, query_one  # noqa: E402
from init_database import main as seed_main  # noqa: E402


def reset():
    print("=" * 50)
    print("⚠️  即将清空工单相关业务表（repair_order 等）！")
    print("=" * 50)

    # 先删子表（有外键约束的），再删主表，否则外键约束会报错
    # —— 这一点和 Java/JPA 里处理关联表删除的顺序问题一样
    for table in ["repair_record", "repair_attachment",
                  "repair_message", "repair_order"]:
        execute(f"DELETE FROM {table}")
        print(f"  已清空：{table}")

    # 重新导入种子数据（账号/房屋已存在会自动跳过，只补历史工单）
    seed_main()
    print("\n重置完成！")


if __name__ == "__main__":
    confirm = input("确认要清空所有工单数据吗？输入 yes 继续：")
    if confirm.strip().lower() == "yes":
        reset()
    else:
        print("已取消")
