# 数据契约 v2.0

> 状态：**定稿**（2026-09-15，任务 1.1）
> 作用：第一步（模拟与检测）、第二步（百炼）、第三步（接入仓库）之间唯一的接口约定
> 权威性：本目录的 `*.schema.json` 是机器可校验的权威定义；本文是说明。两者如有出入，以 Schema 为准，并应立即修正本文

## 一、文件一览

| 契约 | 方向 | Schema | 样例 |
| --- | --- | --- | --- |
| 公共定义 | — | `common.schema.json` | — |
| ① 异常事件 | 检测模块 → 百炼应用① | `event.schema.json` | `bailian_kit/events/` |
| ② 事件决策 | 百炼应用① → 后端 | `event_decision.schema.json` | `bailian_kit/expected/0*.expected.json` |
| ③-输入 月度聚合 | 检测模块 → 百炼应用② | `monthly_input.schema.json` | `bailian_kit/monthly/`、`bailian_kit/batch_brief/` |
| ③-输出 报告 | 百炼应用② → 前端 | `report_output.schema.json` | `bailian_kit/expected/monthly_*`、`batch_brief_*` |
| ④-输入 问答上下文 | 后端 → 百炼应用③ | `qa_context.schema.json` | `bailian_kit/qa/` |
| ④-输出 问答回答 | 百炼应用③ → 前端 | `qa_answer.schema.json` | `bailian_kit/expected/qa_*` |

校验命令（需要 `jsonschema>=4.18`；装了 `scipy` 才会复核批次统计的 p 值）：

```bash
python data/scripts/validate_contracts.py
python data/scripts/validate_contracts.py --contract event_decision --file 百炼输出.json --event 对应事件.json
```

## 二、版本规则

- `schema_version` 取 `2.x`。**2.x 内只允许新增可选字段**，不修改、不删除已有字段，也不收紧已有取值。
- 需要破坏性修改时升级到 `3.0`，并在本文末尾的变更记录中说明。
- 所有对象均为 `additionalProperties: false`（`evidence`、`saving_signals`、`payload` 除外），拼错的字段名会直接校验失败。

## 三、公共约定

| 项 | 约定 |
| --- | --- |
| 时间 | `YYYY-MM-DDTHH:MM:SS+08:00`；日期 `YYYY-MM-DD`；月份 `YYYY-MM` |
| 户号 | 模拟楼栋 1栋1单元，楼层 1–18 + 户位 01–06，如 `503`、`1302`；1302/805/503 为现有档案住户 |
| 批次 | `A`=1–6 层，`B`=7–12 层，`C`=13–18 层（B 批次在模拟器中预设缺陷，仅真值可见） |
| 立管 | 同户位号上下贯通，如 `ST02` 贯通 102…1802 |
| 事件编号 | `EVT-日期-范围键-4位序号`；范围键为户号、`ST0n`、`BATCH{A/B/C}` 或 `BLDG` |
| 数据来源 | `data_source` 固定为 `SIMULATED` |
| 数值单位 | 流量 L/min（字段后缀 `_lpm`），水量 L / m³，压力 MPa，时间常数 s，电流 A，剩余电流 mA，电量 kWh，温度 ℃，金额 元 |
| 比例 | `change_ratio` 等为小数（−0.43 表示下降 43%）；`confidence` 为 0–1 |

### 编码体系

