import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' }
})

// 登录态在 localStorage（stores/auth.js 写入），3D 独立工程复用本文件时同样生效
const AUTH_KEY = 'zw_auth'
function savedToken() {
  try { return JSON.parse(localStorage.getItem(AUTH_KEY) || 'null')?.token || null } catch { return null }
}

api.interceptors.request.use((config) => {
  const token = savedToken()
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// 令牌失效（过期、账号被禁用）：清掉本地登录态，并通知页面回到登录
api.interceptors.response.use(
  (res) => res,
  (error) => {
    const url = error.config?.url || ''
    if (error.response?.status === 401 && !url.startsWith('/auth/login')) {
      try { localStorage.removeItem(AUTH_KEY) } catch { /* 隐私模式下忽略 */ }
      window.dispatchEvent(new CustomEvent('auth:expired'))
    }
    return Promise.reject(error)
  },
)

/** 错误提示文字：后端 detail 可能是字符串，也可能是 { code, message } */
export function errorText(error, fallback = '操作失败') {
  const d = error?.response?.data?.detail
  if (typeof d === 'string') return d
  return d?.message || fallback
}

export default {
  // Auth
  login: (username, password) => api.post('/auth/login', { username, password }),
  me: () => api.get('/auth/me'),
  health: () => api.get('/health', { timeout: 2500 }),

  // 3D 数字孪生数据（后端按登录账号裁剪）
  getTwinBuilding: () => api.get('/twin/building', { timeout: 60000 }),
  getTwinDemoEvents: () => api.get('/twin/demo-events'),

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
  uploadAttachment: (orderNo, file, attachmentType = 'file', aiDescription = '') => {
    const fd = new FormData()
    fd.append('repair_order_id', orderNo)
    fd.append('file', file)
    fd.append('attachment_type', attachmentType)
    fd.append('ai_description', aiDescription)
    // 上传人由后端按登录令牌确定
    return api.post('/chat/attachment', fd, { headers: { 'Content-Type': 'multipart/form-data' } })
  },
  transcribeAudio: (file) => {
    const fd = new FormData()
    fd.append('file', file)
    return api.post('/chat/transcribe', fd, { headers: { 'Content-Type': 'multipart/form-data' } })
  },

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
  // AI 智能调度：看板总览、单工单预览与安全自动派单
  getDispatchOverview: () => api.get('/workorders/dispatch/overview'),
  getDispatchPlan: (id) => api.get(`/workorders/${id}/dispatch-plan`),
  autoAssignWorkOrder: (id, data) => api.post(`/workorders/${id}/auto-assign`, data),
  batchAutoAssignWorkOrders: (data) => api.post('/workorders/dispatch/auto-assign-batch', data),

  // Admin - Houses
  adminListHouses: () => api.get('/admin/houses'),
  adminCreateHouse: (data) => api.post('/admin/houses', data),
  adminUpdateHouse: (code, data) => api.put(`/admin/houses/${code}`, data),
  adminDeleteHouse: (code) => api.delete(`/admin/houses/${code}`),
  // Admin - Users
  adminListUsers: (role) => api.get('/admin/users', { params: role ? { role } : {} }),
  adminCreateUser: (data) => api.post('/admin/users', data),
  adminUpdateUser: (id, data) => api.put(`/admin/users/${id}`, data),
  adminDeleteUser: (id) => api.delete(`/admin/users/${id}`),
  // 住户房屋绑定
  adminHouseCodes: () => api.get('/admin/house-codes'),
  adminSetUserHouses: (id, houses) => api.put(`/admin/users/${id}/houses`, { houses }),

  // Maintenance
  getMaintenanceHistory: (houseId) => api.get(`/maintenance/history/${houseId}`),
  getMaintenanceRisks: (params) => api.get('/maintenance/risks', { params }),

  // 主动感知（模拟数据）：检测事件、住户提醒、复查与建单
  getSensingSamples: (houseId = '1302') => api.get('/sensing/samples', { params: { house_id: houseId } }),
  runWaterBlockage: (houseId, scenario) => api.post('/sensing/water-blockage/run', { house_id: houseId, scenario }, { timeout: 120000 }),
  runSensingDetection: (houseId, detector, scenario) => api.post('/sensing/run', { house_id: houseId, detector, scenario }, { timeout: 180000 }),
  resetSensingDemo: (houseId) => api.post('/sensing/demo/reset', null, { params: { house_id: houseId } }),
  getSensingEvents: (params) => api.get('/sensing/events', { params }),
  getSensingEvent: (eventId) => api.get(`/sensing/events/${eventId}`),
  recheckSensingEvent: (eventId) => api.post(`/sensing/events/${eventId}/recheck`, null, { timeout: 120000 }),
  createSensingWorkOrder: (eventId) => api.post(`/sensing/events/${eventId}/workorder`, {}),
  getSensingNotices: (params) => api.get('/sensing/notices', { params }),
  readSensingNotice: (id) => api.post(`/sensing/notices/${id}/read`),
  repairFromNotice: (id) => api.post(`/sensing/notices/${id}/repair`, {}),
  dismissNotice: (id) => api.post(`/sensing/notices/${id}/dismiss`),
}
