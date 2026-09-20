// 户型几何：3D 户内与 2D 平面图共用的唯一数据源。
//
// 户内局部坐标（米）：
//   lx ∈ [0, W]  沿面宽方向
//   ly ∈ [0, D]  ly = 0 为采光外立面，ly = D 为入户门所在的走廊一侧；阳台位于 ly < 0
//   h            距本层楼面的高度
// 户型几何为示意设计（档案只提供管线位置的文字描述），房间构成与 sim_building.json 的 rooms 一致。

export const ROOM_NAMES = {
  BEDROOM_MAIN: '主卧', BEDROOM_2: '次卧', BEDROOM_3: '书房', LIVING: '客餐厅',
  KITCHEN: '厨房', BATHROOM: '卫生间', BALCONY: '阳台', STORAGE: '储物间',
}

export const WALL_H = 2.9
export const EXT_T = 0.2
export const INT_T = 0.1

const T89 = {
  id: 'T89', W: 10.0, D: 9.0,
  rooms: [
    { id: 'BEDROOM_MAIN', rects: [[0, 0, 3.6, 4.2]] },
    { id: 'LIVING', rects: [[3.6, 0, 7.2, 4.2], [3.0, 4.2, 6.8, 9.0]] },
    { id: 'BEDROOM_2', rects: [[7.2, 0, 10, 4.2]] },
    { id: 'BATHROOM', rects: [[0, 4.2, 3.0, 6.4]] },
    { id: 'BEDROOM_3', rects: [[0, 6.4, 3.0, 9.0]] },
    { id: 'KITCHEN', rects: [[6.8, 4.2, 10, 9.0]] },
    { id: 'BALCONY', rects: [[3.6, -1.5, 7.2, 0]] },
  ],
  openings: [
    { a: 'h', at: 4.2, from: 3.6, to: 6.8, kind: 'open' },
    { a: 'h', at: 9.0, from: 4.2, to: 5.2, kind: 'entry' },
    { a: 'v', at: 3.6, from: 3.1, to: 4.0, kind: 'door' },
    { a: 'v', at: 7.2, from: 3.1, to: 4.0, kind: 'door' },
    { a: 'v', at: 3.0, from: 4.7, to: 5.5, kind: 'door' },
    { a: 'v', at: 3.0, from: 7.4, to: 8.2, kind: 'door' },
    { a: 'v', at: 6.8, from: 5.6, to: 7.0, kind: 'slide' },
    { a: 'h', at: 0, from: 4.0, to: 6.8, kind: 'slide' },
    { a: 'h', at: 0, from: 0.8, to: 2.8, kind: 'window' },
    { a: 'h', at: 0, from: 7.9, to: 9.4, kind: 'window' },
    { a: 'h', at: 9.0, from: 7.4, to: 9.4, kind: 'highwin' },
    { a: 'h', at: 9.0, from: 0.6, to: 2.4, kind: 'highwin' },
  ],
  fix: {
    entry: { x: 6.0 }, panel: { x: 3.55 },
    stack: { x: 0.14, y: 6.26 },
    shower: { x: 0.55, y: 4.72, box: [0, 4.2, 1.1, 5.25] }, floorDrain: { x: 0.85, y: 4.45 },
    toilet: { x: 0.36, y: 5.8 }, basin: { x: 1.75, y: 6.12 }, heater: { x: 1.75, y: 4.45 },
    sink: { x: 9.66, y: 6.1 }, stove: { x: 9.66, y: 8.2 }, fridge: { x: 7.25, y: 8.55 },
    washer: { x: 6.75, y: -1.05 }, washerDrain: { x: 6.2, y: -1.25 },
  },
  ac: { BEDROOM_MAIN: { x: 1.8, y: 4.08, wall: 'y' }, LIVING: { x: 7.08, y: 2.2, wall: 'x' } },
  outdoorAC: [{ x: 2.9, y: -0.45 }, { x: 3.95, y: -1.1 }],
  furniture: [
    { t: 'bed', x: 1.8, y: 2.7, w: 1.8, d: 2.0, head: 'y+' },
    { t: 'wardrobe', x: 0.3, y: 1.1, w: 0.6, d: 1.8 },
    { t: 'sofa', x: 5.4, y: 3.55, w: 2.4, d: 0.9, back: 'y+' },
    { t: 'tv', x: 5.4, y: 0.28, w: 1.8, d: 0.4 },
    { t: 'coffee', x: 5.4, y: 2.2, w: 1.1, d: 0.6 },
    { t: 'dining', x: 4.9, y: 6.6, w: 1.4, d: 0.85 },
    { t: 'bed', x: 8.6, y: 2.6, w: 1.5, d: 2.0, head: 'y+' },
    { t: 'desk', x: 9.6, y: 0.45, w: 0.8, d: 0.55 },
    { t: 'desk', x: 1.5, y: 8.55, w: 1.2, d: 0.6 },
    { t: 'bookcase', x: 0.2, y: 7.7, w: 0.35, d: 1.6 },
    { t: 'counter', x: 9.7, y: 6.6, w: 0.6, d: 4.8 },
    { t: 'counter', x: 8.4, y: 4.5, w: 2.6, d: 0.6 },
    { t: 'shoe', x: 3.3, y: 8.7, w: 0.6, d: 0.35 },
    { t: 'rack', x: 5.4, y: -1.2, w: 2.6, d: 0.1 },
  ],
}