| 前缀 | 含义 | 示例 | 是否在档案中 |
| --- | --- | --- | --- |
| `EQ` `PL` `EL` `DW` | 一房一码档案设备（`houses.json`） | `EQ-1302-B-02` 花洒 | 是 |
| `WS-{户}-…` | 给水拓扑部件 | `WS-1302-B-SH` 卫生间花洒头、`WS-805-IN-MV` 入户电动总阀 | 否（模拟拓扑） |
| `WD-{户}-…` | 排水拓扑部件 | `WD-1302-B-FD` 卫生间地漏 | 否 |
| `ST0n-F{a}-F{b}` | 立管楼层区间 | `ST02-F11-F12` | 否 |
| `CB-{户}-{回路}` | 电气回路（智能断路器） | `CB-1302-KT` 厨房插座回路；`-OUT`/`-IN` 为出线/进线端子 | 否 |
| `SN-{户}-{区域}-{类型}{nn}` | 传感器 | `SN-805-K-WL01` 厨房水浸 | 否 |
| `SPK-{户}-{区域}-{nn}` | 智能音箱 | `SPK-503-L-01` | 否 |

区域代码（拓扑与传感器编码）：`K` 厨房、`B` 卫生间、`L` 起居室/卧室、`IN` 入户、`Y` 阳台（2.1 新增）、`WH` 热水器（2.1 新增）。

设备编码（`EQ/PL/EL/DW`）的区域段只能是单个字母，因此入户设备使用 `E`（2.1 新增），如 `EQ-1302-E-01` 智能水表；阳台设备使用 `Y`。

回路代码：`LT` 照明、`SK` 普通插座、`KT` 厨房插座、`BT` 卫生间、`AC1`/`AC2` 空调、`WH` 热水器；`CB-{户}-MAIN` 为户总电表。

传感器类型（2.1 新增）：`FL` 流量、`PR` 压力、`LV` 水位、`WL` 水浸、`TP` 温度、`TH` 温湿度、`PS` 人体存在（毫米波雷达）。

楼栋级编码（2.1 新增）：`WS-BLDG-{LOW|MID|HIGH}-MT` 低、中、高区总水表，`WS-BLDG-PUMP-{MID|HIGH}` 中、高区二次供水泵，`CB-BLDG-PUB` 公区用电，`SN-BLDG-OUT-TH01` 室外温湿度。

每户的完整编码清单见 `sim_config/sim_building.json`（任务 1.2 生成），说明见 `sim_config/README.md`。

## 四、契约① 异常事件

### 顶层字段

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `scope` | ✓ | `HOUSE` / `STACK` / `BUILDING` / `BATCH`。`HOUSE` 时 `house_id`、`archive_context` 必须有值，其它范围必须为 `null` |
| `related_houses` | ✓ | HOUSE：可能受影响的相邻住户（如楼下）；STACK：同立管需通知的住户；BUILDING：受影响住户（空数组=全楼）；BATCH：**建议巡检的住户**（同批次尚未发生故障的住户） |
| `domain` | ✓ | `WATER` / `POWER` / `JOINT` / `CARE`。批次事件同时含水、电缺陷时用 `JOINT` |
| `location_candidates` | ✓ | 按置信度降序，最多 3 个，置信度之和 ≤ 1；关怀、批次、离线事件为空数组 |
| `evidence` | ✓ | 按 `event_type` 约定的结构化证据（见下表），只含事件级数值 |
| `evidence_text` | ✓ | ≤200 字的一句话证据，供大模型直接引用 |
| `control_actions_taken` | ✓ | 已自动执行的控制动作：`CLOSE_MAIN_VALVE`、`CLOSE_BRANCH_VALVE`、`TRIP_CIRCUIT`、`SWITCH_OFF_PLUG`、`SPEAKER_INQUIRY` |
| `archive_context.in_archive` | HOUSE 时 ✓ | 该户是否在现有 MySQL 档案中 |
| `archive_context.persona_hint` | 可选 | 仅关怀事件使用，只允许粗粒度标签 `独居老人` |
| `fault_started_est` | 可选 | 渐进型故障的估计开始日期 |

### `event_type` 与 `evidence` 必填键（P0）

