// 户内：墙体门窗、地面、家具、厨卫器具、灯具插座、配电箱与入户水表组，以及给水、排水、电气回路、传感器
import * as THREE from 'three'
import { Batch, pipeGeometry, centerGeometry, textSprite } from './geo'
import { mat } from './materials'
import { LAYOUTS, SLOTS, buildWalls, rectToPlate, toPlate, EXT_T, INT_T, ROOM_NAMES, roomCenter } from '../data/layouts'
import { supplyRoutes, drainRoutes, circuitRoutes, supplyAnchors, parseHouseId, panelAnchor } from '../data/resolver'

const ROOM_FLOOR = {
  BEDROOM_MAIN: 'floorBed', BEDROOM_2: 'floorBed', BEDROOM_3: 'floorBed', LIVING: 'floorLiving',
  KITCHEN: 'floorKitchen', BATHROOM: 'floorWet', BALCONY: 'floorBalcony', STORAGE: 'floorStorage',
}

/** 局部盒子 → 楼栋局部盒子 */
function lbox(batch, slot, key, x0, y0, h0, x1, y1, h1) {
  const r = rectToPlate(slot, Math.min(x0, x1), Math.min(y0, y1), Math.max(x0, x1), Math.max(y0, y1))
  batch.box(key, r.minX, h0, r.minZ, r.maxX, h1, r.maxZ)
}

function localMesh(slot, material, x0, y0, h0, x1, y1, h1) {
  const r = rectToPlate(slot, Math.min(x0, x1), Math.min(y0, y1), Math.max(x0, x1), Math.max(y0, y1))
  const g = new THREE.BoxGeometry(Math.max(r.maxX - r.minX, 0.01), Math.max(h1 - h0, 0.01), Math.max(r.maxZ - r.minZ, 0.01))
  const m = new THREE.Mesh(g, material)
  m.position.set((r.minX + r.maxX) / 2, (h0 + h1) / 2, (r.minZ + r.maxZ) / 2)
  return m
}

// ---------------------------------------------------------------------------
// 家具
// ---------------------------------------------------------------------------
function furniture(b, slot, f) {
  const { x, y, w, d } = f
  const X0 = x - w / 2, X1 = x + w / 2, Y0 = y - d / 2, Y1 = y + d / 2
  const L = (...a) => lbox(b, slot, ...a)
  switch (f.t) {
    case 'bed': {
      L('wood', X0, Y0, 0, X1, Y1, 0.42)
      L('ceramic', X0 + 0.05, Y0 + 0.05, 0.42, X1 - 0.05, Y1 - 0.05, 0.6)
      if (f.head === 'y+') {
        L('wood', X0, Y1 - 0.08, 0, X1, Y1, 1.05)
        L('fabric2', X0 + 0.1, Y1 - 0.55, 0.6, X1 - 0.1, Y1 - 0.12, 0.72)
        L('fabric', X0 + 0.02, Y0 + 0.02, 0.6, X1 - 0.02, Y0 + d * 0.55, 0.66)
        L('wood', X0 - 0.5, Y1 - 0.45, 0, X0 - 0.05, Y1, 0.5); L('wood', X1 + 0.05, Y1 - 0.45, 0, X1 + 0.5, Y1, 0.5)
      } else {
        L('wood', X0, Y0, 0, X0 + 0.08, Y1, 1.05)
        L('fabric2', X0 + 0.12, Y0 + 0.1, 0.6, X0 + 0.55, Y1 - 0.1, 0.72)
        L('fabric', X0 + w * 0.45, Y0 + 0.02, 0.6, X1 - 0.02, Y1 - 0.02, 0.66)
      }
      break
    }
    case 'wardrobe': L('wood', X0, Y0, 0, X1, Y1, 2.2); break
    case 'bookcase': L('wood', X0, Y0, 0, X1, Y1, 2.0); for (let k = 1; k < 5; k++) L('fabric2', X0 + 0.02, Y0 + 0.05, k * 0.4, X1 - 0.02, Y1 - 0.05, k * 0.4 + 0.25); break
    case 'sofa': {
      L('fabric', X0, Y0, 0, X1, Y1, 0.42)
      if (f.back === 'y+') L('fabric', X0, Y1 - 0.22, 0.42, X1, Y1, 0.88)
      else L('fabric', X0, Y0, 0.42, X1, Y0 + 0.22, 0.88)
      L('fabric', X0, Y0, 0.42, X0 + 0.2, Y1, 0.62); L('fabric', X1 - 0.2, Y0, 0.42, X1, Y1, 0.62)
      L('fabric2', X0 + 0.3, Y0 + 0.15, 0.42, X0 + 0.7, Y1 - 0.3, 0.58)
      break
    }
    case 'tv': L('wood', X0, Y0, 0, X1, Y1, 0.45); L('counter', X0 + 0.1, y - 0.03, 0.75, X1 - 0.1, y + 0.03, 1.55); break
    case 'coffee': L('wood', X0, Y0, 0.36, X1, Y1, 0.42); L('metal', X0 + 0.05, Y0 + 0.05, 0, X1 - 0.05, Y1 - 0.05, 0.36); break
    case 'dining': {
      L('wood', X0, Y0, 0.72, X1, Y1, 0.77)
      L('metal', x - 0.05, y - 0.05, 0, x + 0.05, y + 0.05, 0.72)
      for (const sx of [-0.3, 0.3]) for (const sy of [-1, 1]) {
        const cx = x + sx * w, cy = y + sy * (d / 2 + 0.3)
        L('fabric2', cx - 0.2, cy - 0.2, 0.42, cx + 0.2, cy + 0.2, 0.47)
        L('wood', cx - 0.2, sy > 0 ? cy + 0.16 : cy - 0.2, 0.47, cx + 0.2, sy > 0 ? cy + 0.2 : cy - 0.16, 0.9)
      }
      break
    }
    case 'desk': L('wood', X0, Y0, 0.72, X1, Y1, 0.76); L('wood', X0, Y0, 0, X0 + 0.05, Y1, 0.72); L('wood', X1 - 0.05, Y0, 0, X1, Y1, 0.72); L('fabric', x - 0.22, Y1 + 0.1, 0.42, x + 0.22, Y1 + 0.5, 0.47); break
    case 'counter': L('furniture', X0, Y0, 0, X1, Y1, 0.86); L('counter', X0 - 0.02, Y0 - 0.02, 0.86, X1 + 0.02, Y1 + 0.02, 0.9); break
    case 'shoe': L('wood', X0, Y0, 0, X1, Y1, 1.0); break
    case 'rack': L('metal', X0, Y0, 2.35, X1, Y1, 2.4); L('metal', X0, Y0 + 0.4, 2.35, X1, Y1 + 0.4, 2.4); break
    default: break
  }
}