const T75 = {
  id: 'T75', W: 9.0, D: 8.8,
  rooms: [
    { id: 'BEDROOM_MAIN', rects: [[0, 0, 3.4, 4.0]] },
    { id: 'LIVING', rects: [[3.4, 0, 9.0, 4.0], [2.8, 4.0, 5.8, 8.8]] },
    { id: 'BATHROOM', rects: [[0, 4.0, 2.8, 6.2]] },
    { id: 'BEDROOM_2', rects: [[0, 6.2, 2.8, 8.8]] },
    { id: 'KITCHEN', rects: [[5.8, 4.0, 9.0, 8.8]] },
    { id: 'BALCONY', rects: [[3.4, -1.5, 9.0, 0]] },
  ],
  openings: [
    { a: 'h', at: 4.0, from: 3.4, to: 5.8, kind: 'open' },
    { a: 'h', at: 8.8, from: 3.8, to: 4.8, kind: 'entry' },
    { a: 'v', at: 3.4, from: 2.9, to: 3.8, kind: 'door' },
    { a: 'v', at: 2.8, from: 4.6, to: 5.4, kind: 'door' },
    { a: 'v', at: 2.8, from: 7.2, to: 8.0, kind: 'door' },
    { a: 'v', at: 5.8, from: 5.4, to: 6.8, kind: 'slide' },
    { a: 'h', at: 0, from: 4.2, to: 8.2, kind: 'slide' },
    { a: 'h', at: 0, from: 0.7, to: 2.7, kind: 'window' },
    { a: 'v', at: 9.0, from: 5.2, to: 7.4, kind: 'window' },
    { a: 'v', at: 9.0, from: 1.0, to: 3.2, kind: 'window' },
    { a: 'h', at: 8.8, from: 0.5, to: 2.2, kind: 'highwin' },
  ],
  fix: {
    entry: { x: 5.1 }, panel: { x: 3.15 },
    stack: { x: 0.14, y: 6.06 },
    shower: { x: 0.55, y: 4.52, box: [0, 4.0, 1.1, 5.05] }, floorDrain: { x: 0.85, y: 4.25 },
    toilet: { x: 0.36, y: 5.6 }, basin: { x: 1.65, y: 5.92 }, heater: { x: 1.65, y: 4.25 },
    sink: { x: 8.66, y: 6.3 }, stove: { x: 8.66, y: 8.05 }, fridge: { x: 6.25, y: 8.35 },
    washer: { x: 8.5, y: -1.05 }, washerDrain: { x: 7.95, y: -1.25 },
  },
  ac: { BEDROOM_MAIN: { x: 1.7, y: 3.88, wall: 'y' }, LIVING: { x: 8.88, y: 3.5, wall: 'x' } },
  outdoorAC: [{ x: 2.8, y: -0.45 }, { x: 3.75, y: -1.1 }],
  furniture: [
    { t: 'bed', x: 1.7, y: 2.5, w: 1.8, d: 2.0, head: 'y+' },
    { t: 'wardrobe', x: 0.3, y: 0.95, w: 0.6, d: 1.6 },
    { t: 'sofa', x: 6.2, y: 3.45, w: 2.6, d: 0.9, back: 'y+' },
    { t: 'tv', x: 6.2, y: 0.28, w: 1.8, d: 0.4 },
    { t: 'coffee', x: 6.2, y: 2.1, w: 1.1, d: 0.6 },
    { t: 'dining', x: 4.3, y: 6.2, w: 1.2, d: 0.8 },
    { t: 'bed', x: 1.45, y: 7.7, w: 1.2, d: 2.0, head: 'x-' },
    { t: 'counter', x: 8.7, y: 6.4, w: 0.6, d: 4.8 },
    { t: 'counter', x: 7.4, y: 4.3, w: 2.6, d: 0.6 },
    { t: 'shoe', x: 3.1, y: 8.5, w: 0.5, d: 0.35 },
    { t: 'rack', x: 6.0, y: -1.2, w: 3.0, d: 0.1 },
  ],
}