| event_type | 约束 | evidence 必填键 |
| --- | --- | --- |
| `SUPPLY_BLOCKAGE` | domain=WATER | `metric` `baseline` `recent` `change_ratio` `duration_days` `inlet_pressure_change` `same_branch_other_fixtures` `hot_cold` |
| `DRAIN_BLOCKAGE` | domain=WATER | `tau_baseline_s` `tau_recent_s` `tau_ratio` `standing_water` `same_room_other_drains` |
| `STACK_BLOCKAGE` | scope=STACK，domain=WATER | `stack_id` `floor_range` `abnormal_houses` `upstream_correlation` |
| `HIDDEN_LEAK` | domain=WATER | `night_min_flow_lpm` `consecutive_nights` `est_daily_loss_l` |
| `PIPE_BURST` | domain=WATER，severity=CRITICAL | `peak_flow_lpm` `duration_s` `rated_max_lpm` `matched_fixture` `est_loss_l` `occupancy` |
| `WATER_INTRUSION` | domain=JOINT | `sensor_codes` `source_inference`（SELF/UPSTAIRS/UNKNOWN） `flow_anomaly` |
| `LEAKAGE_CURRENT` | domain=POWER | `circuit_code` `residual_ma_baseline` `residual_ma_recent` `trip_threshold_ma` `trend_days` |
| `TERMINAL_OVERHEAT` | domain=POWER，severity=CRITICAL | `circuit_code` `terminal_temp_c` `ambient_temp_c` `current_a` `rated_current_a` `rise_per_a2_baseline` `rise_per_a2_recent` |
| `AC_EFFICIENCY_DROP` | domain=POWER | `efficiency_index_baseline` `efficiency_index_recent` `change_ratio` `comparable_hours` `suspected_cause` |
| `WATER_HEATER_SCALING` | domain=JOINT | `thermal_efficiency_baseline` `thermal_efficiency_recent` `diagnosis`（SCALING/HEATING_ELEMENT/INLET_FILTER） |
| `CARE_ABNORMAL` | domain=CARE，无定位候选 | `care_level`(1–3) `signals`{water, power: NORMAL/ABSENT；presence: NORMAL/ABSENT/STATIONARY_LONG} `delay_vs_baseline_min` |
| `BATCH_QUALITY_ALERT` | scope=BATCH，无定位候选 | `observation_days` `batch_house_count` `other_house_count` `defects[]` `faulted_houses` |
| `METER_OFFLINE` | 无定位候选 | `meter_code` `offline_minutes` `last_seen_at` |
| `VOLTAGE_ABNORMAL`（2.2 新增，原 P1 预留） | domain=POWER；供电侧为 scope=BUILDING、无定位候选 | `voltage_min_v` `voltage_max_v` `limits_v`（GB/T 12325：[198, 235.4]） `minutes_out_of_range` `days_affected` `source_inference`（SUPPLY/HOUSE_WIRING/UNKNOWN） `appliances_at_risk[]`{appliance, name, range_v, minutes_outside} |

P1/P2 预留类型（本阶段不产生）：`CONTINUOUS_FLOW` `PRESSURE_ABNORMAL` `TRAP_SEAL_DRY` `NETWORK_LEAK` `CIRCUIT_OVERLOAD` `NEUTRAL_BROKEN` `EBIKE_INDOOR_CHARGING` `ARC_FAULT` `STANDBY_WASTE` `POWER_ANOMALY`。它们的 evidence 必填键在实现时以新增 `if/then` 的方式补充。

### 隐私约束

- `evidence` 与 `evidence_text` **不得包含原始曲线和具体作息时间**（如"平时 6:40 起床"）。关怀事件只允许相对偏差，如 `delay_vs_baseline_min`。
- 事件发生时刻（`detected_at`、控制动作时间）不属于作息信息，可以使用。

## 五、契约② 事件决策

