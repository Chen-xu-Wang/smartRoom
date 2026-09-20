// 问题高亮：事件信标、楼层光带、住户体块、部位闪烁放大、批次热力
import * as THREE from 'three'
import { SEVERITY_META, TYPE_META, CLOSED_STATUSES } from '../data/events'
import { BUILDINGS, FLOOR_H, FLOORS } from '../data/site'
import { SLOTS, slotBounds, PLATE } from '../data/layouts'
import { parseHouseId } from '../data/resolver'
import { radialTexture } from './buildSite'

function pinTexture(color, text) {
  const c = document.createElement('canvas'); c.width = 128; c.height = 160
  const ctx = c.getContext('2d')
  ctx.fillStyle = color
  ctx.beginPath(); ctx.arc(64, 60, 52, 0, Math.PI * 2); ctx.fill()
  ctx.beginPath(); ctx.moveTo(34, 98); ctx.lineTo(64, 156); ctx.lineTo(94, 98); ctx.fill()
  ctx.fillStyle = '#ffffff'; ctx.beginPath(); ctx.arc(64, 60, 40, 0, Math.PI * 2); ctx.fill()
  ctx.fillStyle = color; ctx.font = 'bold 50px "Microsoft YaHei", sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'
  ctx.fillText(text, 64, 62)
  const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace
  return tex
}

let NIGHT = false
export function setHighlightTheme(theme) { NIGHT = theme === 'night' }

// 白天用普通混合（叠加混合在浅色背景上会发白），夜间用叠加混合更有发光感
function additive(color, opacity = 0.5) {
  return new THREE.MeshBasicMaterial({ color, transparent: true, opacity, depthWrite: false, depthTest: false, blending: NIGHT ? THREE.AdditiveBlending : THREE.NormalBlending })
}

export class Highlighter {
  constructor(engine) {
    this.engine = engine
    this.root = new THREE.Group(); this.root.name = 'highlights'
    engine.scene.add(this.root)
    this.markers = new THREE.Group(); this.markers.name = 'eventMarkers'
    this.focus = new THREE.Group(); this.focus.name = 'focusHighlight'
    this.heat = new THREE.Group(); this.heat.name = 'heat'
    this.selection = new THREE.Group(); this.selection.name = 'selection'
    this.root.add(this.markers, this.focus, this.heat, this.selection)
    this.pulses = []
    this.scaled = []
  }

  // ------------------------------------------------------------------ 事件信标
  setMarkers(events, { onlyHouse = null, visible = true } = {}) {
    this.markers.clear()
    this.pulses = this.pulses.filter(p => !p.marker)
    const bd = BUILDINGS[0]
    const perFloorSlot = new Map()
    for (const ev of events) {
      if (CLOSED_STATUSES.includes(ev.status)) continue
      if (onlyHouse && ev.houseId !== onlyHouse) continue
      const sev = SEVERITY_META[ev.severity] || SEVERITY_META.LOW
      const meta = TYPE_META[ev.type] || { icon: '!' }
      const pos = this.markerAnchor(ev, bd)
      if (!pos) continue
      const k = `${Math.round(pos.x)}:${Math.round(pos.y)}:${Math.round(pos.z)}`
      const n = perFloorSlot.get(k) || 0; perFloorSlot.set(k, n + 1)
      const g = new THREE.Group()
      g.position.copy(pos).add(new THREE.Vector3(n * 1.6, n * 0.8, 0))
      const beam = new THREE.Mesh(new THREE.CylinderGeometry(0.12, 0.35, 5, 10, 1, true), additive(sev.hex, 0.55))
      beam.position.y = 2.5
      const pin = new THREE.Sprite(new THREE.SpriteMaterial({ map: pinTexture(sev.color, meta.icon), depthTest: false, transparent: true }))
      pin.scale.set(2.6, 3.25, 1); pin.position.y = 6.4; pin.renderOrder = 20
      const glow = new THREE.Sprite(new THREE.SpriteMaterial({ map: radialTexture(), color: sev.hex, transparent: true, depthWrite: false, depthTest: false, blending: THREE.AdditiveBlending }))
      glow.scale.set(5, 5, 1); glow.position.y = 6.4
      const info = { pick: 'event', eventId: ev.id, name: `${meta.label} · ${ev.houseId || ev.event.scope}` }
      pin.userData = info; beam.userData = info
      g.add(beam, glow, pin)
      g.userData = { eventId: ev.id, rank: sev.rank }
      this.markers.add(g)
      this.pulses.push({ obj: glow, kind: 'glow', speed: 3 + sev.rank, base: 5, marker: true })
      this.pulses.push({ obj: pin, kind: 'bob', speed: 2.2, base: 6.4, marker: true })
    }
    this.markers.visible = visible
    if (this.markerLevel) this.setMarkerLevel(this.markerLevel)
  }

  /** 信标随层级缩放：小区全景大、楼层中等、户内隐藏（改用部位高亮） */
  setMarkerLevel(level) {
    this.markerLevel = level
    const s = { site: 1.6, building: 1, floor: 0.35, house: 0 }[level] ?? 1
    this.markers.visible = s > 0
    this.markers.children.forEach(g => g.scale.setScalar(s || 1))
  }

