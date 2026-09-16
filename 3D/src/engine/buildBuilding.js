// 楼栋外壳：标准层模板（只生成一次，各楼各层克隆共享几何）、屋顶、首层入口、排水立管
import * as THREE from 'three'
import { Batch, textSprite, pipeGeometry, centerGeometry } from './geo'
import { mat } from './materials'
import { LAYOUTS, SLOTS, PLATE, CORE, buildWalls, isPlateBoundary, rectToPlate, toPlate, EXT_T, WALL_H } from '../data/layouts'
import { FLOORS, FLOOR_H } from '../data/site'

let FLOOR_TEMPLATE = null

function wallRect(slot, w, t) {
  return w.a === 'h' ? rectToPlate(slot, w.from, w.at - t / 2, w.to, w.at + t / 2) : rectToPlate(slot, w.at - t / 2, w.from, w.at + t / 2, w.to)
}

export function floorTemplate() {
  if (FLOOR_TEMPLATE) return FLOOR_TEMPLATE
  const b = new Batch()
  // 楼板
  b.box('slab', PLATE.minX, -0.15, PLATE.northZ, PLATE.maxX, 0, PLATE.southZ)
  b.box('slabEdge', PLATE.minX - 0.04, -0.15, PLATE.southZ - 0.02, PLATE.maxX + 0.04, 0.02, PLATE.southZ + 0.04)
  b.box('slabEdge', PLATE.minX - 0.04, -0.15, PLATE.northZ - 0.04, PLATE.maxX + 0.04, 0.02, PLATE.northZ + 0.02)
  b.box('slabEdge', PLATE.minX - 0.04, -0.15, PLATE.northZ, PLATE.minX + 0.02, 0.02, PLATE.southZ)
  b.box('slabEdge', PLATE.maxX - 0.02, -0.15, PLATE.northZ, PLATE.maxX + 0.04, 0.02, PLATE.southZ)

  for (const [slot, s] of Object.entries(SLOTS)) {
    const L = LAYOUTS[s.layout]
    const { walls, glass, railings } = buildWalls(L)
    for (const w of walls) {
      if (!isPlateBoundary(slot, w)) continue
      const r = wallRect(slot, w, EXT_T)
      b.box('wall', r.minX, w.y0, r.minZ, r.maxX, Math.min(w.y1, FLOOR_H - 0.15), r.maxZ)
    }
    for (const g of glass) {
      if (!isPlateBoundary(slot, g)) continue
      const r = wallRect(slot, g, 0.06)
      b.box('glass', r.minX, g.y0, r.minZ, r.maxX, g.y1, r.maxZ)
      // 窗框
      const fr = wallRect(slot, g, EXT_T + 0.02)
      b.box('frame', fr.minX, g.y1 - 0.06, fr.minZ, fr.maxX, g.y1, fr.maxZ)
      b.box('frame', fr.minX, g.y0, fr.minZ, fr.maxX, g.y0 + 0.06, fr.maxZ)
      if (g.a === 'h') {
        const mid = (g.from + g.to) / 2
        const m = rectToPlate(slot, mid - 0.03, g.at - 0.11, mid + 0.03, g.at + 0.11)
        b.box('frame', m.minX, g.y0, m.minZ, m.maxX, g.y1, m.maxZ)
      }
    }
    // 阳台：楼板、玻璃栏板、扶手
    const balcony = L.rooms.find(r => r.id === 'BALCONY')
    if (balcony) {
      const [x0, y0, x1, y1] = balcony.rects[0]
      const r = rectToPlate(slot, x0, y0, x1, y1)
      b.box('slab', r.minX, -0.15, r.minZ, r.maxX, 0, r.maxZ)
      b.box('slabEdge', r.minX - 0.03, -0.15, r.minZ - 0.03, r.maxX + 0.03, 0.0, r.maxZ + 0.03)
      for (const rl of railings) {
        const rr = rl.a === 'h' ? rectToPlate(slot, rl.from, rl.at - 0.03, rl.to, rl.at + 0.03) : rectToPlate(slot, rl.at - 0.03, rl.from, rl.at + 0.03, rl.to)
        b.box('railing', rr.minX, 0.0, rr.minZ, rr.maxX, 1.05, rr.maxZ)
        b.box('frame', rr.minX - 0.02, 1.05, rr.minZ - 0.02, rr.maxX + 0.02, 1.12, rr.maxZ + 0.02)
      }
    }
    // 空调外机（带支架）
    for (const ac of L.outdoorAC) {
      const [px, pz] = toPlate(slot, ac.x, ac.y)
      const alongX = true
      b.box('acUnit', px - 0.42, 0.15, pz - 0.18, px + 0.42, 0.75, pz + 0.18)
      b.box('frame', px - 0.45, 0.1, pz - 0.2, px + 0.45, 0.15, pz + 0.2)
      if (alongX) b.box('seam', px - 0.2, 0.3, pz - 0.19, px + 0.2, 0.6, pz + 0.19)
    }
    // MiC 模块拼缝：沿外立面按房间边界的竖缝
    const cuts = new Set()
    for (const room of L.rooms) for (const q of room.rects) { if (q[1] <= 0.001) { cuts.add(q[0]); cuts.add(q[2]) } }
    for (const cx of cuts) {
      const [px, pz] = toPlate(slot, cx, 0)
      const out = s.south ? 1 : -1
      b.box('seam', px - 0.035, 0, pz - 0.005 + out * 0.1, px + 0.035, FLOOR_H - 0.15, pz + 0.005 + out * 0.13)
    }
  }
  // 走廊两端墙与窗
  for (const x of [PLATE.minX, PLATE.maxX]) {
    b.box('wall', x - 0.1, 0, -1, x + 0.1, 0.9, 1)
    b.box('wall', x - 0.1, 2.4, -1, x + 0.1, FLOOR_H - 0.15, 1)
    b.box('glass', x - 0.03, 0.9, -0.9, x + 0.03, 2.4, 0.9)
  }
  // 核心筒北立面（楼梯间窗）
  b.box('core', CORE.x0, 0, CORE.z0 - 0.1, CORE.x1, FLOOR_H - 0.15, CORE.z0 + 0.1)
  for (const cx of [-8.3, 8.3]) b.box('glass', cx - 0.8, 1.0, CORE.z0 - 0.13, cx + 0.8, 2.2, CORE.z0 - 0.08)
  for (const cx of [-3, 0, 3]) b.box('seam', cx - 0.03, 0, CORE.z0 - 0.14, cx + 0.03, FLOOR_H - 0.15, CORE.z0 - 0.1)

  FLOOR_TEMPLATE = b.build({ castShadow: true, receiveShadow: true })
  return FLOOR_TEMPLATE
}

