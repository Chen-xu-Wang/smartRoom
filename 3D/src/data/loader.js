// 数据加载：楼栋拓扑、演示样例事件、联机事件
// 楼栋与演示事件含全部住户档案，由后端 /api/twin/* 按登录账号裁剪后下发（需要登录）：
// 无权访问的住户只有户型外壳，户内设备、传感器、管线为空。
import api from '@app/api/index.js'
import { setBuildingData } from './resolver'
import { normalize } from './events'

export async function loadBuilding() {
  const { data } = await api.getTwinBuilding()
  setBuildingData(data)
  return data
}

export async function loadDemo() {
  const { data } = await api.getTwinDemoEvents()
  return { events: data.events.map(normalize), orders: data.work_orders || [] }
}

/** 探测后端是否可用（健康检查接口，无需登录） */
export async function probeBackend() {
  try {
    await api.health()
    return true
  } catch {
    return false
  }
}

/** 联机工单：只取主动感知产生的工单（source = AUTO_SENSOR），映射成维修视角用的结构 */
export async function loadLiveOrders(api) {
  const res = await api.getWorkOrders({ page_size: 100 })
  const rows = res.data.orders || []
  return rows
    .filter(o => o.source === 'AUTO_SENSOR' && !['COMPLETED', 'CANCELLED'].includes(o.raw_status))
    .map(o => ({
      order_no: o.order_no, event_id: o.trigger_event_id, house_id: o.house_id, status: o.raw_status,
      repairer: o.assigned_to || '', priority: o.priority, fault_type: o.fault_type, trade: o.suggested_trade,
      location: o.location, materials: o.materials || [], safety: o.worker_safety_notice || [], summary: o.ai_analysis,
    }))
}

/** 联机事件：列表 + 逐个详情（含决策、提醒） */
export async function loadLive(api) {
  const res = await api.getSensingEvents({ limit: 100 })
  const list = res.data.events || []
  const details = await Promise.all(list.map(e => api.getSensingEvent(e.event_id).then(r => r.data).catch(() => null)))
  return details.filter(Boolean).map(d => normalize({
    origin: 'LIVE', status: d.status, event: d.event, decision: d.decision,
    notices: d.notices, work_order_id: d.work_order_id,
    trend: d.diagnostics?.daily ? { daily: d.diagnostics.daily, threshold: -0.3 } : null,
    chart: d.diagnostics?.chart || null,
  }))
}