  markerAnchor(ev, bd) {
    const e = ev.event
    if (e.scope === 'BATCH') return new THREE.Vector3(bd.x + PLATE.maxX + 3, 10 * FLOOR_H, bd.z + PLATE.southZ + 2)
    const houseId = ev.houseId || e.evidence?.trigger_house
    if (!houseId) return new THREE.Vector3(bd.x, FLOORS * FLOOR_H + 4, bd.z)
    const { floor, slot } = parseHouseId(houseId)
    const s = SLOTS[slot]
    const bb = slotBounds(slot)
    const x = bd.x + (bb.minX + bb.maxX) / 2
    const z = bd.z + (s.south ? bb.maxZ + 1.5 : bb.minZ - 1.5)
    return new THREE.Vector3(x, (floor - 1) * FLOOR_H + 0.5, z)
  }

  // ------------------------------------------------------------------ 聚焦高亮
  clearFocus() {
    for (const s of this.scaled) s.obj.scale.setScalar(s.base)
    this.scaled = []
    this.pulses = this.pulses.filter(p => !p.focus)
    this.focus.clear()
  }

  /** targets 来自 eventTargets；registry 为编码 → Object3D */
  showFocus(targets, { level, registry, resolve }) {
    this.clearFocus()
    if (!targets) return
    const sev = SEVERITY_META[targets.severity] || SEVERITY_META.MEDIUM
    const bd = BUILDINGS[0]

    // 楼层光带（楼栋/小区层级可见）
    for (const f of targets.floors) this.addFloorBand(bd, f, targets.scope === 'BATCH' ? 0xffb020 : sev.hex, targets.scope === 'BATCH')
    // 住户体块
    if (targets.houseId && level !== 'house') this.addUnitBlock(bd, targets.houseId, sev.hex, 0.35)
    for (const h of targets.related) if (h !== targets.houseId) this.addUnitBlock(bd, h, 0xffa940, 0.18)
    for (const h of targets.faulted) this.addUnitBlock(bd, h, 0xf5222d, 0.32)

    // 部位
    const mark = (code, color, strong) => {
      const obj = registry?.get(code)
      if (obj) this.addPartHalo(obj, color, strong)
      else {
        const r = resolve?.(code)
        if (r?.world) this.addPointHalo(new THREE.Vector3(...r.world), color, strong ? 0.35 : 0.22)
      }
    }
    if (targets.facility) mark(targets.facility, sev.hex, !targets.primary)
    if (targets.primary) mark(targets.primary, sev.hex, true)
    for (const c of targets.secondary) mark(c, 0xfadb14, false)
    for (const c of targets.sensors) mark(c, 0x13c2c2, false)
  }

  addFloorBand(bd, floor, color, soft) {
    const y = (floor - 1) * FLOOR_H
    const w = PLATE.maxX - PLATE.minX + 1.2, d = PLATE.southZ - PLATE.northZ + 4.2
    const g = new THREE.Group()
    const m = additive(color, soft ? 0.22 : 0.5)
    const t = 0.25, h = soft ? FLOOR_H : 0.6
    const parts = [
      [w, h, t, 0, (PLATE.southZ + 2.2)], [w, h, t, 0, PLATE.northZ - 0.6],
      [t, h, d, PLATE.minX - 0.6, (PLATE.southZ + PLATE.northZ) / 2 + 1.4], [t, h, d, PLATE.maxX + 0.6, (PLATE.southZ + PLATE.northZ) / 2 + 1.4],
    ]
    for (const [a, b2, c, x, z] of parts) {
      const mesh = new THREE.Mesh(new THREE.BoxGeometry(a, b2, c), m)
      mesh.position.set(bd.x + x, y + (soft ? FLOOR_H / 2 : FLOOR_H - 0.3), bd.z + z)
      mesh.renderOrder = 15
      g.add(mesh)
    }
    this.focus.add(g)
    this.pulses.push({ obj: m, kind: 'opacity', speed: 4, base: soft ? 0.22 : 0.5, focus: true })
  }