const T65 = {
  id: 'T65', W: 8.4, D: 8.0,
  rooms: [
    { id: 'BEDROOM_MAIN', rects: [[0, 0, 3.1, 3.8]] },
    { id: 'LIVING', rects: [[3.1, 0, 5.9, 3.8], [2.6, 3.8, 5.2, 8.0]] },
    { id: 'BEDROOM_2', rects: [[5.9, 0, 8.4, 3.8]] },
    { id: 'BATHROOM', rects: [[0, 3.8, 2.6, 6.2]] },
    { id: 'STORAGE', rects: [[0, 6.2, 2.6, 8.0]] },
    { id: 'KITCHEN', rects: [[5.2, 3.8, 8.4, 8.0]] },
  ],
  openings: [
    { a: 'h', at: 3.8, from: 3.1, to: 5.2, kind: 'open' },
    { a: 'h', at: 8.0, from: 3.4, to: 4.4, kind: 'entry' },
    { a: 'v', at: 3.1, from: 2.8, to: 3.65, kind: 'door' },
    { a: 'v', at: 5.9, from: 2.8, to: 3.65, kind: 'door' },
    { a: 'v', at: 2.6, from: 4.4, to: 5.2, kind: 'door' },
    { a: 'v', at: 2.6, from: 6.8, to: 7.6, kind: 'door' },
    { a: 'v', at: 5.2, from: 5.2, to: 6.5, kind: 'slide' },
    { a: 'h', at: 0, from: 0.6, to: 2.5, kind: 'window' },
    { a: 'h', at: 0, from: 3.5, to: 5.5, kind: 'window' },
    { a: 'h', at: 0, from: 6.3, to: 8.0, kind: 'window' },
    { a: 'v', at: 0, from: 4.4, to: 5.4, kind: 'highwin' },
    { a: 'h', at: 8.0, from: 6.4, to: 7.9, kind: 'highwin' },
  ],
  fix: {
    entry: { x: 4.75 }, panel: { x: 2.9 },
    stack: { x: 0.14, y: 6.06 },
    shower: { x: 0.55, y: 4.32, box: [0, 3.8, 1.1, 4.85] }, floorDrain: { x: 0.85, y: 4.05 },
    toilet: { x: 0.36, y: 5.45 }, basin: { x: 1.2, y: 5.92 }, heater: { x: 1.4, y: 4.05 },
    sink: { x: 8.06, y: 5.0 }, stove: { x: 8.06, y: 7.2 }, fridge: { x: 5.65, y: 7.55 },
    washer: { x: 2.12, y: 5.82 }, washerDrain: { x: 1.7, y: 5.55 },
  },
  ac: { BEDROOM_MAIN: { x: 1.6, y: 3.68, wall: 'y' }, LIVING: { x: 4.5, y: 3.68, wall: 'y' } },
  outdoorAC: [{ x: 2.8, y: -0.45 }, { x: 6.0, y: -0.45 }],
  furniture: [
    { t: 'bed', x: 1.55, y: 2.3, w: 1.8, d: 2.0, head: 'y+' },
    { t: 'sofa', x: 4.5, y: 3.2, w: 2.2, d: 0.85, back: 'y+' },
    { t: 'tv', x: 4.5, y: 0.28, w: 1.6, d: 0.4 },
    { t: 'coffee', x: 4.5, y: 1.9, w: 0.9, d: 0.55 },
    { t: 'dining', x: 3.9, y: 6.6, w: 1.1, d: 0.75 },
    { t: 'bed', x: 7.15, y: 2.45, w: 1.2, d: 2.0, head: 'y+' },
    { t: 'counter', x: 8.1, y: 5.9, w: 0.6, d: 4.2 },
    { t: 'bookcase', x: 0.3, y: 7.1, w: 0.5, d: 1.6 },
    { t: 'shoe', x: 2.95, y: 7.7, w: 0.5, d: 0.35 },
  ],
}