/** 核心筒内部（楼层剖切时显示）：电梯井、楼梯、走廊、管井 */
export function buildCoreInterior() {
  const b = new Batch()
  b.box('floorStorage', PLATE.minX, 0, -1, PLATE.maxX, 0.02, 1)
  b.box('floorStorage', CORE.x0, 0, CORE.z0, CORE.x1, 0.02, CORE.z1)
  // 走廊两侧墙（户门墙由户内生成，这里补核心筒南墙，留电梯厅开口）
  b.box('intWall', CORE.x0, 0, CORE.z1 - 0.1, -4.2, WALL_H, CORE.z1)
  b.box('intWall', 4.2, 0, CORE.z1 - 0.1, CORE.x1, WALL_H, CORE.z1)
  b.box('intWall', CORE.x0, 0, CORE.z0, CORE.x0 + 0.1, WALL_H, CORE.z1)
  b.box('intWall', CORE.x1 - 0.1, 0, CORE.z0, CORE.x1, WALL_H, CORE.z1)
  // 电梯井 ×3
  for (let i = 0; i < 3; i++) {
    const x = -3.6 + i * 2.6
    b.box('core', x, 0, -8.8, x + 2.3, WALL_H, -8.7)
    b.box('core', x, 0, -8.8, x + 0.1, WALL_H, -5.4)
    b.box('core', x + 2.2, 0, -8.8, x + 2.3, WALL_H, -5.4)
    b.box('metal', x + 0.4, 0, -5.45, x + 1.9, 2.1, -5.38)
  }
  // 楼梯间 ×2（踏步示意）
  for (const sx of [-1, 1]) {
    const x0 = sx < 0 ? CORE.x0 + 0.2 : 6.2
    b.box('intWall', x0 - 0.1, 0, CORE.z0, x0, WALL_H, -1.1)
    for (let k = 0; k < 9; k++) b.box('wallAlt', x0 + 0.2, 0, -8.6 + k * 0.28, x0 + 1.9, 0.17 * (k + 1), -8.32 + k * 0.28)
    for (let k = 0; k < 9; k++) b.box('wallAlt', x0 + 2.1, 0.17 * 9 - 0.17 * k, -8.6 + k * 0.28, x0 + 3.8, 0.17 * 9 - 0.17 * k + 0.17, -8.32 + k * 0.28)
  }
  // 管井与电井
  b.box('panel', -5.6, 0, -4.2, -4.4, WALL_H, -1.2)
  b.box('panel', 4.4, 0, -4.2, 5.6, WALL_H, -1.2)
  const g = b.build({ receiveShadow: true })
  g.name = 'coreInterior'
  g.userData.coreLabels = true
  const l1 = textSprite('电梯厅', { size: 36, scale: 0.9, depthTest: true }); l1.position.set(0, 1.6, -3.5); g.add(l1)
  const l2 = textSprite('水管井', { size: 30, scale: 0.7, depthTest: true }); l2.position.set(-5, 3.2, -2.7); g.add(l2)
  const l3 = textSprite('电井', { size: 30, scale: 0.7, depthTest: true }); l3.position.set(5, 3.2, -2.7); g.add(l3)
  return g
}

