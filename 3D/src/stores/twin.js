// 数字孪生全局状态：视角、数据模式、主题、层级焦点、事件与选中对象、账号权限
import { defineStore } from 'pinia'
import { markRaw } from 'vue'
import { ElMessage } from 'element-plus'
import { eventTargets, sortEvents, SEVERITY_META, CLOSED_STATUSES } from '../data/events'
import { houseById, resolveCode, parseHouseId } from '../data/resolver'
import { loadDemo, loadLive, loadLiveOrders, probeBackend } from '../data/loader'
import { useAuthStore } from '@app/stores/auth.js'
import { BUILDINGS } from '../data/site'
import { VIEWS_OF_BACKEND, READONLY_VIEWS, SCOPE_OF_BACKEND, houseIdsOf, floorOfHouse, noticeHousesOf } from '../data/access'

let engine = null
export const setEngine = (e) => { engine = e ? markRaw(e) : null }
export const getEngine = () => engine

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
    /** 当前账号可见的待处理事件 */
    visibleEvents() { return this.openEvents.filter(e => this.canSeeEvent(e)) },
    currentHouse: (s) => (s.level.houseId ? houseById(s.level.houseId) : null),
    isLiveBuilding: (s) => !s.level.buildingNo || s.level.buildingNo === 1,
    myOrders(s) {
      if (this.scopeKind === 'repairer') return this.accountOrders
      if (s.role !== 'repairer' || !s.repairerName) return s.orders
      const mine = s.orders.filter(o => o.repairer === s.repairerName)
      // 演示或物业查看时：联机工单可能尚未派单（assigned_to 为空），显示待派单工单，避免列表空白
      return mine.length ? mine : s.orders.filter(o => !o.repairer)
    },
    /** 维修人员账号名下的工单（不做"待派单"兜底） */
    accountOrders: (s) => (s.loginUser ? s.orders.filter(o => o.repairer === s.loginUser.name) : []),
    roleLocked: (s) => !!s.loginUser,
    counts() {
      const c = { CRITICAL: 0, HIGH: 0, MEDIUM: 0, LOW: 0 }
      for (const e of this.openEvents) c[e.severity] = (c[e.severity] || 0) + 1
      return c
    },

    // ------------------------------------------------------------ 权限（规则见 data/access.js）
    /** 当前账号可用的视角（未登录时不会加载数据，见 TwinRoot 的登录入口） */
    allowedRoles: (s) => (s.loginUser ? s.loginUser.views : ROLES.map(r => r.id)),
    /** 当前视角是否只读（物业查看维修视角） */
    readOnly: (s) => !!s.loginUser && (READONLY_VIEWS[s.loginUser.backendRole] || []).includes(s.role),
    /** 数据范围 all / owner / repairer（前端界面层；后端接口按同样规则裁剪数据） */
    scopeKind: (s) => (s.loginUser ? (SCOPE_OF_BACKEND[s.loginUser.backendRole] || 'owner') : (s.role === 'owner' ? 'owner' : 'all')),
    /** 可进入的住户，null 表示不限 */
    houseScope() {
      if (this.scopeKind === 'all') return null
      if (this.scopeKind === 'repairer') return [...new Set(this.accountOrders.map(o => String(o.house_id)))]
      return this.loginUser ? this.loginUser.houseIds : (this.ownerHouse ? [this.ownerHouse] : [])
    },
    canSeeHouse() {
      const scope = this.houseScope
      return (h) => !scope || (!!h && scope.includes(String(h)))
    },
    canSeeEvent(s) {
      const kind = this.scopeKind
      if (kind === 'all') return () => true
      if (kind === 'repairer') {
        const ids = new Set(this.accountOrders.map(o => o.event_id))
        return (e) => ids.has(e.id)
      }
      // 业主：发生在本户，或提醒对象包含本户（如楼上漏水影响本户）
      const own = s.ownerHouse
      return (e) => !!own && (e.houseId === own || noticeHousesOf(e).has(own) || (e.event.related_houses || []).includes(own))
    },
    /** 发生在别户、只是影响本户的事件：业主只看影响提示，不看邻居户号、户内部位与监测数据 */
    isNeighborEvent(s) {
      return (e) => this.scopeKind === 'owner' && !!e && e.houseId !== s.ownerHouse
    },
    activeTargets() { return this.activeEvent ? this.targetsOf(this.activeEvent) : null },
    /** 事件定位目标；业主视角去掉本户以外的部位、住户、楼层与公共设施 */
    targetsOf(s) {
      return (ev) => {
        const t = eventTargets(ev)
        if (this.scopeKind !== 'owner') return t
        const own = s.ownerHouse
        const inOwn = (c) => { const r = c ? resolveCode(c, 1) : null; return !!r && r.kind !== 'stack' && r.houseId === own }
        return {
          ...t, scope: 'HOUSE', houseId: own,
          primary: inOwn(t.primary) ? t.primary : null,
          secondary: t.secondary.filter(inOwn), sensors: t.sensors.filter(inOwn), controls: t.controls.filter(inOwn),
          related: [], faulted: t.faulted.includes(own) ? [own] : [], floors: own ? [floorOfHouse(own)] : [], facility: null,
        }
      }
    },
  },
  actions: {
    async init() {
      const demo = await loadDemo()
      this.demoEvents = demo.events
      this.demoOrders = demo.orders
      this.events = demo.events
      this.orders = demo.orders
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
          ElMessage.success(`已切换到联机数据：${this.visibleEvents.length} 个事件、${this.myOrders.length} 张工单`)
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
      this.activeOrderNo = null
      engine.setFocusTargets(null)
      // 工单变化会改变维修人员的可见住户，一并刷新
      this.refreshMarkers()
    },

    /** 按当前账号与视角刷新引擎的可见住户范围和事件信标 */
    refreshMarkers() {
      engine.setScope(this.houseScope)
      const kind = this.scopeKind
      // 业主只在自家显示信标（邻居事件不显示位置）；维修人员只显示自己工单的事件
      const list = kind === 'all' ? this.events
        : kind === 'owner' ? this.events.filter(e => e.houseId && e.houseId === this.ownerHouse)
          : this.events.filter(e => this.canSeeEvent(e))
      engine.setEvents(list)
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

    /** 组件卸载时复位，避免下次进入 3D 页面沿用上一次的状态（含登录身份，进入时重新读取） */
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
      this.role = 'property'
      this.loginUser = null
      this.ownerHouse = '1302'
      this.repairerName = '王工'
    },

    /** 采用登录用户：视角、可见住户、维修人员身份都以账号为准，页面和 URL 都改不了 */
    adoptAuth(user) {
      if (!user?.username) return
      const views = VIEWS_OF_BACKEND[user.backendRole] || []
      const houseIds = houseIdsOf(user).filter(h => houseById(h))
      if (user.backendRole === 'RESIDENT') this.ownerHouse = houseIds[0] || null
      if (user.backendRole === 'REPAIRER') this.repairerName = user.name
      this.loginUser = {
        id: user.id, username: user.username, name: user.name, backendRole: user.backendRole,
        role: views[0] || null, roleLabel: ROLE_LABEL[user.backendRole] || '访客', views, houseIds,
      }
    },

    /** 退出登录：已加载的数据按账号裁剪过，整页刷新回到登录入口 */
    signOut() {
      useAuthStore().logout()
      location.reload()
    },

    async setRole(role) {
      if (!this.allowedRoles.includes(role)) {
        ElMessage.warning('当前账号无权使用该视角')
        return
      }
      this.role = role
      this.selected = null
      this.activeEventId = null
      this.activeOrderNo = null
      engine.setFocusTargets(null)
      engine.clearRoute()
      this.xray = role === 'archive'
      engine.setXray(this.xray)
      this.layers = role === 'archive'
        ? { supply: true, drain: true, circuit: true, sensor: true, furn: false, labels: true }
        : { supply: false, drain: false, circuit: false, sensor: false, furn: true, labels: true }
      engine.setLayers(this.layers)
      this.setColorMode('none')
      this.refreshMarkers()
      const scope = this.houseScope
      if (role === 'owner') await (this.ownerHouse ? engine.goHouse(1, this.ownerHouse) : engine.goSite())
      else if (role === 'archive') {
        if (!scope) await engine.goBuilding(1)
        else if (scope.length) await engine.goHouse(1, scope.includes(this.ownerHouse) ? this.ownerHouse : scope[0])
        else await engine.goSite()
      } else if (role === 'repairer') {
        const o = this.myOrders[0]
        if (o) this.openOrder(o)
        else await engine.goSite()
      } else await engine.goSite()
    },

    async setOwnerHouse(id) {
      if (this.loginUser && !this.loginUser.houseIds.includes(id)) { ElMessage.warning('只能切换到您名下的住宅'); return }
      this.ownerHouse = id
      this.activeEventId = null
      engine.setFocusTargets(null)
      this.refreshMarkers()
      if (this.role === 'owner') await engine.goHouse(1, id)
    },

    setLayer(key, value) {
      this.layers[key] = value
      engine.setLayers({ [key]: value })
    },

    setXray(v) { this.xray = v; engine.setXray(v) },

    setColorMode(mode) {
      // 批次、供水分区着色是整栋楼的信息，受限账号不可用
      if (mode !== 'none' && this.houseScope) mode = 'none'
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

    deniedText() {
      if (this.scopeKind === 'owner') return '隐私保护：只能进入自己的住宅'
      if (this.scopeKind === 'repairer') return '只能查看您工单涉及的住户'
      return '无权查看'
    },

    // ------------------------------------------------------------ 定位
    async locateEvent(id, { cinematic = true } = {}) {
      const ev = this.events.find(e => e.id === id)
      if (!ev) return
      if (!this.canSeeEvent(ev)) {
        ElMessage.warning(this.scopeKind === 'owner' ? '隐私保护：只能查看与您家相关的问题' : '该问题不在您的工单范围内')
        return
      }
      this.activeEventId = id
      const t = this.targetsOf(ev)
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
      const scope = this.houseScope
      if (scope && info.pick !== 'floor' && (!info.houseId || !this.canSeeHouse(info.houseId))) {
        ElMessage.warning(this.deniedText())
        return
      }
      if (info.pick === 'floor') {
        if (lvl.level === 'site' || lvl.buildingNo !== info.building) {
          if (info.building !== 1 && lvl.level === 'site') ElMessage.info(`${BUILDINGS.find(b => b.no === info.building)?.name}：结构可查看，告警与工单数据暂未接入`)
          return engine.goBuilding(info.building)
        }
        // 受限账号：本层有自己可见的户才进入该户，由引擎判断
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
      if (this.houseScope) {
        const r = resolveCode(code, this.level.buildingNo || 1)
        // 户内构件看住户是否可见；立管等公共部位只对维修人员开放（且须在其工单楼层，由引擎判断）
        const ok = r && (r.kind === 'stack' ? this.scopeKind === 'repairer' : r.kind !== 'facility' && this.canSeeHouse(r.houseId))
        if (!ok) { ElMessage.warning(this.deniedText()); return }
      }
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
     * 进入 3D 页面：确定登录身份，再处理来自现有前端的入口参数
     * （role / house / event / code / floor / building / theme / live）。
     * 所有参数都要过权限检查，改地址栏不能越权。
     */
    async applyEntryParams(params, api) {
      const p = Object.fromEntries(new URLSearchParams(params))
      // 身份：与前端共用的登录状态（独立运行时在 3D 自己的登录框登录）
      const user = useAuthStore().user
      if (user) this.adoptAuth(user)
      if (p.theme === 'night') {
        document.documentElement.dataset.theme = 'night'
        document.documentElement.classList.add('dark')
        this.setTheme('night')
      }
      if (p.live === '1') {
        this.backendOnline = await probeBackend()
        if (this.backendOnline) await this.setMode('live', api)
      }
      // 业主的当前住宅：已登录时只能是名下的房子
      if (p.house && houseById(p.house) && (!this.loginUser || this.loginUser.houseIds.includes(p.house))) this.ownerHouse = p.house
      const valid = this.allowedRoles
      if (!valid.length) {
        engine.setScope([])
        ElMessage.error('当前账号没有 3D 数字孪生的访问权限')
        return
      }
      // URL 里的 role 只能在账号允许的视角里选，否则用账号默认视角
      if (p.role && !valid.includes(p.role)) ElMessage.warning('当前账号无权使用该视角，已切换到账号默认视角')
      const wanted = valid.includes(p.role) ? p.role : (this.loginUser ? this.loginUser.role : this.role)
      await this.setRole(wanted)
      if (this.loginUser?.backendRole === 'RESIDENT' && !this.ownerHouse) ElMessage.warning('您的账号尚未绑定房屋，请联系物业')
      const building = Number(p.building) || 1
      if (p.event) {
        if (this.events.some(e => e.id === p.event)) await this.locateEvent(p.event)
        else ElMessage.warning(`未找到事件 ${p.event}${this.mode === 'demo' ? '：当前是演示样例模式，可切换到联机数据' : ''}`)
      } else if (p.code) {
        await this.selectCode(p.code)
      } else if (p.house && houseById(p.house)) {
        if (this.canSeeHouse(p.house)) await engine.goHouse(building, p.house)
        else ElMessage.warning(this.deniedText())
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