export const LAYOUTS = { T89, T75, T65 }

// ---------------------------------------------------------------------------
// 标准层：一梯六户（楼栋局部坐标：x 向东，z 向南，楼面 y = 0）
// 南排 04·01·02·03 外立面在 z = +10；北排 06·[核心筒]·05 外立面在 z = -9；中间走廊 z ∈ [-1, 1]
// ---------------------------------------------------------------------------
export const PLATE = { minX: -19, maxX: 19, southZ: 10, northZ: -9, corridor: [-1, 1] }

export const SLOTS = {
  '04': { layout: 'T75', x0: -19, south: true, flip: true },
  '01': { layout: 'T89', x0: -10, south: true, flip: true },
  '02': { layout: 'T89', x0: 0, south: true, flip: false },
  '03': { layout: 'T75', x0: 10, south: true, flip: false },
  '06': { layout: 'T65', x0: -19, south: false, flip: false },
  '05': { layout: 'T65', x0: 10.6, south: false, flip: true },
}

export const CORE = { x0: -10.6, x1: 10.6, z0: -9, z1: -1 }

/** 户内局部坐标 → 楼栋局部坐标 (x, z) */
export function toPlate(slotId, lx, ly) {
  const s = SLOTS[slotId]
  const L = LAYOUTS[s.layout]
  const x = s.x0 + (s.flip ? L.W - lx : lx)
  const z = s.south ? PLATE.southZ - ly : PLATE.northZ + ly
  return [x, z]
}

/** 户内局部矩形 → 楼栋局部轴对齐矩形 */
export function rectToPlate(slotId, x0, y0, x1, y1) {
  const [ax, az] = toPlate(slotId, x0, y0)
  const [bx, bz] = toPlate(slotId, x1, y1)
  return { minX: Math.min(ax, bx), maxX: Math.max(ax, bx), minZ: Math.min(az, bz), maxZ: Math.max(az, bz) }
}

export function slotBounds(slotId) {
  const L = LAYOUTS[SLOTS[slotId].layout]
  const minY = L.rooms.some(r => r.id === 'BALCONY') ? -1.5 : 0
  return rectToPlate(slotId, 0, minY, L.W, L.D)
}

export function roomCenter(layout, roomId) {
  const room = layout.rooms.find(r => r.id === roomId)
  if (!room) return [layout.W / 2, layout.D / 2]
  // 取面积最大的矩形中心
  const r = [...room.rects].sort((a, b) => (b[2] - b[0]) * (b[3] - b[1]) - (a[2] - a[0]) * (a[3] - a[1]))[0]
  return [(r[0] + r[2]) / 2, (r[1] + r[3]) / 2]
}

// ---------------------------------------------------------------------------
// 墙体生成：由房间矩形边合并，扣除门窗洞口
// ---------------------------------------------------------------------------
const key = (v) => Math.round(v * 1000) / 1000