function buildRoof() {
  const b = new Batch()
  const top = FLOORS * FLOOR_H
  b.box('roof', PLATE.minX, top - 0.15, PLATE.northZ, PLATE.maxX, top + 0.05, PLATE.southZ)
  // 女儿墙
  b.box('wall', PLATE.minX, top, PLATE.southZ - 0.2, PLATE.maxX, top + 1.2, PLATE.southZ)
  b.box('wall', PLATE.minX, top, PLATE.northZ, PLATE.maxX, top + 1.2, PLATE.northZ + 0.2)
  b.box('wall', PLATE.minX, top, PLATE.northZ, PLATE.minX + 0.2, top + 1.2, PLATE.southZ)
  b.box('wall', PLATE.maxX - 0.2, top, PLATE.northZ, PLATE.maxX, top + 1.2, PLATE.southZ)
  b.box('slabEdge', PLATE.minX - 0.05, top + 1.15, PLATE.northZ - 0.05, PLATE.maxX + 0.05, top + 1.25, PLATE.southZ + 0.05)
  // 电梯机房、楼梯出屋面
  b.box('core', -5, top, -9, 5, top + 4, -3)
  b.box('slabEdge', -5.1, top + 3.9, -9.1, 5.1, top + 4.1, -2.9)
  b.box('core', -10.4, top, -9, -6.2, top + 3.2, -4)
  b.box('core', 6.2, top, -9, 10.4, top + 3.2, -4)
  // 太阳能板阵列
  for (let i = 0; i < 6; i++) for (let j = 0; j < 3; j++) {
    const x = -16 + i * 5.4, z = 2 + j * 2.6
    const g = new THREE.BoxGeometry(4.6, 0.08, 2.0); g.rotateX(-0.35); g.translate(x + 2.3, top + 0.9, z + 1)
    b.geom('solar', g)
    b.box('metal', x + 0.3, top, z + 1.6, x + 0.4, top + 0.75, z + 1.7); b.box('metal', x + 4.2, top, z + 1.6, x + 4.3, top + 0.75, z + 1.7)
  }
  return b.build({ castShadow: true, receiveShadow: true })
}

function buildLobby() {
  const b = new Batch()
  // 北侧入户大堂：玻璃门、雨棚、台阶
  b.box('glass', -3.5, 0, PLATE.northZ - 0.25, 3.5, 2.6, PLATE.northZ - 0.15)
  b.box('frame', -3.6, 2.6, PLATE.northZ - 0.3, 3.6, 2.75, PLATE.northZ - 0.1)
  b.box('canopy', -5, 3.3, PLATE.northZ - 4, 5, 3.55, PLATE.northZ)
  b.box('metal', -4.8, 0, PLATE.northZ - 3.9, -4.6, 3.3, PLATE.northZ - 3.7)
  b.box('metal', 4.6, 0, PLATE.northZ - 3.9, 4.8, 3.3, PLATE.northZ - 3.7)
  b.box('plaza', -5, 0, PLATE.northZ - 4, 5, 0.15, PLATE.northZ)
  return b.build({ castShadow: true })
}

/**
 * 生成一栋楼：返回 { group, floors[], proxies[], label }
 * 每层是一个 Group（克隆自模板），可单独隐藏以实现楼层剖切。
 */
