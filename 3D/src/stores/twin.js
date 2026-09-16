// 数字孪生全局状态：视角、数据模式、主题、层级焦点、事件与选中对象
import { defineStore } from 'pinia'
import { markRaw } from 'vue'
import { ElMessage } from 'element-plus'
import { eventTargets, sortEvents, SEVERITY_META, CLOSED_STATUSES } from '../data/events'
import { houseById, resolveCode, parseHouseId } from '../data/resolver'
import { loadDemo, loadLive, loadLiveOrders, probeBackend } from '../data/loader'
import { useAuthStore } from '@app/stores/auth.js'
import { decodeAuth, AUTH_KEY } from '@app/utils/twin.js'
import { BUILDINGS } from '../data/site'

let engine = null
export const setEngine = (e) => { engine = e ? markRaw(e) : null }
export const getEngine = () => engine

// 后端角色 → 3D 视角
export const ROLE_OF_BACKEND = { RESIDENT: 'owner', PROPERTY: 'property', ADMIN: 'property', REPAIRER: 'repairer' }
export const ROLE_LABEL = { RESIDENT: '居民', PROPERTY: '物业', ADMIN: '管理员', REPAIRER: '维修工' }

export const ROLES = [
  { id: 'property', label: '物业', icon: 'OfficeBuilding' },
  { id: 'owner', label: '业主', icon: 'House' },
  { id: 'archive', label: '住宅', icon: 'Files' },
  // Tools 在 Element Plus 里是齿轮造型，容易被当成"设置"，改用工具箱
  { id: 'repairer', label: '维修人员', icon: 'Briefcase' },
]

