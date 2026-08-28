import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' }
})

export default {
  // Houses
  getHouses: () => api.get('/houses'),
  getHouse: (id) => api.get(`/houses/${id}`),
  getHouseByQR: (qr) => api.get(`/houses/qr/${qr}`),
  getHouseComponents: (id, cat) => api.get(`/houses/${id}/components`, { params: { category: cat } }),
  getHousePipeline: (id) => api.get(`/houses/${id}/pipeline`),
  getHouseHistory: (id) => api.get(`/houses/${id}/history`),

  // Chat
  initChat: (houseId) => api.post('/chat/init', { house_id: houseId }),
  sendMessage: (sessionId, message) => api.post('/chat/message', { session_id: sessionId, message }),
  chatAction: (sessionId, action) => api.post('/chat/action', { session_id: sessionId, action }),

  // Work Orders
  getWorkOrders: (params) => api.get('/workorders', { params }),
  getWorkOrder: (id) => api.get(`/workorders/${id}`),
  // 阶段3：查询工单的「故障记忆」（同设备近180天历史维修 + AI维修连续性建议）。
  // orderNo 从哪来：工单详情页路由参数 route.params.id，即工单号（如 "WO-1302-20260827131641"），
  //               与 getWorkOrder 用的 id 是同一个值，无需额外获取。
  // 为什么单独请求：历史维修记录是工单详情的「辅助上下文」，
  //                若塞进 getWorkOrder 会让基本信息加载变慢、且每次刷新详情都重复查询；
  //                单独请求可独立 loading / 失败兜底，不阻塞审核、派单、维修等主流程。
  // 返回数据用在哪：WorkOrderDetail.vue 的【故障记忆】卡片 ——
  //                重复故障警告、历史维修时间线、AI维修连续性建议都来自这个接口。
  getFaultMemory: (orderNo) => api.get(`/workorders/${orderNo}/fault-memory`),
  reviewWorkOrder: (id, data) => api.put(`/workorders/${id}/review`, data),
  completeWorkOrder: (id, data) => api.put(`/workorders/${id}/complete`, data),
  // 阶段5.7：独立派单流程
  getRepairers: () => api.get('/workorders/repairers'),          // 在册维修人员列表（派单下拉）
  assignWorkOrder: (id, data) => api.put(`/workorders/${id}/assign`, data),  // 独立派单
  // 阶段5.8：开始维修（已派单 → 维修中）
  startWorkOrder: (id, data) => api.put(`/workorders/${id}/start`, data),    // 开始维修
  getWorkOrderStats: () => api.get('/workorders/stats/summary'),

  // Maintenance
  getMaintenanceHistory: (houseId) => api.get(`/maintenance/history/${houseId}`),
}