// ---------------------------------------------------------------------------
// 户内构建
// ---------------------------------------------------------------------------
export function buildUnit(bd, house, registry) {
  const { floor, slot } = parseHouseId(house.house_id)
  const L = LAYOUTS[house.layout_id]
  const root = new THREE.Group()
  root.name = `unit-${bd.no}-${house.house_id}`
  root.position.set(bd.x, (floor - 1) * 3.0, bd.z)
  root.userData = { houseId: house.house_id, building: bd.no }

  const layers = {}
  for (const k of ['arch', 'walls', 'glass', 'furn', 'fixtures', 'supply', 'drain', 'circuit', 'sensor', 'labels']) {
    layers[k] = new THREE.Group(); layers[k].name = k; root.add(layers[k])
  }

  // ---- 地面（每个房间一个可拾取 Mesh） ----
  for (const room of L.rooms) {
    for (const q of room.rects) {
      const m = localMesh(slot, mat(ROOM_FLOOR[room.id] || 'floorLiving'), q[0], q[1], 0.0, q[2], q[3], 0.03)
      m.receiveShadow = true
      m.userData = { pick: 'room', room: room.id, houseId: house.house_id, building: bd.no, name: `${house.house_id} ${ROOM_NAMES[room.id]}` }
      layers.arch.add(m)
    }
  }

  // ---- 墙体、玻璃、门 ----
  const { walls, glass, doors, railings } = buildWalls(L)
  const wb = new Batch()
  for (const w of walls) {
    const t = w.ext ? EXT_T : INT_T
    if (w.a === 'h') lbox(wb, slot, w.ext ? 'wall' : 'intWall', w.from, w.at - t / 2, w.y0, w.to, w.at + t / 2, w.y1)
    else lbox(wb, slot, w.ext ? 'wall' : 'intWall', w.at - t / 2, w.from, w.y0, w.at + t / 2, w.to, w.y1)
  }
  const wallGroup = wb.build({ castShadow: true, receiveShadow: true })
  wallGroup.children.forEach(c => { c.userData = { pick: 'house', houseId: house.house_id, building: bd.no } })
  layers.walls.add(wallGroup)

  const gb = new Batch()
  for (const g of glass) {
    if (g.a === 'h') lbox(gb, slot, 'glass', g.from, g.at - 0.03, g.y0, g.to, g.at + 0.03, g.y1)
    else lbox(gb, slot, 'glass', g.at - 0.03, g.from, g.y0, g.at + 0.03, g.to, g.y1)
  }
  for (const rl of railings) {
    if (rl.a === 'h') lbox(gb, slot, 'railing', rl.from, rl.at - 0.03, 0, rl.to, rl.at + 0.03, 1.05)
    else lbox(gb, slot, 'railing', rl.at - 0.03, rl.from, 0, rl.at + 0.03, rl.to, 1.05)
  }
  const bal = L.rooms.find(r => r.id === 'BALCONY')
  if (bal) { const q = bal.rects[0]; lbox(gb, slot, 'slab', q[0], q[1], -0.15, q[2], q[3], 0) }
  layers.glass.add(gb.build())

  const db = new Batch()
  for (const d of doors) {
    const w = d.to - d.from
    if (d.kind === 'entry') {
      if (d.a === 'h') lbox(db, slot, 'door', d.from, d.at - 0.06, 0, d.to, d.at + 0.06, 2.1)
      continue
    }
    // 室内门：以 from 端为轴开启 90°
    if (d.a === 'v') lbox(db, slot, 'door', d.at, d.from, 0, d.at + w * (d.at < L.W / 2 ? 1 : -1), d.from + 0.04, 2.05)
    else lbox(db, slot, 'door', d.from, d.at, 0, d.from + 0.04, d.at + w, 2.05)
  }
  layers.arch.add(db.build())

  // ---- 家具 ----
  const fb = new Batch()
  for (const f of L.furniture) furniture(fb, slot, f)
  // 吸顶灯
  for (const room of L.rooms) {
    const [cx, cy] = roomCenter(L, room.id)
    lbox(fb, slot, 'lampHead', cx - 0.22, cy - 0.22, 2.84, cx + 0.22, cy + 0.22, 2.88)
  }
  layers.furn.add(fb.build({ castShadow: true, receiveShadow: true }))

  // ---- 器具（可点击查看档案） ----
  const F = L.fix
  const dev = (role) => house.devices.find(d => d.role === role)
  const addFixture = (role, build, extra = {}) => {
    const b = new Batch()
    build(b)
    const g = b.build({ castShadow: true })
    const d = dev(role)
    const info = { pick: 'part', code: d?.device_code || extra.code || role, kind: 'device', houseId: house.house_id, building: bd.no, name: d?.name || extra.name || role }
    g.userData = info
    g.traverse(o => { if (o.isMesh) o.userData = info })
    layers.fixtures.add(g)
    if (d) registry?.set(d.device_code, g)
    return g
  }
  const bathY1 = L.rooms.find(r => r.id === 'BATHROOM').rects[0][3]
  addFixture('B_TOILET', b => {
    lbox(b, slot, 'ceramic', 0.08, F.toilet.y - 0.2, 0.38, 0.26, F.toilet.y + 0.2, 0.8)
    lbox(b, slot, 'ceramic', 0.2, F.toilet.y - 0.19, 0, 0.72, F.toilet.y + 0.19, 0.42)
  })
  addFixture('B_BASIN', b => {
    lbox(b, slot, 'wood', F.basin.x - 0.4, bathY1 - 0.48, 0, F.basin.x + 0.4, bathY1 - 0.02, 0.78)
    lbox(b, slot, 'ceramic', F.basin.x - 0.42, bathY1 - 0.5, 0.78, F.basin.x + 0.42, bathY1 - 0.02, 0.86)
    lbox(b, slot, 'glass', F.basin.x - 0.35, bathY1 - 0.08, 1.2, F.basin.x + 0.35, bathY1 - 0.05, 1.9)
  })
  addFixture('B_SHOWER', b => {
    const [x0, y0, x1, y1] = F.shower.box
    lbox(b, slot, 'ceramic', x0 + 0.05, y0 + 0.05, 0, x1, y1, 0.04)
    lbox(b, slot, 'glass', x1 - 0.02, y0 + 0.05, 0, x1 + 0.02, y1, 1.95)
    lbox(b, slot, 'glass', x0 + 0.05, y1 - 0.02, 0, x1, y1 + 0.02, 1.95)
    lbox(b, slot, 'metal', 0.05, F.shower.y - 0.02, 0.9, 0.12, F.shower.y + 0.02, 2.1)
    lbox(b, slot, 'metal', 0.12, F.shower.y - 0.12, 2.0, 0.4, F.shower.y + 0.12, 2.06)
  })
  addFixture('B_FLOOR_DRAIN', b => lbox(b, slot, 'metal', F.floorDrain.x - 0.09, F.floorDrain.y - 0.09, 0.03, F.floorDrain.x + 0.09, F.floorDrain.y + 0.09, 0.05))
  addFixture('B_HEATER', b => lbox(b, slot, 'appliance', F.heater.x - 0.42, F.heater.y - 0.2, 2.28, F.heater.x + 0.42, F.heater.y + 0.2, 2.68))
  addFixture('K_SINK', b => {
    lbox(b, slot, 'metal', F.sink.x - 0.24, F.sink.y - 0.36, 0.84, F.sink.x + 0.24, F.sink.y + 0.36, 0.92)
    lbox(b, slot, 'metal', F.sink.x + 0.1, F.sink.y - 0.02, 0.92, F.sink.x + 0.16, F.sink.y + 0.02, 1.15)
  })
  addFixture('K_STOVE', b => {
    lbox(b, slot, 'counter', F.stove.x - 0.28, F.stove.y - 0.36, 0.9, F.stove.x + 0.28, F.stove.y + 0.36, 0.95)
    lbox(b, slot, 'metal', F.stove.x - 0.1, F.stove.y - 0.4, 1.85, F.stove.x + 0.3, F.stove.y + 0.4, 2.25)
  }, { name: '燃气灶与油烟机' })
  addFixture('K_FRIDGE', b => lbox(b, slot, 'appliance', F.fridge.x - 0.35, F.fridge.y - 0.33, 0, F.fridge.x + 0.35, F.fridge.y + 0.33, 1.8), { name: '冰箱' })
  addFixture('WASHER', b => lbox(b, slot, 'appliance', F.washer.x - 0.3, F.washer.y - 0.3, 0, F.washer.x + 0.3, F.washer.y + 0.3, 0.85), { name: '洗衣机' })
  if (house.layout_id !== 'T65') addFixture('Y_FLOOR_DRAIN', b => lbox(b, slot, 'metal', F.washerDrain.x - 0.08, F.washerDrain.y - 0.08, 0.02, F.washerDrain.x + 0.08, F.washerDrain.y + 0.08, 0.04))
  for (const [room, p] of Object.entries(L.ac)) {
    const role = (house.devices.find(d => d.role?.startsWith('L_AC') && d.location && (room === 'LIVING' ? d.name.includes('客厅') : d.name.includes('卧')))?.role) || `AC_${room}`
    addFixture(role, b => {
      if (p.wall === 'y') lbox(b, slot, 'appliance', p.x - 0.45, p.y - 0.12, 2.3, p.x + 0.45, p.y + 0.1, 2.62)
      else lbox(b, slot, 'appliance', p.x - 0.12, p.y - 0.45, 2.3, p.x + 0.1, p.y + 0.45, 2.62)
    }, { name: room === 'LIVING' ? '客厅空调' : '卧室空调' })
  }
  // 入户配电箱（含断路器）
  const [pxL, pyL] = panelAnchor(house)
  const panel = addFixture('PANEL', b => {
    lbox(b, slot, 'panel', pxL - 0.3, pyL - 0.06, 1.35, pxL + 0.3, pyL + 0.06, 1.95)
  }, { code: `CB-${house.house_id}-MAIN`, name: '入户配电箱' })
  registry?.set(`CB-${house.house_id}-MAIN`, panel)
  house.circuits.forEach((c, i) => {
    const bx = pxL - 0.2 + i * 0.065
    const m = localMesh(slot, mat('circuit'), bx - 0.022, pyL - 0.1, 1.62, bx + 0.022, pyL - 0.05, 1.78)
    const info = { pick: 'part', code: `${c.circuit_code}-OUT`, kind: 'terminal', houseId: house.house_id, building: bd.no, name: `${c.name} 断路器` }
    m.userData = info
    layers.fixtures.add(m)
    registry?.set(`${c.circuit_code}-OUT`, m)
    registry?.set(`${c.circuit_code}-IN`, m)
  })

  // ---- 给水 ----
  const SA = supplyAnchors(house)
  for (const seg of supplyRoutes(house)) {
    const color = seg.side === 'HOT' ? 'hot' : (seg.side === 'MIXED' ? 'metal' : 'cold')
    const pts = seg.routes.flat().length > 1 ? seg.routes : [[seg.end]]
    const geos = pts.map(r => pipeGeometry(r.map(p => plate3(slot, p)), seg.kind === 'PIPE' ? 0.028 : 0.022))
    const geo = geos.length > 1 ? mergeAll(geos) : geos[0]
    const c = centerGeometry(geo)
    const mesh = new THREE.Mesh(geo, mat(color))
    mesh.position.copy(c)
    mesh.userData = { pick: 'part', code: seg.code, kind: 'supply', houseId: house.house_id, building: bd.no, name: seg.name }
    layers.supply.add(mesh)
    registry?.set(seg.code, mesh)
    // 阀门、水表、过滤器等节点件
    if (['METER', 'VALVE', 'FILTER', 'PRV', 'ANGLE_VALVE', 'MIXER', 'HEATER_FILTER'].includes(seg.kind)) {
      const [x, y, h] = SA[seg.code.split('-').slice(2).join('-')] || seg.end
      const s = seg.kind === 'METER' || seg.kind === 'FILTER' ? 0.09 : 0.055
      const node = localMesh(slot, mat(seg.kind === 'METER' ? 'panel' : 'metal'), x - s, y - s, h - s, x + s, y + s, h + s)
      node.userData = mesh.userData
      layers.supply.add(node)
    }
  }
  // ---- 排水 ----
  for (const seg of drainRoutes(house)) {
    const geos = seg.routes.map(r => pipeGeometry(r.map(p => plate3(slot, p)), seg.kind === 'BRANCH' ? 0.05 : 0.035))
    const geo = geos.length > 1 ? mergeAll(geos) : geos[0]
    const c = centerGeometry(geo)
    const mesh = new THREE.Mesh(geo, mat('drain'))
    mesh.position.copy(c)
    mesh.userData = { pick: 'part', code: seg.code, kind: 'drain', houseId: house.house_id, building: bd.no, name: seg.name }
    layers.drain.add(mesh)
    registry?.set(seg.code, mesh)
  }
  // ---- 电气回路 ----
  for (const c of circuitRoutes(house)) {
    if (!c.routes.length) continue
    const geo = mergeAll(c.routes.map(r => pipeGeometry(r.map(p => plate3(slot, p)), 0.014, 6)))
    const cc = centerGeometry(geo)
    const mesh = new THREE.Mesh(geo, mat('circuit'))
    mesh.position.copy(cc)
    mesh.userData = { pick: 'part', code: c.code, kind: 'circuit', houseId: house.house_id, building: bd.no, name: c.name }
    layers.circuit.add(mesh)
    registry?.set(c.code, mesh)
    // 末端（插座、灯位）
    for (const e of c.ends) {
      const s = 0.06
      const end = localMesh(slot, mat('circuit'), e[0] - s, e[1] - s, e[2] - s, e[0] + s, e[1] + s, e[2] + s)
      end.userData = mesh.userData
      layers.circuit.add(end)
    }
  }
  // ---- 传感器 ----
  const sgeo = new THREE.SphereGeometry(0.075, 12, 8)
  for (const s of house.sensors) {
    const r = registry?.resolve?.(s.sensor_code)
    if (!r) continue
    const m = new THREE.Mesh(sgeo, mat('sensor'))
    const [px, pz] = toPlate(slot, r.local[0], r.local[1])
    m.position.set(px, r.local[2], pz)
    m.userData = { pick: 'part', code: s.sensor_code, kind: 'sensor', houseId: house.house_id, building: bd.no, name: `${SENSOR_NAME[s.type] || s.type}传感器` }
    layers.sensor.add(m)
    registry?.set(s.sensor_code, m)
  }

  // ---- 房间名标签 ----
  for (const room of L.rooms) {
    const [cx, cy] = roomCenter(L, room.id)
    const [px, pz] = toPlate(slot, cx, cy)
    const t = textSprite(ROOM_NAMES[room.id], { size: 34, scale: 0.55, bg: 'rgba(255,255,255,0.75)' })
    t.position.set(px, 1.3, pz)
    layers.labels.add(t)
  }
  const [hx, hz] = toPlate(slot, L.W / 2, L.D / 2)
  const tag = textSprite(`${house.house_id}`, { size: 44, scale: 1.1, color: '#ffffff', bg: 'rgba(22,119,255,0.9)' })
  tag.position.set(hx, 3.4, hz)
  tag.userData.houseTag = true
  root.add(tag)

  return { root, layers }
}

export const SENSOR_NAME = { FL: '流量', PR: '压力', LV: '水位', WL: '水浸', PS: '人体存在', TH: '温湿度', TP: '温度' }

function plate3(slot, [lx, ly, h]) {
  const [x, z] = toPlate(slot, lx, ly)
  return [x, h, z]
}

function mergeAll(geos) {
  const { mergeGeometries } = THREE_UTILS
  const m = mergeGeometries(geos, false)
  geos.forEach(g => g.dispose())
  return m
}

import * as BGU from 'three/addons/utils/BufferGeometryUtils.js'
const THREE_UTILS = BGU

export function slotOf(houseId) {
  return SLOTS[String(houseId).slice(-2)]
}
