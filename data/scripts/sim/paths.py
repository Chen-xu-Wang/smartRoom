"""模拟器目录约定。所有路径都基于本文件位置推导，不依赖当前工作目录。"""
from __future__ import annotations

from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = SCRIPTS_DIR.parent
PROJECT_DIR = DATA_DIR.parent

PROCESSED_DIR = DATA_DIR / "processed"
SIM_CONFIG_DIR = PROCESSED_DIR / "sim_config"
SIM_CONFIG_TRUTH_DIR = SIM_CONFIG_DIR / "_truth"
EVALUATION_DIR = PROCESSED_DIR / "evaluation"
CONTRACTS_DIR = PROCESSED_DIR / "contracts"

PARAMS_FILE = SIM_CONFIG_DIR / "sim_params.yaml"
PRICE_FILE = SIM_CONFIG_DIR / "price_tables.yaml"
BUILDING_FILE = SIM_CONFIG_DIR / "sim_building.json"
PERSONA_TRUTH_FILE = SIM_CONFIG_TRUTH_DIR / "household_personas.json"

ARCHIVE_HOUSES_FILE = PROJECT_DIR / "backend" / "app" / "data" / "houses.json"
ARCHIVE_PROFILES_FILE = PROJECT_DIR / "backend" / "app" / "data" / "house_profiles.json"


def dataset_dir(dataset: str) -> Path:
    """sim_dev / sim_test 数据集目录。"""
    if dataset not in ("dev", "test"):
        raise ValueError(f"dataset 须为 dev 或 test，收到 {dataset!r}")
    return PROCESSED_DIR / f"sim_{dataset}"