  addUnitBlock(bd, houseId, color, opacity) {
    const { floor, slot } = parseHouseId(houseId)
    if (!SLOTS[slot]) return
    const bb = slotBounds(slot)
    const m = additive(color, opacity)
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(bb.maxX - bb.minX + 0.3, FLOOR_H - 0.1, bb.maxZ - bb.minZ + 0.3), m)
    mesh.position.set(bd.x + (bb.minX + bb.maxX) / 2, (floor - 1) * FLOOR_H + FLOOR_H / 2, bd.z + (bb.minZ + bb.maxZ) / 2)
    mesh.renderOrder = 14
    this.focus.add(mesh)
    this.pulses.push({ obj: m, kind: 'opacity', speed: 5, base: opacity, focus: true })
  }

  addPartHalo(obj, color, strong) {
    obj.updateWorldMatrix(true, true)
    const meshes = []
    obj.traverse(o => { if (o.isMesh && o.geometry) meshes.push(o) })
    const m = additive(color, strong ? 0.75 : 0.45)
    for (const src of meshes) {
      const h = new THREE.Mesh(src.geometry, m)
      src.matrixWorld.decompose(h.position, h.quaternion, h.scale)
      h.userData.baseScale = h.scale.clone()
      h.renderOrder = 30
      this.focus.add(h)
      this.pulses.push({ obj: h, kind: 'halo', speed: strong ? 7 : 4, focus: true, amp: strong ? 0.35 : 0.12 })
    }
    this.pulses.push({ obj: m, kind: 'blink', speed: strong ? 8 : 4, base: strong ? 0.85 : 0.5, focus: true })
    // 目标本身跳动放大
    if (strong && obj.isMesh) {
      this.scaled.push({ obj, base: obj.scale.x })
      this.pulses.push({ obj, kind: 'scale', speed: 6, base: obj.scale.x, focus: true, amp: 0.22 })
    }
    // 光环
    const box = new THREE.Box3().setFromObject(obj)
    const c = new THREE.Vector3(); box.getCenter(c)
    const size = box.getSize(new THREE.Vector3()).length()
    this.addPointHalo(c, color, Math.min(1.2, Math.max(0.3, size * 0.35)), strong)
  }

  addPointHalo(pos, color, radius, strong = true) {
    const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: radialTexture(), color, transparent: true, opacity: NIGHT ? 1 : 0.45, depthWrite: false, depthTest: false, blending: NIGHT ? THREE.AdditiveBlending : THREE.NormalBlending }))
    s.position.copy(pos)
    const base = radius * 3
    s.scale.set(base, base, 1)
    s.renderOrder = 31
    this.focus.add(s)
    this.pulses.push({ obj: s, kind: 'glow', speed: strong ? 6 : 3, base, focus: true })
    const ringGeo = new THREE.RingGeometry(radius * 1.1, radius * 1.35, 40)
    const ring = new THREE.Mesh(ringGeo, additive(color, 0.9))
    ring.material.side = THREE.DoubleSide
    ring.position.copy(pos)
    ring.renderOrder = 32
    ring.userData.billboard = true
    this.focus.add(ring)
    this.pulses.push({ obj: ring, kind: 'ring', speed: 2.2, base: 1, focus: true })
  }

  // ------------------------------------------------------------------ 选中构件（蓝色描边，不闪烁）
  setSelection(obj) {
    this.selection.clear()
    if (!obj) return
    obj.updateWorldMatrix(true, true)
    const m = new THREE.MeshBasicMaterial({ color: 0x1677ff, transparent: true, opacity: 0.45, depthTest: false, depthWrite: false })
    obj.traverse(src => {
      if (!src.isMesh || !src.geometry) return
      const h = new THREE.Mesh(src.geometry, m)
      src.matrixWorld.decompose(h.position, h.quaternion, h.scale)
      h.scale.multiplyScalar(1.06)
      h.renderOrder = 25
      this.selection.add(h)
    })
  }

  // ------------------------------------------------------------------ 批次/分区热力（住宅视角）
  setFloorHeat(buildingNo, colorByFloor) {
    this.heat.clear()
    if (!colorByFloor) return
    const bd = BUILDINGS.find(b => b.no === buildingNo)
    for (const [floor, color] of Object.entries(colorByFloor)) {
      const m = new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.28, depthWrite: false })
      const mesh = new THREE.Mesh(new THREE.BoxGeometry(PLATE.maxX - PLATE.minX + 0.8, FLOOR_H - 0.2, PLATE.southZ - PLATE.northZ + 3.4), m)
      mesh.position.set(bd.x, (floor - 1) * FLOOR_H + FLOOR_H / 2, bd.z + 0.75)
      mesh.userData.floor = Number(floor)
      this.heat.add(mesh)
    }
  }

  /** 楼层剖切时隐藏剖切层及以上的着色块 */
  cutHeat(floor) {
    this.heat.children.forEach(m => { m.visible = !floor || m.userData.floor < floor })
  }

  tick(t, camera) {
    for (const p of this.pulses) {
      const s = Math.sin(t * p.speed)
      switch (p.kind) {
        case 'glow': { const k = p.base * (1 + 0.35 * s); p.obj.scale.set(k, k, 1); break }
        case 'bob': p.obj.position.y = p.base + 0.35 * s; break
        case 'opacity': p.obj.opacity = p.base * (0.55 + 0.45 * (s * 0.5 + 0.5)); break
        case 'blink': p.obj.opacity = p.base * (s > -0.2 ? 1 : 0.15); break
        case 'halo': { const k = 1 + (p.amp || 0.2) * (s * 0.5 + 0.5); p.obj.scale.copy(p.obj.userData.baseScale).multiplyScalar(k); break }
        case 'scale': p.obj.scale.setScalar(p.base * (1 + (p.amp || 0.2) * (s * 0.5 + 0.5))); break
        case 'ring': {
          const k = 1 + ((t * p.speed) % 1) * 1.6
          p.obj.scale.setScalar(k)
          p.obj.material.opacity = 0.9 * (1 - ((t * p.speed) % 1))
          if (camera) p.obj.quaternion.copy(camera.quaternion)
          break
        }
        default: break
      }
    }
  }
}
