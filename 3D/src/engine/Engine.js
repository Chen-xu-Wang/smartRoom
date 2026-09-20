// 3D 引擎：场景、灯光与主题、镜头层级（小区→楼栋→楼层→户→部位）、楼层剖切、拾取、图层、导航路线
import * as THREE from 'three'
import CameraControls from 'camera-controls'
import { buildSite } from './buildSite'
import { buildBuilding, buildStacks, buildCoreInterior } from './buildBuilding'
import { buildUnit } from './buildUnit'
import { Highlighter, setHighlightTheme } from './Highlighter'
import { setMaterialTheme, setStructureOpacity, mat } from './materials'
import { disposeTree } from './geo'
import { BUILDINGS, FLOOR_H, FLOORS, FACILITIES } from '../data/site'
import { SLOTS, LAYOUTS, slotBounds, toPlate, PLATE } from '../data/layouts'
import { houseById, resolveCode, parseHouseId } from '../data/resolver'

CameraControls.install({ THREE })

const sleep = (ms) => new Promise(r => setTimeout(r, ms))

export class Engine {
  constructor(container) {
    this.container = container
    this.renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' })
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5))
    this.renderer.shadowMap.enabled = true
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping
    container.appendChild(this.renderer.domElement)

    this.scene = new THREE.Scene()
    this.camera = new THREE.PerspectiveCamera(42, 1, 0.1, 3000)
    this.controls = new CameraControls(this.camera, this.renderer.domElement)
    this.controls.maxPolarAngle = Math.PI * 0.49
    this.controls.minDistance = 1.2
    this.controls.maxDistance = 900
    this.controls.dollyToCursor = true
    this.controls.smoothTime = 0.45

    this.hemi = new THREE.HemisphereLight(0xffffff, 0xb9a98a, 1.2)
    this.sun = new THREE.DirectionalLight(0xffffff, 2.2)
    this.sun.castShadow = true
    this.sun.shadow.mapSize.set(2048, 2048)
    this.sun.shadow.bias = -0.0004
    this.sun.shadow.normalBias = 0.02
    this.scene.add(this.hemi, this.sun, this.sun.target)

    this.registry = new Map()
    this.registry.resolve = resolveCode
    this.buildings = new Map()
    this.interior = null
    this.level = { level: 'site', buildingNo: null, floor: null, houseId: null }
    this.layers = { supply: false, drain: false, circuit: false, sensor: false, furn: true, labels: true }
    this.autoLayers = new Set()
    // 可见住户范围：null 不限；Set 时只能进入这些户，其他户只显示建筑外壳（权限见 data/access.js）
    this.scope = null
    this.xray = false
    this.lowWalls = false
    this.route = null
    this.theme = 'day'
    this.callbacks = { pick: null, hover: null, level: null, denied: null }
    this.highlighter = new Highlighter(this)
    this.focusTargets = null
    this.clock = new THREE.Clock()
    this._bind()
    this.resize()
  }

  on(name, fn) { this.callbacks[name] = fn }
  emit(name, payload) { this.callbacks[name]?.(payload) }

  // ------------------------------------------------------------------ 构建
  load() {
    this.site = buildSite()
    this.scene.add(this.site)
    this.facilitiesGroup = this.site.getObjectByName('facilities')
    this.nightGlow = this.site.getObjectByName('nightGlow')
    for (const bd of BUILDINGS) {
      const b = buildBuilding(bd)
      this.scene.add(b.group)
      this.buildings.set(bd.no, b)
    }
    this.setTheme('day')
    this.camera.position.set(170, 190, 260)
    this.controls.setLookAt(170, 190, 260, 0, 0, 10, false)
    this._updateShadow(new THREE.Vector3(0, 0, 0), 150)
    this._loop()
  }

  // ------------------------------------------------------------------ 主题
  setTheme(theme) {
    this.theme = theme
    setMaterialTheme(theme)
    setHighlightTheme(theme)
    const day = theme === 'day'
    this.scene.background = new THREE.Color(day ? 0xdfe8f0 : 0x050b18)
    this.scene.fog = new THREE.Fog(day ? 0xdfe8f0 : 0x050b18, day ? 420 : 260, day ? 1300 : 900)
    this.hemi.color.setHex(day ? 0xffffff : 0x4a6fa8)
    this.hemi.groundColor.setHex(day ? 0xb9a98a : 0x0a1020)
    this.hemi.intensity = day ? 1.25 : 0.55
    this.sun.color.setHex(day ? 0xfff4e0 : 0x8fb4ff)
    this.sun.intensity = day ? 2.3 : 0.5
    this.sun.castShadow = day
    this.renderer.toneMappingExposure = day ? 1.0 : 1.15
    if (this.nightGlow) this.nightGlow.visible = !day
    if (this.focusTargets) this._refreshFocus()
    if (this.events) this.highlighter.setMarkers(this.events, this._markerOpts || {})
  }

  _updateShadow(center, radius) {
    const s = this.sun.shadow.camera
    s.left = -radius; s.right = radius; s.top = radius; s.bottom = -radius
    s.near = 1; s.far = radius * 6
    s.updateProjectionMatrix()
    this.sun.target.position.copy(center)
    this.sun.position.copy(center).add(new THREE.Vector3(radius * 0.8, radius * 2.2, radius * 0.6))
  }

  /** 镜头过渡：页面不可见时 requestAnimationFrame 暂停，过渡 Promise 不会结束，因此加超时兜底 */
  _move(p) {
    return Promise.race([p, sleep(1400)])
  }

  // ------------------------------------------------------------------ 层级导航
  _setLevel(level) {
    this.level = level
    this.highlighter.setMarkerLevel(level.level)
    if (this.focusTargets) this.highlighter.showFocus(this.focusTargets, { level: level.level, registry: this.registry, resolve: (c) => resolveCode(c, 1) })
    this.emit('level', { ...level })
  }

  async goSite() {
    this.clearRoute()
    this._setCutaway(null, null)
    this._setLevel({ level: 'site', buildingNo: null, floor: null, houseId: null })
    this._updateShadow(new THREE.Vector3(0, 0, 0), 150)
    await this._move(this.controls.setLookAt(170, 190, 260, 0, 0, 10, true))
  }

  async goBuilding(no) {
    const b = this.buildings.get(no)
    if (!b) return
    this._ensureStacks(no)
    this._setCutaway(null, null)
    this._setLevel({ level: 'building', buildingNo: no, floor: null, houseId: null })
    const { x, z } = b.bd
    this._updateShadow(new THREE.Vector3(x, 0, z), 70)
    await this._move(this.controls.setLookAt(x + 34, 66, z + 112, x, 24, z, true))
  }

  async goFloor(no, floor) {
    const b = this.buildings.get(no)
    if (!b) return false
    floor = Math.max(1, Math.min(FLOORS, floor))
    if (this.scope) {
      // 受限账号不能浏览整层：本层有自己可见的住户就直接进入该户，否则拒绝
      const own = no === 1 ? [...this.scope].find(h => parseHouseId(h).floor === floor) : null
      if (!own) { this.emit('denied', { floor }); return false }
      return this.goHouse(no, own)
    }
    this._ensureStacks(no)
    this._setCutaway(no, floor)
    this.partZoom = false
    this._setLevel({ level: 'floor', buildingNo: no, floor, houseId: null })
    const { x, z } = b.bd
    const y = (floor - 1) * FLOOR_H
    this._updateShadow(new THREE.Vector3(x, y, z), 32)
    await this._move(this.controls.setLookAt(x + 22, y + 40, z + 44, x, y, z + 0.5, true))
  }

  async goHouse(no, houseId) {
    const b = this.buildings.get(no)
    const { floor, slot } = parseHouseId(houseId)
    if (!b || !SLOTS[slot]) return false
    if (!this.canEnterHouse(no, houseId)) { this.emit('denied', { houseId: String(houseId) }); return false }
    this._ensureStacks(no)
    this._setCutaway(no, floor)
    this.partZoom = false
    this._setLevel({ level: 'house', buildingNo: no, floor, houseId: String(houseId) })
    this._applyLayers()
    const bb = slotBounds(slot)
    const cx = b.bd.x + (bb.minX + bb.maxX) / 2, cz = b.bd.z + (bb.minZ + bb.maxZ) / 2
    const y = (floor - 1) * FLOOR_H
    const out = 1 // 始终从南侧俯视，与北向朝上的 2D 平面图方向一致
    this._updateShadow(new THREE.Vector3(cx, y, cz), 14)
    await this._move(this.controls.setLookAt(cx + 3, y + 17, cz + out * 11, cx, y, cz, true))
  }

  async goPart(code, no = 1) {
    const r = resolveCode(code, no)
    if (!r) return null
    if (r.kind === 'facility') {
      const f = FACILITIES.find(x => x.id === r.facility)
      await this.goSite()
      await this._move(this.controls.setLookAt(f.x + 22, 26, f.z + 30, f.x, 2, f.z, true))
      return r
    }
    if (r.kind === 'stack') {
      if ((await this.goFloor(no, r.floorB || r.floor)) === false) return null
      const [x, y, z] = r.world
      this.partZoom = true
      this._applyLayers()
      await this._move(this.controls.setLookAt(x + 13, y + 15, z + 18, x, y, z, true))
      return r
    }
    if (!r.houseId) return r
    if (!this.canEnterHouse(no, r.houseId)) { this.emit('denied', { houseId: r.houseId }); return null }
    if (this.level.level !== 'house' || this.level.houseId !== r.houseId || this.level.buildingNo !== no) await this.goHouse(no, r.houseId)
    const [x, y, z] = r.world
    this.partZoom = true
    this._applyLayers()
    const out = 1
    await this._move(this.controls.setLookAt(x + 3.2, y + 5.2, z + out * 6, x, y, z, true))
    return r
  }

  // ------------------------------------------------------------------ 一键定位
  /** 用户的任何新操作都会让进行中的定位动画在下一步停下 */
  cancelLocate() { this._locToken = (this._locToken || 0) + 1 }

  async locate(ev, targets, { cinematic = true } = {}) {
    this.cancelLocate()
    const token = this._locToken
    const alive = () => token === this._locToken
    this.focusTargets = targets
    const no = 1
    const code = targets.primary
    const r = code ? resolveCode(code, no) : null
    if (r?.houseId) this.autoLayers = new Set([r.kind])
    else this.autoLayers = new Set(targets.sensors.length ? ['sensor'] : [])
    const step = cinematic ? 650 : 0
    if (cinematic && this.level.level !== 'site' && this.level.buildingNo !== no) { await this.goSite(); await sleep(step / 2) }
    if (!alive()) return
    this._refreshFocus()
    if (r?.kind === 'facility') { await this.goPart(code, no); this._refreshFocus(); return }
    if (targets.scope === 'BATCH') { await this.goBuilding(no); this._refreshFocus(); return }
    if (cinematic) { await this.goBuilding(no); await sleep(step); if (!alive()) return }
    const floor = r?.kind === 'stack' ? (r.floorB || r.floor) : targets.floors[0]
    if (!floor && !targets.houseId) { await this.goBuilding(no); this._refreshFocus(); return }
    if (floor) { await this.goFloor(no, floor); if (cinematic) await sleep(step); if (!alive()) return }
    if (r?.kind === 'stack') { await this.goPart(code, no); this._refreshFocus(); return }
    if (targets.houseId) { await this.goHouse(no, targets.houseId); if (cinematic) await sleep(step); if (!alive()) return }
    if (r?.houseId) { await this.goPart(code, no); this._refreshFocus() }
  }

  /** 选中构件：蓝色描边（与问题高亮的红/橙闪烁区分） */
  setSelection(code) {
    this.selectedCode = code || null
    const obj = code ? this.registry.get(code) : null
    this.highlighter.setSelection(obj && obj.visible !== false ? obj : null)
  }

  setFocusTargets(targets) {
    this.focusTargets = targets
    if (!targets) this.autoLayers = new Set()
    this._refreshFocus()
  }

  _refreshFocus() {
    this._applyLayers()
    this.highlighter.showFocus(this.focusTargets, { level: this.level.level, registry: this.registry, resolve: (c) => resolveCode(c, 1) })
  }

  setEvents(events, opts = {}) {
    this.events = events
    this._markerOpts = opts
    this.highlighter.setMarkers(events, opts)
  }

  // ------------------------------------------------------------------ 剖切与户内
  _setCutaway(no, floor) {
    for (const [bn, b] of this.buildings) {
      const cut = bn === no && floor
      if (cut) {
        const floors = b.ensureFloors()
        b.inst.visible = false
        floors.forEach((fg, i) => { fg.visible = i + 1 < floor })
      } else {
        b.inst.visible = true
        b.floors?.forEach(fg => { fg.visible = false })
      }
      b.roof.visible = !cut
      b.label.visible = !cut
      b.group.children.forEach(ch => { if (ch.isSprite && ch !== b.label) ch.visible = !cut })
      if (b.stacks) {
        b.stacks.visible = !!cut || this.xray || this.layers.drain
        b.stacks.children.forEach(m => { m.visible = !cut || (m.userData.floorTop || 99) <= floor })
      }
    }
    this.highlighter.cutHeat(floor)
    if (no && floor) this._ensureInterior(no, floor)
    else this._disposeInterior()
  }

  _ensureStacks(no) {
    const b = this.buildings.get(no)
    if (b.stacks) return
    b.stacks = buildStacks(b.bd, this.registry)
    b.group.add(b.stacks)
    b.stacks.visible = this.xray || this.layers.drain
  }

  _disposeInterior() {
    if (!this.interior) return
    this.scene.remove(this.interior.group)
    disposeTree(this.interior.group)
    for (const code of this.interior.codes) this.registry.delete(code)
    this.interior = null
  }

  _ensureInterior(no, floor) {
    if (this.interior && this.interior.no === no && this.interior.floor === floor) return
    this._disposeInterior()
    this.highlighter.setSelection(null)
    const bd = BUILDINGS.find(b => b.no === no)
    const group = new THREE.Group(); group.name = `interior-${no}-${floor}`
    const units = new Map()
    const codes = []
    const reg = new Map(); reg.resolve = resolveCode
    for (const slot of Object.keys(SLOTS)) {
      const house = houseById(`${floor}${slot}`)
      if (!house) continue
      const u = buildUnit(bd, house, reg)
      group.add(u.root)
      units.set(house.house_id, u)
    }
    const core = buildCoreInterior()
    core.position.set(bd.x, (floor - 1) * FLOOR_H, bd.z)
    group.add(core)
    for (const [k, v] of reg) { this.registry.set(k, v); codes.push(k) }
    this.scene.add(group)
    this.interior = { no, floor, group, units, codes }
    this._applyLayers()
    if (this.selectedCode) this.setSelection(this.selectedCode)
  }

  // ------------------------------------------------------------------ 图层
  setLayers(layers) { Object.assign(this.layers, layers); this._applyLayers() }
  /** 设置可见住户范围（null 不限）；数据只接入了 1栋，受限账号不能进入其它楼栋的户内 */
  setScope(houses) {
    this.scope = houses ? new Set(houses.map(String)) : null
    if (this.scope && this.level.houseId && !this.scope.has(this.level.houseId)) this.goSite()
    this._applyLayers()
  }
  canEnterHouse(no, houseId) { return !this.scope || (no === 1 && this.scope.has(String(houseId))) }
  setXray(on) {
    this.xray = on
    setStructureOpacity(on ? 0.22 : 1)
    for (const b of this.buildings.values()) if (b.stacks) b.stacks.visible = on || this.layers.drain || (this.level.buildingNo === b.bd.no && !!this.level.floor)
    this._applyLayers()
  }
  setLowWalls(on) { this.lowWalls = on; this._applyLayers() }
  setFloorHeat(no, colorByFloor) {
    if (this.scope && colorByFloor) return
    this.highlighter.setFloorHeat(no, colorByFloor)
    this.highlighter.cutHeat(this.level.floor)
  }

  _applyLayers() {
    if (!this.interior) return
    this.interior.group.children.forEach(c => { if (c.userData.coreLabels) c.children.forEach(l => { if (l.isSprite) l.visible = !this.level.houseId && !this.partZoom }) })
    const focusHouse = this.level.houseId
    for (const [hid, u] of this.interior.units) {
      const hidden = !!this.scope && !this.scope.has(hid)
      const isFocus = hid === focusHouse
      const auto = isFocus || !!(this.focusTargets && this.focusTargets.houseId === hid)
      const L = u.layers
      L.furn.visible = !hidden && this.layers.furn
      L.fixtures.visible = !hidden
      L.labels.visible = !hidden && this.layers.labels && (isFocus || !focusHouse) && !this.partZoom
      const tag = u.root.children.find(c => c.userData.houseTag)
      if (tag) tag.visible = !focusHouse && !this.partZoom
      L.supply.visible = !hidden && (this.layers.supply || (auto && this.autoLayers.has('supply')))
      L.drain.visible = !hidden && (this.layers.drain || (auto && this.autoLayers.has('drain')))
      L.circuit.visible = !hidden && (this.layers.circuit || (auto && (this.autoLayers.has('circuit') || this.autoLayers.has('terminal'))))
      L.sensor.visible = !hidden && (this.layers.sensor || (auto && this.autoLayers.has('sensor')))
      const low = this.lowWalls || (focusHouse && isFocus)
      L.walls.scale.y = low ? 0.4 : 1
      L.glass.visible = !low
    }
  }

  // ------------------------------------------------------------------ 导航路线（维修人员）
  clearRoute() {
    if (!this.route) return
    this.scene.remove(this.route.group)
    disposeTree(this.route.group)
    this.route = null
  }

  showRoute(no, houseId, code) {
    this.clearRoute()
    const bd = BUILDINGS.find(b => b.no === no)
    const { floor, slot } = parseHouseId(houseId)
    const s = SLOTS[slot]; const L = LAYOUTS[s.layout]
    const y = (floor - 1) * FLOOR_H + 0.25
    const lobbyZ = bd.z + PLATE.northZ - 5
    const [ex, ez] = toPlate(slot, L.fix.entry.x - 0.8, L.D + 0.5)
    const pts = [
      [0, 0.3, 106], [0, 0.3, 90], [bd.x + 26, 0.3, 90], [bd.x + 26, 0.3, lobbyZ], [bd.x, 0.3, lobbyZ],
      [bd.x, 0.3, bd.z + PLATE.northZ + 1.5], [bd.x, 0.3, bd.z - 5], [bd.x, y, bd.z - 5], [bd.x, y, bd.z], [bd.x + ex, y, bd.z], [bd.x + ex, y, bd.z + ez],
    ]
    const r = code ? resolveCode(code, no) : null
    if (r?.world) { pts.push([r.world[0], y, r.world[2]]); pts.push([r.world[0], r.world[1], r.world[2]]) }
    const path = new THREE.CurvePath()
    for (let i = 1; i < pts.length; i++) path.add(new THREE.LineCurve3(new THREE.Vector3(...pts[i - 1]), new THREE.Vector3(...pts[i])))
    const segs = Math.max(64, Math.round(path.getLength() / 1.5))
    const geo = new THREE.TubeGeometry(path, segs, 0.7, 8, false)
    const tex = stripeTexture()
    tex.repeat.set(path.getLength() / 4, 1)
    const m = new THREE.MeshBasicMaterial({ map: tex, transparent: true, depthTest: false, depthWrite: false })
    const mesh = new THREE.Mesh(geo, m)
    mesh.renderOrder = 40
    const group = new THREE.Group(); group.add(mesh)
    this.scene.add(group)
    this.route = { group, tex }
  }

  /** 镜头框住导航路线（大门到 1栋） */
  async frameRoute() {
    await this._move(this.controls.setLookAt(95, 120, 175, 5, 10, 55, true))
  }

  // ------------------------------------------------------------------ 拾取
  _bind() {
    this.raycaster = new THREE.Raycaster()
    this.pointer = new THREE.Vector2()
    const el = this.renderer.domElement
    let down = null
    el.addEventListener('pointerdown', (e) => { down = { x: e.clientX, y: e.clientY } })
    el.addEventListener('pointerup', (e) => {
      if (!down || Math.hypot(e.clientX - down.x, e.clientY - down.y) > 5) return
      const info = this.pick(e)
      this.emit('pick', info)
    })
    let last = 0
    el.addEventListener('pointermove', (e) => {
      const now = performance.now()
      if (now - last < 90) return
      last = now
      const info = this.pick(e)
      el.style.cursor = info ? 'pointer' : 'grab'
      this.emit('hover', info ? { ...info, x: e.clientX, y: e.clientY } : null)
    })
    this._onResize = () => this.resize()
    window.addEventListener('resize', this._onResize)
  }

  pick(e) {
    const rect = this.renderer.domElement.getBoundingClientRect()
    this.pointer.set(((e.clientX - rect.left) / rect.width) * 2 - 1, -((e.clientY - rect.top) / rect.height) * 2 + 1)
    this.raycaster.setFromCamera(this.pointer, this.camera)
    const targets = [this.highlighter.markers]
    if (this.interior) targets.push(this.interior.group)
    for (const b of this.buildings.values()) {
      if (b.stacks?.visible) targets.push(b.stacks)
      targets.push(...b.proxies.filter((p, i) => (b.inst.visible || (b.floors && b.floors[i].visible))))
    }
    if (this.facilitiesGroup) targets.push(this.facilitiesGroup)
    const hits = this.raycaster.intersectObjects(targets, true)
    for (const h of hits) {
      let o = h.object
      if (!visibleChain(o)) continue
      while (o && !o.userData?.pick) o = o.parent
      if (o) return { ...o.userData, point: h.point.toArray() }
    }
    return null
  }

  resize() {
    const w = this.container.clientWidth || window.innerWidth
    const h = this.container.clientHeight || window.innerHeight
    this.renderer.setSize(w, h)
    this.camera.aspect = w / h
    this.camera.updateProjectionMatrix()
  }

  _loop() {
    const tick = () => {
      this._raf = requestAnimationFrame(tick)
      const dt = this.clock.getDelta()
      const t = this.clock.elapsedTime
      this.controls.update(dt)
      this.highlighter.tick(t, this.camera)
      if (this.route) this.route.tex.offset.x -= dt * 1.2
      this.renderer.render(this.scene, this.camera)
    }
    tick()
  }

  dispose() {
    cancelAnimationFrame(this._raf)
    window.removeEventListener('resize', this._onResize)
    this.controls.dispose()
    this.renderer.dispose()
    this.renderer.domElement.remove()
  }
}

function visibleChain(o) {
  while (o) { if (!o.visible) return false; o = o.parent }
  return true
}

function stripeTexture() {
  let _stripe = null
  const c = document.createElement('canvas'); c.width = 128; c.height = 32
  const ctx = c.getContext('2d')
  ctx.fillStyle = 'rgba(0,140,255,0.9)'; ctx.fillRect(0, 0, 128, 32)
  ctx.fillStyle = 'rgba(255,255,255,0.95)'
  ctx.beginPath(); ctx.moveTo(40, 4); ctx.lineTo(80, 16); ctx.lineTo(40, 28); ctx.lineTo(52, 16); ctx.closePath(); ctx.fill()
  _stripe = new THREE.CanvasTexture(c)
  _stripe.wrapS = THREE.RepeatWrapping
  _stripe.colorSpace = THREE.SRGBColorSpace
  return _stripe
}

export { mat }
