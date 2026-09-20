import { defineStore } from 'pinia'

const STORAGE_KEY = 'zw_auth'

// 角色映射：后端 role → 前端 role
function mapRole(backendRole) {
  const r = (backendRole || '').toUpperCase()
  if (r === 'RESIDENT') return 'resident'
  if (r === 'REPAIRER') return 'repairer'
  if (r === 'PROPERTY') return 'property'
  return 'admin'
}

/** 本地登录态是否可用：必须带未过期的令牌（旧版本登录态没有令牌，要求重新登录） */
function usable(saved) {
  return !!(saved?.username && saved.token && (!saved.expiresAt || saved.expiresAt * 1000 > Date.now()))
}

export const useAuthStore = defineStore('auth', {
  state: () => {
    let saved = null
    try {
      saved = JSON.parse(localStorage.getItem(STORAGE_KEY))
    } catch { saved = null }
    if (saved && !usable(saved)) {
      saved = null
      try { localStorage.removeItem(STORAGE_KEY) } catch { /* 隐私模式下忽略 */ }
    }
    return { user: saved }
  },
  getters: {
    isLoggedIn: (s) => !!s.user,
    isResident: (s) => s.user?.backendRole === 'RESIDENT',
    isRepairer: (s) => s.user?.backendRole === 'REPAIRER',
    isProperty: (s) => ['PROPERTY','ADMIN'].includes(s.user?.backendRole),
    isAdmin: (s) => ['PROPERTY','ADMIN'].includes(s.user?.backendRole), // 兼容旧守卫：物业即管理员
    isSuperAdmin: (s) => s.user?.backendRole === 'ADMIN',
    roleLabel: (s) => ({RESIDENT:'居民',REPAIRER:'维修工',PROPERTY:'物业',ADMIN:'管理员'}[s.user?.backendRole] || '访客'),
  },
  actions: {
    async login({ username, password, role }) {
      try {
        const { default: api } = await import('../api/index.js')
        const res = await api.login(username, password)
        const u = res.data
        const frontendRole = mapRole(u.role)
        // resident 标签页只允许 RESIDENT，admin 标签页允许 PROPERTY/REPAIRER/ADMIN
        if (role === 'resident' && u.role !== 'RESIDENT') {
          return { ok: false, msg: '该账号不是居民账号' }
        }
        if (role === 'admin' && u.role === 'RESIDENT') {
          return { ok: false, msg: '该账号不是管理员/维修账号' }
        }
        this.user = {
          id: u.id,
          username: u.username,
          role: frontendRole,
          backendRole: u.role,
          name: u.real_name || u.username,
          // 名下房屋（后端 user_house 绑定）；houseId 为默认房屋，兼容只用单个房号的页面
          houseIds: u.house_ids || [],
          houseId: (u.house_ids || [])[0] || null,
          // 访问令牌：api/index.js 从本地登录态读取并放进 Authorization 请求头
          token: u.token,
          expiresAt: u.expires_at,
        }
        localStorage.setItem(STORAGE_KEY, JSON.stringify(this.user))
        return { ok: true, user: this.user }
      } catch (e) {
        const msg = e.response?.data?.detail || '用户名或密码错误，请检查后重试'
        return { ok: false, msg }
      }
    },
    logout() {
      this.user = null
      localStorage.removeItem(STORAGE_KEY)
    },
  },
})
