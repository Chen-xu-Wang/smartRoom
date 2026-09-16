// 编码解析：把 sim_building.json 中的管段、回路、传感器、设备、立管编码解析为户内锚点与世界坐标，
// 并生成给水、排水、电气回路的敷设路线（纯数据，不依赖 three）。
import { LAYOUTS, SLOTS, toPlate, roomCenter } from './layouts'
import { BUILDINGS, FLOOR_H, FACILITIES } from './site'

let DATA = null
const HOUSES = new Map()

export function setBuildingData(data) {
  DATA = data
  HOUSES.clear()
  for (const h of data.houses) HOUSES.set(h.house_id, h)
}
export const buildingData = () => DATA
export const houseById = (id) => HOUSES.get(String(id))

export const AREA_ROOM = { K: 'KITCHEN', B: 'BATHROOM', Y: 'BALCONY', IN: 'LIVING', WH: 'BATHROOM', L: 'LIVING', E: 'LIVING' }

export function parseHouseId(id) {
  const s = String(id)
  return { floor: Number(s.slice(0, -2)), slot: s.slice(-2) }
}

export function floorBaseY(floor) {
  return (floor - 1) * FLOOR_H
}

/** 户内局部点 → 世界坐标 */
export function localToWorld(buildingNo, houseId, lx, ly, h) {
  const b = BUILDINGS.find(x => x.no === Number(buildingNo))
  const { floor, slot } = parseHouseId(houseId)
  const [px, pz] = toPlate(slot, lx, ly)
  return [b.x + px, floorBaseY(floor) + h, b.z + pz]
}

// ---------------------------------------------------------------------------
// 锚点
// ---------------------------------------------------------------------------
function entryPoints(L, house) {
  const y = L.D - 0.16
  const x = L.fix.entry.x
  const pts = { 'IN-MT': [x, y, 0.55], 'IN-MV': [x + 0.28, y, 0.55] }
  let cursor = x + 0.56
  if (house.has_prv) { pts['IN-PRV'] = [cursor, y, 0.55]; cursor += 0.28 }
  pts['IN-FLT'] = [cursor, y, 0.55]
  pts['IN-MAIN'] = [cursor + 0.35, y - 0.3, 0.22]
  return pts
}

export function supplyAnchors(house) {
  const L = LAYOUTS[house.layout_id]
  const f = L.fix
  const bathWallY = L.rooms.find(r => r.id === 'BATHROOM').rects[0][3]
  const a = {
    ...entryPoints(L, house),
    'K-C': [f.sink.x - 0.2, f.sink.y - 0.14, 0.22],
    'K-AV': [f.sink.x + 0.12, f.sink.y - 0.14, 0.45],
    'K-HS': [f.sink.x + 0.02, f.sink.y - 0.1, 0.7],
    'K-FC': [f.sink.x + 0.12, f.sink.y, 1.08],
    'K-H': [f.sink.x - 0.2, f.sink.y + 0.14, 0.3],
    'K-AVH': [f.sink.x + 0.12, f.sink.y + 0.14, 0.45],
    'K-HSH': [f.sink.x + 0.02, f.sink.y + 0.1, 0.7],
    'B-C': [0.1, f.toilet.y - 0.35, 0.22],
    'B-AVT': [0.1, f.toilet.y + 0.2, 0.25],
    'B-WC': [0.18, f.toilet.y, 0.72],
    'B-AVB': [f.basin.x - 0.12, bathWallY - 0.1, 0.5],
    'B-AVBH': [f.basin.x + 0.12, bathWallY - 0.1, 0.5],
    'B-BS': [f.basin.x, bathWallY - 0.22, 0.95],
    'B-MV': [0.08, f.shower.y, 1.05],
    'B-SH': [0.3, f.shower.y, 2.05],
    'B-H': [0.1, f.shower.y + 0.3, 0.3],
    'WH-FLT': [f.heater.x - 0.55, f.heater.y, 2.2],
    'WH': [f.heater.x, f.heater.y, 2.45],
    'Y-C': [f.washer.x + 0.45, f.washer.y + 0.5, 0.22],
    'Y-WT': [f.washer.x + 0.2, f.washer.y - 0.32, 1.05],
    'B-WT': [f.washer.x, f.washer.y + 0.3, 1.05],
  }
  return a
}

export function drainAnchors(house) {
  const L = LAYOUTS[house.layout_id]
  const f = L.fix
  const bathWallY = L.rooms.find(r => r.id === 'BATHROOM').rects[0][3]
  return {
    'B-FD': [f.floorDrain.x, f.floorDrain.y, -0.02],
    'B-BS': [f.basin.x, bathWallY - 0.25, 0.35],
    'B-WC': [f.toilet.x + 0.1, f.toilet.y, 0.05],
    'B-BR': [f.stack.x + 0.3, f.stack.y - 0.2, -0.14],
    'K-SK': [f.sink.x, f.sink.y, 0.4],
    'K-BR': [f.stack.x + 0.12, f.stack.y + 0.02, -0.14],
    'Y-FD': [f.washerDrain.x, f.washerDrain.y, -0.02],
    'Y-BR': [f.stack.x + 0.02, f.stack.y - 0.12, -0.14],
  }
}