function mergeIntervals(list) {
  const s = [...list].sort((a, b) => a[0] - b[0])
  const out = []
  for (const [a, b] of s) {
    if (out.length && a <= out[out.length - 1][1] + 1e-6) out[out.length - 1][1] = Math.max(out[out.length - 1][1], b)
    else out.push([a, b])
  }
  return out
}

function subtract(intervals, a, b) {
  const out = []
  for (const [x, y] of intervals) {
    if (b <= x || a >= y) { out.push([x, y]); continue }
    if (a > x) out.push([x, a])
    if (b < y) out.push([b, y])
  }
  return out
}

const OPENING_SPEC = {
  door: { gap: [0, 2.1] },
  entry: { gap: [0, 2.1] },
  slide: { gap: [0, 2.3] },
  window: { gap: [0.9, 2.4] },
  highwin: { gap: [1.6, 2.3] },
}

/**
 * 返回 { walls, glass, doors, railings }
 * walls:   { a, at, from, to, y0, y1, ext }
 * glass:   { a, at, from, to, y0, y1 }
 * doors:   { a, at, from, to, kind }
 */
export function buildWalls(layout) {
  const lines = new Map()
  const railings = []
  const add = (a, at, from, to) => {
    const k = `${a}:${key(at)}`
    if (!lines.has(k)) lines.set(k, [])
    lines.get(k).push([Math.min(from, to), Math.max(from, to)])
  }
  for (const room of layout.rooms) {
    for (const [x0, y0, x1, y1] of room.rects) {
      if (room.id === 'BALCONY') {
        railings.push({ a: 'h', at: y0, from: x0, to: x1 })
        railings.push({ a: 'v', at: x0, from: y0, to: y1 })
        railings.push({ a: 'v', at: x1, from: y0, to: y1 })
        continue
      }
      add('h', y0, x0, x1); add('h', y1, x0, x1); add('v', x0, y0, y1); add('v', x1, y0, y1)
    }
  }
  const walls = []
  const glass = []
  const doors = []
  for (const [k, raw] of lines) {
    const [a, atStr] = k.split(':')
    const at = Number(atStr)
    let full = mergeIntervals(raw)
    const ext = (a === 'h' && (at === 0 || at === key(layout.D))) || (a === 'v' && (at === 0 || at === key(layout.W)))
    const ops = layout.openings.filter(o => o.a === a && key(o.at) === at)
    for (const o of ops) {
      full = subtract(full, o.from, o.to)
      if (o.kind === 'open') continue
      const [g0, g1] = OPENING_SPEC[o.kind].gap
      if (g0 > 0) walls.push({ a, at, from: o.from, to: o.to, y0: 0, y1: g0, ext })
      walls.push({ a, at, from: o.from, to: o.to, y0: g1, y1: WALL_H, ext })
      if (o.kind === 'window' || o.kind === 'highwin') glass.push({ a, at, from: o.from, to: o.to, y0: g0, y1: g1, ext })
      else if (o.kind === 'slide') glass.push({ a, at, from: o.from, to: o.to, y0: 0.05, y1: g1, ext, slide: true })
      else doors.push({ a, at, from: o.from, to: o.to, kind: o.kind })
    }
    for (const [from, to] of full) {
      if (to - from > 1e-3) walls.push({ a, at, from, to, y0: 0, y1: WALL_H, ext })
    }
  }
  return { walls, glass, doors, railings }
}

/** 某户位的外立面构件（用于楼栋外壳）：只保留落在标准层外轮廓上的墙、窗、阳台 */
export function isPlateBoundary(slotId, wall) {
  const s = SLOTS[slotId]
  const L = LAYOUTS[s.layout]
  if (wall.a === 'h') return wall.at === 0 || (key(wall.at) === key(L.D) && false)
  // 竖墙：只有落在楼栋东西两端的才算外立面
  const [px] = toPlate(slotId, wall.at, 0)
  return Math.abs(px - PLATE.minX) < 1e-3 || Math.abs(px - PLATE.maxX) < 1e-3
}