| 字段 | 说明 |
| --- | --- |
| `actionable` | `false` 时 `notices`、`workorders`、`control_suggestions` 必须为空（用于低置信干扰） |
| `priority` | `URGENT` / `HIGH` / `NORMAL` / `LOW`，与 `repair_order.priority` 一致 |
| `fault_summary` | ≤60 字，含可能性百分比 |
| `notices[]` | `audience`：RESIDENT（事件户）/ NEIGHBOR（相关住户）/ FAMILY（住户授权家属）/ PROPERTY（物业）；同一 audience 最多一条；`content` ≤200 字 |
| `workorders[]` | 一个事件可以对应多个工种的多张工单。`create_mode`：`IMMEDIATE` 立即创建；`DEFERRED` 在住户点击一键报修，或 `recheck_after_days` 天后仍未恢复时创建。`fault_type`、`suggested_trade` 与 `agent.py` 取值一致 |
| `workorders[].worker_safety_notice` | 一线维修人员作业安全提示，最多 5 条 |
| `control_suggestions[]` | 建议追加的控制动作，需后端规则或人工确认后执行；**不得重复已执行的动作** |
| `escalation` | 仅关怀事件使用：`next_level`、`after_minutes`、`condition`、`action`（NOTIFY_FAMILY / CREATE_ONSITE_WORKORDER）；其它事件为 `null` |
| `knowledge_refs[]` | 格式"手册名-章节名" |

`generated_by`（百炼/规则）不由百炼输出，由后端在落库时补充。

### 决策规则

以下规则写进百炼提示词，后端再做兜底校验（`validate_contracts.py` 已实现带 ★ 的检查）。

| 事件 | priority | 工单 | 提醒与其它 |
| --- | --- | --- | --- |
| `PIPE_BURST`、`TERMINAL_OVERHEAT`（CRITICAL） | URGENT ★ | IMMEDIATE | 住户 + 物业；安全提示必填 |
| `WATER_INTRUSION` | HIGH | IMMEDIATE | 住户 + 相关住户；须提示插座回路风险 ★ |
| `STACK_BLOCKAGE` | HIGH | IMMEDIATE，公共部位 | 物业 + 同立管住户暂缓用水 |
| `LEAKAGE_CURRENT` | 接近动作值或已漏电跳闸时 HIGH，否则 NORMAL | IMMEDIATE | 住户（跳闸时同时通知物业） |
| `VOLTAGE_ABNORMAL`（2.2） | 有电器超出允许电压 ≥10 分钟时 HIGH，否则 NORMAL | IMMEDIATE：供电侧为楼栋配电工单，本户接线为户内电工工单 | 供电侧：物业 + 同相住户；本户接线：住户（避免同时使用大功率电器） |
| `BATCH_QUALITY_ALERT` | HIGH | IMMEDIATE，按缺陷工种拆分，`house_ids` 等于 `related_houses` ★ | 物业 + 巡检住户（强调"预防性检查、非故障"） |
| `CARE_ABNORMAL` | 1 级 NORMAL，2 级 HIGH，3 级 URGENT | 仅 3 级创建上门工单 ★（`其他故障` / `综合维修`，暂用） | 1 级语音询问；2 级通知家属 + 物业；3 级上门 |
| 户内堵塞、暗漏、结垢、能效衰减 | NORMAL / LOW | DEFERRED，一般 3 天复查 | 住户自检，并附免责提示 |
| `METER_OFFLINE` | LOW | IMMEDIATE（运维） | 仅物业 |

通用规则：

- 电气类工单的安全提示必须含"验电"和"挂牌" ★。
- 住户、家属、邻户文案不得出现 Cv、τ、P90、剩余电流、基线、百分位等术语 ★。
- 非关怀事件的 `escalation` 必须为 `null` ★。

**关怀分级时序**（模拟器与后端共用）：1 级语音询问 30 分钟无回应 → 2 级通知家属；2 级 20 分钟内家属未确认安全 → 3 级上门工单。

## 六、契约③ 月度聚合与报告

**输入**（`monthly_input.schema.json`，两种类型二选一）：