function circuitEndpoints(house, suffix) {
  const L = LAYOUTS[house.layout_id]
  const f = L.fix
  const circuit = house.circuits.find(c => c.circuit_code.endsWith(`-${suffix}`))
  const rooms = circuit ? circuit.rooms : []
  switch (suffix) {
    case 'LT': return rooms.map(r => { const [x, y] = roomCenter(L, r); return [x, y, 2.82] })
    case 'SK': return rooms.map(r => { const room = L.rooms.find(x => x.id === r); if (!room) return null; const q = room.rects[0]; return [(q[0] + q[2]) / 2 + 0.6, q[1] + 0.12, 0.3] }).filter(Boolean)
    case 'KT': return [[f.sink.x + 0.15, (f.sink.y + f.stove.y) / 2, 1.15], [f.fridge.x, f.fridge.y + 0.3, 0.45]]
    case 'BT': return [[f.basin.x + 0.55, L.rooms.find(r => r.id === 'BATHROOM').rects[0][3] - 0.08, 1.3]]
    case 'WH': return [[f.heater.x, f.heater.y, 2.45]]
    case 'AC1':
    case 'AC2': {
      const ac = (DATA.layouts.find(l => l.layout_id === house.layout_id)?.air_conditioners || []).find(x => x.circuit === suffix)
      const p = ac && L.ac[ac.room]
      return p ? [[p.x, p.y, 2.45]] : []
    }
    default: return []
  }
}

export function panelAnchor(house) {
  const L = LAYOUTS[house.layout_id]
  return [L.fix.panel.x, L.D - 0.12, 1.65]
}

export function breakerAnchor(house, circuitCode) {
  const idx = Math.max(0, house.circuits.findIndex(c => c.circuit_code === circuitCode))
  const [x, y, h] = panelAnchor(house)
  const dir = SLOTS[parseHouseId(house.house_id).slot] ? 1 : 1
  return [x - 0.2 * dir + idx * 0.065, y - 0.05, h + 0.05]
}

// ---------------------------------------------------------------------------
// 路线：Manhattan 走线（先降到敷设高度，再沿 x、y 走，最后升到终点）
// ---------------------------------------------------------------------------
function manhattan(p, q, layH) {
  const pts = [p]
  if (Math.abs(p[2] - layH) > 1e-3) pts.push([p[0], p[1], layH])
  if (Math.abs(p[0] - q[0]) > 1e-3) pts.push([q[0], p[1], layH])
  if (Math.abs(p[1] - q[1]) > 1e-3) pts.push([q[0], q[1], layH])
  if (Math.abs(q[2] - layH) > 1e-3) pts.push(q)
  return dedupe(pts)
}
function dedupe(pts) {
  return pts.filter((p, i) => i === 0 || Math.hypot(p[0] - pts[i - 1][0], p[1] - pts[i - 1][1], p[2] - pts[i - 1][2]) > 1e-3)
}

const suffixOf = (code, houseId, prefix) => code.slice(`${prefix}-${houseId}-`.length)

export function supplyRoutes(house) {
  const A = supplyAnchors(house)
  const bySuffix = new Map(house.supply.map(s => [suffixOf(s.segment_code, house.house_id, 'WS'), s]))
  const out = []
  for (const seg of house.supply) {
    const sfx = suffixOf(seg.segment_code, house.house_id, 'WS')
    const end = A[sfx]
    if (!end) continue
    const parents = seg.parents.length ? seg.parents : []
    const routes = parents.length
      ? parents.map(pc => {
          const pS = suffixOf(pc, house.house_id, 'WS')
          const start = A[pS]
          if (!start || !bySuffix.has(pS)) return [end]
          const layH = sfx.startsWith('IN-') ? 0.55 : (seg.kind === 'HEATER' || sfx === 'WH-FLT' ? 2.2 : 0.22)
          return manhattan(start, end, Math.min(layH, Math.max(start[2], 0.22)))
        })
      : [[end]]
    out.push({ code: seg.segment_code, name: seg.name, kind: seg.kind, side: seg.side, area: seg.area, end, routes })
  }
  return out
}

