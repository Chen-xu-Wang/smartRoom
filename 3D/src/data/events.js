// 事件归一化与定位目标解析（演示样例与联机数据共用）
import { buildingData } from './resolver'

export const TYPE_META = {
  SUPPLY_BLOCKAGE: { label: '进水堵塞', icon: '水', domain: 'WATER' },
  DRAIN_BLOCKAGE: { label: '排水堵塞', icon: '排', domain: 'WATER' },
  STACK_BLOCKAGE: { label: '立管堵塞', icon: '管', domain: 'WATER' },
  HIDDEN_LEAK: { label: '暗漏', icon: '漏', domain: 'WATER' },
  PIPE_BURST: { label: '爆管', icon: '爆', domain: 'WATER' },
  WATER_INTRUSION: { label: '水浸渗漏', icon: '浸', domain: 'JOINT' },
  LEAKAGE_CURRENT: { label: '漏电劣化', icon: '电', domain: 'POWER' },
  TERMINAL_OVERHEAT: { label: '端子发热', icon: '热', domain: 'POWER' },
  AC_EFFICIENCY_DROP: { label: '空调能效衰减', icon: '空', domain: 'POWER' },
  WATER_HEATER_SCALING: { label: '热水器结垢', icon: '垢', domain: 'JOINT' },
  CARE_ABNORMAL: { label: '独居关怀', icon: '人', domain: 'CARE' },
  BATCH_QUALITY_ALERT: { label: 'MiC 批次质量', icon: '批', domain: 'JOINT' },
  METER_OFFLINE: { label: '设备离线', icon: '离', domain: 'WATER' },
  // P1/P2：后端已实现、方案中预留的类型
  VOLTAGE_ABNORMAL: { label: '电压异常', icon: '压', domain: 'POWER' },
  NEUTRAL_BROKEN: { label: '零线断线', icon: '零', domain: 'POWER' },
  CIRCUIT_OVERLOAD: { label: '回路过载', icon: '载', domain: 'POWER' },
  ARC_FAULT: { label: '电弧故障', icon: '弧', domain: 'POWER' },
  EBIKE_INDOOR_CHARGING: { label: '电动车入户充电', icon: '车', domain: 'POWER' },
  STANDBY_WASTE: { label: '待机能耗', icon: '待', domain: 'POWER' },
  POWER_ANOMALY: { label: '用电异常', icon: '异', domain: 'POWER' },
  CONTINUOUS_FLOW: { label: '持续用水', icon: '流', domain: 'WATER' },
  PRESSURE_ABNORMAL: { label: '水压异常', icon: '压', domain: 'WATER' },
  TRAP_SEAL_DRY: { label: '水封干涸', icon: '封', domain: 'WATER' },
  NETWORK_LEAK: { label: '公共管网漏损', icon: '损', domain: 'WATER' },
}

export const SEVERITY_META = {
  CRITICAL: { label: '危急', color: '#f5222d', hex: 0xf5222d, rank: 4, tag: 'danger' },
  HIGH: { label: '高', color: '#fa8c16', hex: 0xfa8c16, rank: 3, tag: 'warning' },
  MEDIUM: { label: '中', color: '#fadb14', hex: 0xfadb14, rank: 2, tag: 'warning' },
  LOW: { label: '低', color: '#1890ff', hex: 0x1890ff, rank: 1, tag: 'info' },
}

export const ORIGIN_LABEL = {
  DETECTION_SAMPLE: '检测样例（算法输出）',
  CONTRACT_SAMPLE: '契约样例（人工构造的参考事件）',
  DEMO_SCRIPT: '演示样例事件（人工构造）',
  LIVE: '联机数据（后端事件）',
}

// 后端 device_event.status 取值：NOTIFIED / ORDER_CREATED / RESOLVED / ARCHIVED；其余为演示样例使用
export const STATUS_LABEL = {
  NOTIFIED: '已提醒', ORDER_CREATED: '已建工单', WORKORDER_CREATED: '已建工单', ESCALATED: '已升级',
  RESOLVED: '已解除', ARCHIVED: '已归档', REPAIR_REQUESTED: '已报修', RECHECK_PENDING: '待复查',
}

export const CLOSED_STATUSES = ['RESOLVED', 'ARCHIVED']

export const PRIORITY_LABEL = { URGENT: '紧急', HIGH: '高', NORMAL: '中', LOW: '低' }

export const CONTROL_LABEL = {
  CLOSE_MAIN_VALVE: '关闭入户总阀', TRIP_CIRCUIT: '回路分闸', SPEAKER_INQUIRY: '智能音箱语音询问',
}