export function buildBuilding(bd) {
  const group = new THREE.Group()
  group.name = `building-${bd.no}`
  group.position.set(bd.x, 0, bd.z)
  const tpl = floorTemplate()

  // 默认用实例化渲染 18 个标准层（每种材质一次绘制）；只有被剖切的楼栋才展开成逐层对象
  const inst = new THREE.Group()
  inst.name = 'floorsInstanced'
  const m4 = new THREE.Matrix4()
  for (const ch of tpl.children) {
    const im = new THREE.InstancedMesh(ch.geometry, ch.material, FLOORS)
    for (let f = 0; f < FLOORS; f++) { m4.makeTranslation(0, f * FLOOR_H, 0); im.setMatrixAt(f, m4) }
    im.castShadow = ch.castShadow
    im.receiveShadow = ch.receiveShadow
    inst.add(im)
  }
  group.add(inst)

  const proxyMat = new THREE.MeshBasicMaterial({ visible: false })
  const proxyGeo = new THREE.BoxGeometry(PLATE.maxX - PLATE.minX + 0.6, FLOOR_H, PLATE.southZ - PLATE.northZ + 2)
  const proxies = []
  for (let f = 1; f <= FLOORS; f++) {
    const p = new THREE.Mesh(proxyGeo, proxyMat)
    p.position.set(0, (f - 1) * FLOOR_H + FLOOR_H / 2, (PLATE.southZ + PLATE.northZ) / 2 + 0.7)
    p.userData = { pick: 'floor', building: bd.no, floor: f }
    group.add(p)
    proxies.push(p)
  }

  const roof = buildRoof(); roof.name = 'roof'; group.add(roof)
  const lobby = buildLobby(); group.add(lobby)
  const label = textSprite(bd.name, { size: 64, scale: 4.2, color: '#ffffff', bg: bd.live ? 'rgba(22,119,255,0.92)' : 'rgba(90,100,112,0.85)' })
  label.position.set(0, FLOORS * FLOOR_H + 9, -6)
  group.add(label)
  if (!bd.live) {
    const tag = textSprite('暂未接入数据', { size: 36, scale: 1.6, color: '#ffffff', bg: 'rgba(120,128,138,0.8)' })
    tag.position.set(0, FLOORS * FLOOR_H + 6.2, -6)
    group.add(tag)
  }

  const b = {
    group, inst, proxies, roof, label, bd, floors: null,
    /** 剖切时才生成逐层对象（克隆共享几何与材质） */
    ensureFloors() {
      if (b.floors) return b.floors
      b.floors = []
      for (let f = 1; f <= FLOORS; f++) {
        const fg = tpl.clone()
        fg.position.y = (f - 1) * FLOOR_H
        fg.userData = { building: bd.no, floor: f }
        group.add(fg)
        b.floors.push(fg)
      }
      return b.floors
    },
  }
  return b
}

/** 排水立管：6 根 × 18 段，按编码 STxx-Fa-Fb 注册，便于逐段高亮 */
export function buildStacks(bd, registry) {
  const g = new THREE.Group()
  g.name = 'stacks'
  const m = mat('stack')
  for (const [slot, s] of Object.entries(SLOTS)) {
    const L = LAYOUTS[s.layout]
    const [px, pz] = toPlate(slot, L.fix.stack.x, L.fix.stack.y)
    for (let a = 0; a < FLOORS; a++) {
      const y0 = a === 0 ? -1.5 : (a - 1) * FLOOR_H - 0.14
      const y1 = a * FLOOR_H - 0.14
      const code = `ST${slot}-F${a}-F${a + 1}`
      const geo = pipeGeometry([[px, y0, pz], [px, y1, pz]], 0.07, 12)
      const c = centerGeometry(geo)
      const mesh = new THREE.Mesh(geo, m)
      mesh.position.copy(c)
      mesh.userData = { pick: 'part', code, kind: 'stack', building: bd.no, floorTop: a + 1, name: `${slot}号排水立管 ${a}–${a + 1}层段` }
      g.add(mesh)
      registry?.set(code, mesh)
    }
    // 伸顶通气管
    const vent = new THREE.Mesh(pipeGeometry([[px, FLOORS * FLOOR_H - 0.14, pz], [px, FLOORS * FLOOR_H + 1.8, pz]], 0.07, 12), m)
    vent.userData = { floorTop: 99 }
    g.add(vent)
  }
  return g
}