export function drainRoutes(house) {
  const A = drainAnchors(house)
  const S = supplyAnchors(house)
  const L = LAYOUTS[house.layout_id]
  const stack = [L.fix.stack.x, L.fix.stack.y, -0.14]
  const FIX = { SHOWER: 'B-SH', BASIN: 'B-BS', TOILET: 'B-WC', KITCHEN_FAUCET: 'K-FC', WASHER: house.layout_id === 'T65' ? 'B-WT' : 'Y-WT' }
  const out = []
  for (const seg of house.drain) {
    const sfx = suffixOf(seg.segment_code, house.house_id, 'WD')
    const end = A[sfx]
    if (!end) continue
    const routes = []
    if (seg.kind === 'BRANCH') {
      for (const child of house.drain.filter(d => d.downstream === seg.segment_code)) {
        const c = A[suffixOf(child.segment_code, house.house_id, 'WD')]
        if (c) routes.push(manhattan(c, end, -0.14))
      }
      routes.push(manhattan(end, stack, -0.14))
    } else {
      for (const fx of seg.receives || []) {
        const s = S[FIX[fx]]
        if (s && fx !== 'SHOWER' && fx !== 'WASHER') routes.push(manhattan([s[0], s[1], Math.min(s[2], 0.8)], end, end[2]))
      }
      if (!routes.length) routes.push([end])
    }
    out.push({ code: seg.segment_code, name: seg.name, kind: seg.kind, area: seg.area, end, routes })
  }
  return out
}

export function circuitRoutes(house) {
  const panel = panelAnchor(house)
  return house.circuits.map((c, i) => {
    const sfx = suffixOf(c.circuit_code, house.house_id, 'CB')
    const start = breakerAnchor(house, c.circuit_code)
    const ends = circuitEndpoints(house, sfx)
    const layH = 2.62 + (i % 4) * 0.05
    return { code: c.circuit_code, name: c.name, rating: c.rating_a, start, ends, routes: ends.map(e => manhattan(start, e, layH)), panel }
  })
}

// ---------------------------------------------------------------------------
// 编码 → 目标
// ---------------------------------------------------------------------------
const SENSOR_ROOM = { B: 'BATHROOM', K: 'KITCHEN', L: 'LIVING', Y: 'BALCONY', WH: 'BATHROOM', IN: 'LIVING' }

function sensorAnchor(house, sensor) {
  const L = LAYOUTS[house.layout_id]
  const sup = supplyAnchors(house)
  const drn = drainAnchors(house)
  const t = sensor.target || ''
  let base = null
  if (t.startsWith('WS-')) base = sup[suffixOf(t, house.house_id, 'WS')]
  else if (t.startsWith('WD-')) base = drn[suffixOf(t, house.house_id, 'WD')]
  else if (t.startsWith('CB-')) {
    const e = circuitEndpoints(house, suffixOf(t, house.house_id, 'CB'))[0]
    base = e
  }
  const room = sensor.room || SENSOR_ROOM[sensor.sensor_code.split('-')[2]] || 'LIVING'
  const [cx, cy] = roomCenter(L, room)
  switch (sensor.type) {
    case 'WL': return base ? [base[0] + 0.15, base[1] + 0.1, 0.03] : [cx, cy, 0.03]
    case 'PS': return [cx, cy, 2.8]
    case 'TH': return base ? [base[0], base[1], 1.7] : [cx, cy, 1.7]
    case 'LV': return base ? [base[0] + 0.1, base[1], base[2] + 0.12] : [cx, cy, 0.1]
    default: return base ? [base[0] + 0.12, base[1] + 0.06, base[2] + 0.1] : [cx, cy, 1.2]
  }
}

function deviceAnchor(house, device) {
  const L = LAYOUTS[house.layout_id]
  if (device.segment_code) {
    const sfxS = suffixOf(device.segment_code, house.house_id, 'WS')
    const sup = supplyAnchors(house)[sfxS]
    if (device.segment_code.startsWith('WS-') && sup) return sup
    const drn = drainAnchors(house)[suffixOf(device.segment_code, house.house_id, 'WD')]
    if (drn) return drn
  }
  const role = device.role || ''
  if (role === 'K_SOCKET_1') return circuitEndpoints(house, 'KT')[0]
  if (role === 'K_SOCKET_2') return circuitEndpoints(house, 'KT')[1]
  if (role === 'B_SOCKET') return circuitEndpoints(house, 'BT')[0]
  if (role === 'L_LIGHT') { const [x, y] = roomCenter(L, 'LIVING'); return [x, y, 2.8] }
  if (role === 'L_AC1' || role === 'L_AC2') return circuitEndpoints(house, role.slice(2))[0]
  if (device.name && device.name.includes('入户门')) return [L.fix.entry.x - 1.3, L.D, 1.0]
  if (device.name && device.name.includes('阳台')) return [(L.rooms.find(r => r.id === 'BALCONY')?.rects[0][0] || 4) + 1.5, 0, 1.0]
  if (device.circuit_code) return circuitEndpoints(house, suffixOf(device.circuit_code, house.house_id, 'CB'))[0]
  const [x, y] = roomCenter(L, 'LIVING')
  return [x, y, 1]
}

