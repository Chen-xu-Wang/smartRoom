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
  reviewWorkOrder: (id, data) => api.put(`/workorders/${id}/review`, data),
  completeWorkOrder: (id, data) => api.put(`/workorders/${id}/complete`, data),
  getWorkOrderStats: () => api.get('/workorders/stats/summary'),

  // Maintenance
  getMaintenanceHistory: (houseId) => api.get(`/maintenance/history/${houseId}`),
}