export const useTwinStore = defineStore('twin', {
  state: () => ({
    ready: false,
    role: 'property',
    mode: 'demo',
    backendOnline: false,
    theme: 'day',
    level: { level: 'site', buildingNo: null, floor: null, houseId: null },
    events: [],
    demoEvents: [],
    demoOrders: [],
    orders: [],
    activeEventId: null,
    selected: null,
    hover: null,
    ownerHouse: '1302',
    repairerName: '王工',
    activeOrderNo: null,
    layers: { supply: false, drain: false, circuit: false, sensor: false, furn: true, labels: true },
    xray: false,
    colorMode: 'none',
    locating: false,
    loginUser: null,
    themeRoot: null,
  }),
  getters: {
    activeEvent: (s) => s.events.find(e => e.id === s.activeEventId) || null,
    openEvents: (s) => sortEvents(s.events.filter(e => !CLOSED_STATUSES.includes(e.status))),
    visibleEvents(s) {
      if (s.role === 'owner') return this.openEvents.filter(e => e.houseId === s.ownerHouse || (e.event.related_houses || []).includes(s.ownerHouse))
      return this.openEvents
    },
    currentHouse: (s) => (s.level.houseId ? houseById(s.level.houseId) : null),
    isLiveBuilding: (s) => !s.level.buildingNo || s.level.buildingNo === 1,
    myOrders: (s) => {
      if (s.role !== 'repairer' || !s.repairerName) return s.orders
      const mine = s.orders.filter(o => o.repairer === s.repairerName)
      // 联机数据里工单可能尚未派单（assigned_to 为空），此时显示全部待处理工单，避免列表空白
      return mine.length ? mine : s.orders.filter(o => !o.repairer)
    },
    roleLocked: (s) => !!s.loginUser,
    counts() {
      const c = { CRITICAL: 0, HIGH: 0, MEDIUM: 0, LOW: 0 }
      for (const e of this.openEvents) c[e.severity] = (c[e.severity] || 0) + 1
      return c
    },
  },
  actions: {
    async init() {
      const demo = await loadDemo()
      this.demoEvents = demo.events
      this.demoOrders = demo.orders
      this.events = demo.events
      this.orders = demo.orders
      engine.setEvents(this.events)
      this.ready = true
      probeBackend().then(ok => { this.backendOnline = ok })
    },

    async setMode(mode, api) {
      if (mode === this.mode) return
      if (mode === 'live') {
        if (!this.backendOnline) { ElMessage.warning('后端不可用，继续使用演示样例'); return }
        try {
          const [live, orders] = await Promise.all([loadLive(api), loadLiveOrders(api).catch(() => [])])
          this.events = live
          this.orders = orders
          this.mode = 'live'
          ElMessage.success(`已切换到联机数据：${live.length} 个事件、${orders.length} 张工单`)
        } catch (e) {
          ElMessage.error('联机数据加载失败，继续使用演示样例')
          return
        }
      } else {
        this.events = this.demoEvents
        this.orders = this.demoOrders
        this.mode = 'demo'
      }
      this.activeEventId = null
      engine.setFocusTargets(null)
      this.refreshMarkers()
    },

    refreshMarkers() {
      engine.setEvents(this.events, { onlyHouse: this.role === 'owner' ? this.ownerHouse : null })
    },

    /** 主题作用的 DOM 节点：独立运行是 <html>，内嵌到前端时是 3D 容器本身（不影响前端其它页面） */
    setThemeRoot(el) { this.themeRoot = el },

    applyTheme(theme, { engine: withEngine = true } = {}) {
      this.theme = theme
      const el = this.themeRoot || document.documentElement
      el.dataset.theme = theme
      // Element Plus 的暗色变量只认 html.dark，离开 3D 页面时在组件卸载里移除
      document.documentElement.classList.toggle('dark', theme === 'night')
      if (withEngine) engine?.setTheme(theme)
    },

    setTheme(theme) { this.applyTheme(theme) },

    /** 组件卸载时复位，避免下次进入 3D 页面沿用上一次的状态 */
    reset() {
      this.ready = false
      this.events = []
      this.demoEvents = []
      this.orders = []
      this.demoOrders = []
      this.activeEventId = null
      this.activeOrderNo = null
      this.selected = null
      this.hover = null
      this.level = { level: 'site', buildingNo: null, floor: null, houseId: null }
      this.themeRoot = null
    },

    /** 接收控制台同步过来的登录用户 */
    adoptAuth(user, house) {
      if (!user?.username) return
      try { localStorage.setItem(AUTH_KEY, JSON.stringify(user)) } catch { /* 隐私模式下忽略 */ }
      const auth = useAuthStore()
      auth.user = user
      const role = ROLE_OF_BACKEND[user.backendRole] || 'property'
      if (role === 'owner') this.ownerHouse = (house && houseById(house)) ? house : (user.houseId || this.ownerHouse)
      if (role === 'repairer') this.repairerName = user.name
      this.loginUser = { id: user.id, name: user.name, role, roleLabel: ROLE_LABEL[user.backendRole] || '访客' }
    },

    /** 绕过"已登录视角锁定"的内部切换（登录/同步登录态时使用） */
    async setRoleForced(role) {
      const saved = this.loginUser
      this.loginUser = null
      await this.setRole(role)
      this.loginUser = saved
    },

    signOut() {
      useAuthStore().logout()
      this.loginUser = null
    },

    async setRole(role) {
      if (this.loginUser && this.loginUser.role !== role) {
        ElMessage.warning('已登录真实账号，视角由账号角色决定；退出登录后可自由切换')
        return
      }
      this.role = role
      this.selected = null
      this.activeEventId = null
      engine.setFocusTargets(null)
      engine.clearRoute()
      engine.setRestrictHouse(role === 'owner' ? this.ownerHouse : null)
      this.xray = role === 'archive'
      engine.setXray(this.xray)
      this.layers = role === 'archive'
        ? { supply: true, drain: true, circuit: true, sensor: true, furn: false, labels: true }
        : { supply: false, drain: false, circuit: false, sensor: false, furn: true, labels: true }
      engine.setLayers(this.layers)
      this.setColorMode('none')
      this.refreshMarkers()
      if (role === 'owner') await engine.goHouse(1, this.ownerHouse)
      else if (role === 'archive') await engine.goBuilding(1)
      else if (role === 'repairer') {
        const o = this.myOrders[0]
        if (o) this.openOrder(o)
        else await engine.goSite()
      } else await engine.goSite()
    },

    async setOwnerHouse(id) {
      this.ownerHouse = id
      if (this.role === 'owner') {
        engine.setRestrictHouse(id)
        this.refreshMarkers()
        await engine.goHouse(1, id)
      }
    },

    setLayer(key, value) {
      this.layers[key] = value
      engine.setLayers({ [key]: value })
    },

    setXray(v) { this.xray = v; engine.setXray(v) },

    setColorMode(mode) {
      this.colorMode = mode
      if (mode === 'none') { engine.setFloorHeat(1, null); return }
      const map = {}
      if (mode === 'batch') {
        const colors = { A: 0x52c41a, B: 0xfaad14, C: 0x1890ff }
        for (let f = 1; f <= 18; f++) map[f] = f <= 6 ? colors.A : f <= 12 ? colors.B : colors.C
      } else if (mode === 'zone') {
        const colors = { LOW: 0x13c2c2, MID: 0x2f54eb, HIGH: 0x722ed1 }
        for (let f = 1; f <= 18; f++) map[f] = f <= 4 ? colors.LOW : f <= 11 ? colors.MID : colors.HIGH
      }
      engine.setFloorHeat(this.level.buildingNo || 1, map)
    },

    onLevel(level) {
      this.level = level
      if (this.colorMode !== 'none' && level.buildingNo) this.setColorMode(this.colorMode)
    },

    // ------------------------------------------------------------ 定位
    async locateEvent(id, { cinematic = true } = {}) {
      const ev = this.events.find(e => e.id === id)
      if (!ev) return
      if (this.role === 'owner' && ev.houseId !== this.ownerHouse && !(ev.event.related_houses || []).includes(this.ownerHouse)) {
        ElMessage.warning('隐私保护：业主视角只能查看自家相关的问题')
        return
      }
      this.activeEventId = id
      const t = eventTargets(ev)
      if (this.role === 'owner' && t.houseId !== this.ownerHouse) t.houseId = this.ownerHouse
      this.selected = t.primary ? { kind: 'code', code: t.primary } : null
      this.locating = true
      try {
        await engine.locate(ev, t, { cinematic })
      } finally {
        this.locating = false
      }
    },

    async locateTop() {
      const top = this.visibleEvents[0]
      if (!top) { ElMessage.info('当前没有待处理的问题'); return }
      await this.locateEvent(top.id)
    },

    clearEvent() {
      this.activeEventId = null
      engine.setFocusTargets(null)
    },

    // ------------------------------------------------------------ 拾取
    async onPick(info) {
      if (!info) return
      const lvl = this.level
      if (info.pick === 'event') return this.locateEvent(info.eventId)
      if (info.pick === 'facility') { this.selected = { kind: 'facility', id: info.id, name: info.name }; return }
      if (this.role === 'owner' && info.houseId && info.houseId !== this.ownerHouse) {
        ElMessage.warning('隐私保护：业主视角只能进入自己的住宅')
        return
      }
      if (info.pick === 'floor') {
        if (this.role === 'owner') { await engine.goHouse(1, this.ownerHouse); return }
        if (lvl.level === 'site' || lvl.buildingNo !== info.building) {
          if (info.building !== 1 && lvl.level === 'site') ElMessage.info(`${BUILDINGS.find(b => b.no === info.building)?.name}：结构可查看，告警与工单数据暂未接入`)
          return engine.goBuilding(info.building)
        }
        return engine.goFloor(info.building, info.floor)
      }
      if (info.pick === 'room' || info.pick === 'house') {
        if (lvl.level !== 'house' || lvl.houseId !== info.houseId) return engine.goHouse(info.building, info.houseId)
        if (info.pick === 'room') this.selected = { kind: 'room', houseId: info.houseId, room: info.room, name: info.name }
        return
      }
      if (info.pick === 'part') {
        if (lvl.level !== 'house' || lvl.houseId !== info.houseId) {
          if (info.houseId) return engine.goHouse(info.building, info.houseId)
        }
        this.selected = { kind: 'code', code: info.code, name: info.name, building: info.building }
        engine.setSelection(info.code)
      }
    },

    async selectCode(code) {
      this.selected = { kind: 'code', code }
      await engine.goPart(code, this.level.buildingNo || 1)
      engine.setSelection(code)
    },

    // ------------------------------------------------------------ 维修任务
    async openOrder(order) {
      this.activeOrderNo = order.order_no
      if (this.events.some(e => e.id === order.event_id)) await this.locateEvent(order.event_id)
    },

    async navigateToOrder(order) {
      this.activeOrderNo = order.order_no
      const ev = this.events.find(e => e.id === order.event_id)
      const t = ev ? eventTargets(ev) : null
      engine.cancelLocate()
      await engine.goSite()
      engine.showRoute(1, order.house_id, t?.primary)
      await engine.frameRoute()
      if (ev) { this.activeEventId = ev.id; engine.setFocusTargets(t) }
    },

    setHover(h) { this.hover = h },

    /**
     * 处理来自现有前端的入口参数（role / house / event / code / floor / building / theme / live）。
     * 现有前端的入口见 frontend/src/utils/twin.js。
     */
    async applyEntryParams(params, api) {
      const p = Object.fromEntries(new URLSearchParams(params))
      // 控制台带过来的登录态：落盘到本工程的 localStorage，两边显示同一个登录用户
      if (p.auth) this.adoptAuth(decodeAuth(p.auth), p.house)
      if (p.theme === 'night') {
        document.documentElement.dataset.theme = 'night'
        document.documentElement.classList.add('dark')
        this.setTheme('night')
      }
      if (p.live === '1') {
        this.backendOnline = await probeBackend()
        if (this.backendOnline) await this.setMode('live', api)
      }
      if (p.house && houseById(p.house)) this.ownerHouse = p.house
      // 已登录时视角由账号角色决定，URL 里的 role 只在未登录时生效
      const wanted = this.loginUser ? this.loginUser.role : p.role
      if (wanted && ROLES.some(r => r.id === wanted) && wanted !== this.role) await this.setRoleForced(wanted)
      const building = Number(p.building) || 1
      if (p.event) {
        if (this.events.some(e => e.id === p.event)) await this.locateEvent(p.event)
        else ElMessage.warning(`未找到事件 ${p.event}${this.mode === 'demo' ? '：当前是演示样例模式，可切换到联机数据' : ''}`)
      } else if (p.code) {
        await this.selectCode(p.code)
      } else if (p.house && houseById(p.house)) {
        await engine.goHouse(building, p.house)
      } else if (p.floor) {
        await engine.goFloor(building, Number(p.floor))
      } else if (p.building) {
        await engine.goBuilding(building)
      }
    },
  },
})

export function severityColor(sev) { return SEVERITY_META[sev]?.color || '#999' }
export { resolveCode, parseHouseId, houseById }