function roomOfLocal(L, lx, ly) {
  for (const r of L.rooms) for (const q of r.rects) if (lx >= q[0] - 0.05 && lx <= q[2] + 0.05 && ly >= q[1] - 0.05 && ly <= q[3] + 0.05) return r.id
  return null
}

/**
 * 解析任意编码。buildingNo 默认 1。
 * 返回 { code, kind, buildingNo, houseId, floor, slot, room, local, world, name }；无法解析时返回 null。
 */
export function resolveCode(code, buildingNo = 1) {
  if (!code || !DATA) return null
  const fac = FACILITIES.find(f => (f.codes || []).includes(code))
  if (fac) return { code, kind: 'facility', facility: fac.id, name: fac.name, world: [fac.x, fac.h + 1, fac.z] }

  const st = /^ST0(\d)-F(\d+)-F(\d+)$/.exec(code)
  if (st) {
    const slot = `0${st[1]}`
    const a = Number(st[2]), b = Number(st[3])
    const L = LAYOUTS[SLOTS[slot].layout]
    const houseId = `${Math.max(a, 1)}${slot}`
    const [px, pz] = toPlate(slot, L.fix.stack.x, L.fix.stack.y)
    const bld = BUILDINGS.find(x => x.no === Number(buildingNo))
    const y0 = a === 0 ? -1.5 : floorBaseY(a) - 0.14
    const y1 = floorBaseY(b) - 0.14
    return { code, kind: 'stack', buildingNo, slot, floor: Math.max(a, 1), floorB: b, houseId, room: 'BATHROOM',
      name: `0${st[1]}号排水立管 ${a}–${b}层段`, world: [bld.x + px, (y0 + y1) / 2, bld.z + pz], y0, y1 }
  }

  const m = /^([A-Z]+)-(\d{3,4})-(.+)$/.exec(code)
  if (!m) return null
  const [, prefix, houseId, rest] = m
  const house = HOUSES.get(houseId)
  if (!house) return null
  const { floor, slot } = parseHouseId(houseId)
  const L = LAYOUTS[house.layout_id]
  let local = null, kind = 'part', name = code
  if (prefix === 'WS') {
    const seg = house.supply.find(s => s.segment_code === code)
    local = supplyAnchors(house)[rest]
    kind = 'supply'; name = seg?.name || code
  } else if (prefix === 'WD') {
    const seg = house.drain.find(s => s.segment_code === code)
    local = drainAnchors(house)[rest]
    kind = 'drain'; name = seg?.name || code
  } else if (prefix === 'CB') {
    const terminal = /-(OUT|IN)$/.exec(rest)
    const cc = terminal ? code.replace(/-(OUT|IN)$/, '') : code
    const c = house.circuits.find(x => x.circuit_code === cc)
    if (rest === 'MAIN') { local = panelAnchor(house); kind = 'panel'; name = '入户配电箱' }
    else if (terminal) { local = breakerAnchor(house, cc); kind = 'terminal'; name = `${c?.name || cc} ${terminal[1] === 'OUT' ? '出线' : '进线'}端子` }
    else { local = circuitEndpoints(house, rest)[0] || panelAnchor(house); kind = 'circuit'; name = c?.name || code }
  } else if (prefix === 'SN') {
    const s = house.sensors.find(x => x.sensor_code === code)
    if (s) { local = sensorAnchor(house, s); kind = 'sensor'; name = `${s.type} 传感器` }
  } else if (prefix === 'SPK') {
    const [x, y] = roomCenter(L, 'LIVING'); local = [x, y, 2.2]; kind = 'device'; name = '智能音箱'
  } else {
    const d = house.devices.find(x => x.device_code === code)
    if (d) { local = deviceAnchor(house, d); kind = 'device'; name = d.name }
  }
  if (!local) return null
  const room = (kind === 'terminal' || kind === 'panel') ? 'LIVING' : roomOfLocal(L, local[0], local[1]) || AREA_ROOM[rest.split('-')[0]] || 'LIVING'
  return { code, kind, buildingNo, houseId, floor, slot, room, local, name, world: localToWorld(buildingNo, houseId, ...local) }
}

export function houseTarget(houseId, buildingNo = 1) {
  const house = HOUSES.get(String(houseId))
  if (!house) return null
  const { floor, slot } = parseHouseId(houseId)
  const L = LAYOUTS[house.layout_id]
  return { kind: 'house', buildingNo, houseId: String(houseId), floor, slot, local: [L.W / 2, L.D / 2, 1.2],
    world: localToWorld(buildingNo, houseId, L.W / 2, L.D / 2, 1.2), name: `${houseId}室` }
}
