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

export const useAuthStore = defineStore('auth', {
  state: () => {
    let saved = null
    try {
      saved = JSON.parse(localStorage.getItem(STORAGE_KEY))
    } catch { saved = null }
    return { user: saved && saved.username ? saved : null }
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
          houseId: null,
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