- `RESIDENT_MONTHLY`：
  - `water`：用水总量、分器具用水、水费、上月用水、同户型百分位、`saving_signals`。
  - `power`：用电总量、分回路电量、峰谷电量、电费、上月电量、可转移电量与节省金额、待机功率、碳排放、同户型百分位、空调运行时长。
  - 另含本月事件、设备健康分、`price_note`。
  - 一致性要求：分项之和等于总量（水 ±0.1 m³，电 ±1 kWh）；峰谷电量之和等于总量；金额等于用量 × 示例价格。
- `BATCH_BRIEF`：统计区间、批次与其它批次户数、`defects[]`（发生数、发生率比、单侧 Fisher 检验 p 值、共性位置及占比）、已故障住户、建议巡检住户、触发事件。已故障与巡检住户互斥，且合起来等于整个批次。

`saving_signals` 约定键（可选）：`avg_shower_min`、`benchmark_shower_min`、`toilet_flush_l`、`hot_water_wait_l_per_day`。

**输出**（`report_output.schema.json`）：`title`、`summary`（≤150 字）、`sections[]`（≤6 节，每节 `highlights` ≤4 个）、`actions[]`（`CREATE_AUTOMATION_RULE` / `BOOK_SERVICE` / `VIEW_EVENT` / `CREATE_BATCH_INSPECTION`）。`highlights` 的数值必须来自输入数据或其直接计算。

**价格**：样例使用示例价格——峰 0.62 元/kWh（8:00–22:00）、谷 0.32 元/kWh、水 3.5 元/m³、排放因子 0.5703 kg/kWh。均为可配置示例值，不代表特定城市的现行价格。

## 七、契约④ 水电问答

- **输入**：`question` + 最近 1–3 个月的 `monthly[]`（契约③住户月报中 `water`/`power`/`weather` 的子集）+ `recent_events[]`。后端组装后传入，百炼不回调后端。
- **输出**：
  - `answer` ≤300 字。
  - `evidence[]`：引用的数字及其在输入中的路径 `source_path`（如 `monthly[1].power.by_circuit_kwh.空调`），校验工具会核对数值。
  - `suggested_actions[]`。
  - `out_of_scope`：问题超出数据范围时为 `true`，并在 `answer` 中说明原因，**不得编造**。

## 八、传给百炼的方式

每个百炼应用在开始节点定义一个字符串参数（应用① `event_json`、应用② `report_json`、应用③ `qa_json`）。后端把契约 JSON 序列化为字符串，通过 DashScope 应用 API 的 `biz_params` 传入。参数的具体嵌套位置以百炼控制台"查看 API"中的示例为准。

## 九、变更记录

| 版本 | 日期 | 变更 |
| --- | --- | --- |
| 2.2 | 2026-09-15 | 仅新增、不破坏：`VOLTAGE_ABNORMAL` 从预留类型转为已实现，新增 evidence 必填键（见第四节）与决策规则（见第五节）；已有样例仍然有效 |
| 2.1 | 2026-09-15 | 仅新增、不破坏：`segmentCode` 正则放宽，接受立管编码 `ST0n-F{a}-F{b}`（修正 2.0 中说明与正则不一致的问题）；`archiveDeviceCode` 正则放宽，接受档案中无区域段的门窗编码 `DW-1302-01`；新增区域代码 `Y`、`WH`，设备区域段 `E`，传感器类型代码与楼栋级编码。已有样例仍然有效，`schema_version` 可继续写 `2.0` |
| 2.0 | 2026-09-15 | 定稿。相比 `工作方案.md` 初稿：契约② 的单个 `resident_notice`/`workorder_draft` 改为 `notices[]`/`workorders[]` 数组（支持邻户、家属、物业多方提醒和多工种工单）；`worker_safety_notice` 移入每张工单；新增 `create_mode`/`recheck_after_days`、`escalation`；契约① 定位候选增加 `segment_code`/`in_archive`，控制动作改为结构化对象；新增契约③-输出与契约④-输出 Schema |