export function normalize(item) {
  const e = item.event
  const d = item.decision || {}
  return {
    id: e.event_id,
    origin: item.origin,
    status: item.status || 'NOTIFIED',
    event: e,
    decision: d,
    trend: item.trend || null,
    chart: item.chart || null,
    notices: item.notices || null,
    workOrderId: item.work_order_id || null,
    type: e.event_type,
    severity: e.severity,
    priority: d.priority || null,
    scope: e.scope,
    houseId: e.house_id,
    title: d.fault_summary || e.evidence_text,
    detectedAt: e.detected_at,
    building: 1,
  }
}

/** 解析事件的定位目标 */
export function eventTargets(ev) {
  const e = ev.event
  const cands = e.location_candidates || []
  const t = {
    eventId: ev.id, severity: e.severity, scope: e.scope, type: e.event_type,
    houseId: e.house_id || null,
    primary: cands[0]?.segment_code || null,
    secondary: cands.slice(1).map(c => c.segment_code),
    related: e.related_houses || [],
    faulted: [], floors: [], sensors: [], controls: [], facility: null,
  }
  const ev2 = e.evidence || {}
  for (const v of Object.values(ev2)) {
    if (typeof v === 'string') {
      const m = /(SN-\d+-[A-Z]+-[A-Z]+\d+)/.exec(v)
      if (m) t.sensors.push(m[1])
    }
  }
  if (ev2.sensor_code) t.sensors.push(ev2.sensor_code)
  for (const c of e.control_actions_taken || []) if (c.target) t.controls.push(c.target)
  if (e.scope === 'STACK' && t.primary) {
    const m = /^ST0\d-F(\d+)-F(\d+)$/.exec(t.primary)
    if (m) t.floors = [Number(m[2])]
    if (ev2.trigger_house) t.houseId = ev2.trigger_house
  }
  if (e.scope === 'BATCH') {
    const b = buildingData()?.batches.find(x => x.batch_id === e.batch_id)
    if (b) for (let f = b.floors[0]; f <= b.floors[1]; f++) t.floors.push(f)
    t.faulted = ev2.faulted_houses || []
  }
  if (e.scope === 'BUILDING') {
    // 楼栋公共事件（如整相电压异常）：受影响住户整体高亮，并指向对应的公共设施
    t.facility = (TYPE_META[e.event_type]?.domain === 'POWER') ? 'CB-BLDG-PUB' : 'WS-BLDG-MID-MT'
    if (!t.primary) t.faulted = t.related
  }
  if (t.houseId && !t.floors.length) t.floors = [Number(String(t.houseId).slice(0, -2))]
  return t
}

export function sortEvents(list) {
  const openRank = s => (CLOSED_STATUSES.includes(s) ? 0 : 1)
  return [...list].sort((a, b) => openRank(b.status) - openRank(a.status)
    || (SEVERITY_META[b.severity]?.rank || 0) - (SEVERITY_META[a.severity]?.rank || 0)
    || String(b.detectedAt).localeCompare(String(a.detectedAt)))
}

/** 上游隔离点：给水管段 → 最近的上游阀门；回路 → 对应断路器 */
export function isolationPoints(house, code) {
  if (!house || !code) return []
  if (code.startsWith('CB-')) {
    const cc = code.replace(/-(OUT|IN)$/, '')
    const c = house.circuits.find(x => x.circuit_code === cc)
    return c ? [{ code: `${cc}-OUT`, name: `配电箱「${c.name}」断路器`, action: '断开并挂牌上锁' }] : []
  }
  if (code.startsWith('WS-')) {
    const bySeg = new Map(house.supply.map(s => [s.segment_code, s]))
    const out = []
    const seen = new Set()
    const walk = (c) => {
      const s = bySeg.get(c)
      if (!s || seen.has(c)) return
      seen.add(c)
      for (const p of s.parents) {
        const ps = bySeg.get(p)
        if (!ps) continue
        if (['ANGLE_VALVE', 'VALVE'].includes(ps.kind)) { out.push({ code: p, name: ps.name, action: '关闭' }); continue }
        walk(p)
      }
    }
    const self = bySeg.get(code)
    if (self && ['ANGLE_VALVE', 'VALVE'].includes(self.kind)) out.push({ code, name: self.name, action: '关闭' })
    walk(code)
    if (!out.length) out.push({ code: `WS-${house.house_id}-IN-MV`, name: '电动总阀', action: '关闭' })
    return out
  }
  if (code.startsWith('WD-')) return [{ code: null, name: '通知住户暂停该区域用水', action: '' }]
  if (/^ST0\d-F\d+-F\d+$/.test(code)) {
    const upper = Number(code.split('-F')[2])
    return [
      { code: null, name: `同立管 ${upper} 层及以上住户暂停排水`, action: '通知' },
      { code, name: `${upper} 层立管检查口`, action: '打开' },
    ]
  }
  return []
}
