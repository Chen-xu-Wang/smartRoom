<template>
  <div class="plan panel">
    <div class="plan-head">
      <strong>{{ title }}</strong>
      <span class="sub">{{ subtitle }}</span>
      <span class="grow"></span>
      <el-checkbox v-if="houseId" v-model="showMep" size="small">管线</el-checkbox>
    </div>
    <svg :viewBox="viewBox" class="svg" preserveAspectRatio="xMidYMid meet">
      <defs>
        <pattern id="hatch" width="0.3" height="0.3" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <line x1="0" y1="0" x2="0" y2="0.3" stroke="#b9c2cc" stroke-width="0.06" />
        </pattern>
      </defs>

      <!-- 楼层总图 -->
      <template v-if="!houseId">
        <rect :x="PLATE.minX" :y="-1" :width="PLATE.maxX - PLATE.minX" height="2" class="corridor" />
        <rect :x="CORE.x0" :y="CORE.z0" :width="CORE.x1 - CORE.x0" :height="CORE.z1 - CORE.z0" fill="url(#hatch)" class="core" />
        <text :x="0" :y="-5" class="core-label">核心筒 · 电梯厅</text>
        <g v-for="u in floorUnits" :key="u.houseId" class="unit" :class="{ alert: u.alert, related: u.related }" @click="emit('house', u.houseId)">
          <rect v-for="(r, i) in u.rooms" :key="i" :x="r.minX" :y="r.minZ" :width="r.maxX - r.minX" :height="r.maxZ - r.minZ" :fill="roomFill(r.id)" class="room" />
          <rect v-for="(w, i) in u.walls" :key="'w' + i" :x="w.minX" :y="w.minZ" :width="w.maxX - w.minX" :height="w.maxZ - w.minZ" class="wall" />
          <rect :x="u.bb.minX" :y="u.bb.minZ" :width="u.bb.maxX - u.bb.minX" :height="u.bb.maxZ - u.bb.minZ" class="unit-outline" />
          <text :x="(u.bb.minX + u.bb.maxX) / 2" :y="(u.bb.minZ + u.bb.maxZ) / 2" class="unit-label">{{ u.houseId }}</text>
          <text :x="(u.bb.minX + u.bb.maxX) / 2" :y="(u.bb.minZ + u.bb.maxZ) / 2 + 1.3" class="unit-sub">{{ u.layout }}</text>
        </g>
        <g v-for="h in floorHotspots" :key="h.code" class="hotspot primary" @click.stop="emit('code', h.code)">
          <circle :cx="h.x" :cy="h.y" r="1.1" class="ring" />
          <circle :cx="h.x" :cy="h.y" r="0.45" class="core-dot" />
          <text :x="h.x + 1.3" :y="h.y - 0.8" class="hot-label big">{{ h.label }}</text>
        </g>
      </template>

      <!-- 户型平面 -->
      <template v-else-if="unit">
        <g v-for="r in unit.rooms" :key="r.key" class="room-g" :class="{ hot: r.id === hotRoom }" @click="emit('room', r.id)">
          <rect :x="r.minX" :y="r.minZ" :width="r.maxX - r.minX" :height="r.maxZ - r.minZ" :fill="roomFill(r.id)" class="room" />
        </g>
        <text v-for="r in unit.roomLabels" :key="'l' + r.id" :x="r.x" :y="r.y" class="room-label">{{ r.name }}</text>
        <g class="furn">
          <rect v-for="(f, i) in unit.furniture" :key="'f' + i" :x="f.minX" :y="f.minZ" :width="f.maxX - f.minX" :height="f.maxZ - f.minZ" />
        </g>
        <rect v-for="(w, i) in unit.walls" :key="'w' + i" :x="w.minX" :y="w.minZ" :width="w.maxX - w.minX" :height="w.maxZ - w.minZ" class="wall" />
        <rect v-for="(g, i) in unit.glass" :key="'g' + i" :x="g.minX" :y="g.minZ" :width="g.maxX - g.minX" :height="g.maxZ - g.minZ" class="window" />
        <polyline v-for="(d, i) in unit.doors" :key="'d' + i" :points="d" class="door" />
        <g v-if="showMep">
          <polyline v-for="p in unit.supply" :key="p.key" :points="p.points" :class="['pipe', p.side]" />
          <polyline v-for="p in unit.drain" :key="p.key" :points="p.points" class="pipe drain" />
          <polyline v-for="p in unit.circuits" :key="p.key" :points="p.points" class="pipe circuit" />
          <circle v-for="s in unit.sensors" :key="s.code" :cx="s.x" :cy="s.y" r="0.12" class="sensor" @click.stop="emit('code', s.code)" />
        </g>
        <g v-for="f in unit.fixtures" :key="f.code" class="fixture" :class="{ sel: f.code === selectedCode }" @click.stop="emit('code', f.code)">
          <rect :x="f.x - f.w / 2" :y="f.y - f.h / 2" :width="f.w" :height="f.h" :rx="f.round ? f.w / 2 : 0.05" />
        </g>
        <!-- 问题部位 -->
        <g v-for="h in hotspots" :key="h.code + h.cls" :class="['hotspot', h.cls]" @click.stop="emit('code', h.code)">
          <circle :cx="h.x" :cy="h.y" r="0.45" class="ring" />
          <circle :cx="h.x" :cy="h.y" r="0.18" class="core-dot" />
          <text v-if="h.label" :x="h.x + 0.55" :y="h.y - 0.35" class="hot-label">{{ h.label }}</text>
        </g>
      </template>

      <!-- 指北针 -->
      <g :transform="`translate(${vb.x + vb.w - 1.4} ${vb.y + 1.6})`" class="compass">
        <circle r="0.9" />
        <path d="M0 -0.75 L0.3 0.2 L0 0 L-0.3 0.2 Z" />
        <text y="-1.05">N</text>
      </g>
    </svg>
    <div class="legend sub">
      <span><i class="lg cold"></i>冷水</span><span><i class="lg hot"></i>热水</span><span><i class="lg drain"></i>排水</span>
      <span><i class="lg circuit"></i>电气</span><span><i class="lg alert"></i>问题部位</span>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { LAYOUTS, SLOTS, PLATE, CORE, buildWalls, rectToPlate, toPlate, slotBounds, roomCenter, ROOM_NAMES, EXT_T, INT_T } from '../data/layouts'
import { houseById, supplyRoutes, drainRoutes, circuitRoutes, resolveCode, parseHouseId } from '../data/resolver'

const props = defineProps({
  floor: { type: Number, default: null },
  houseId: { type: String, default: null },
  selectedCode: { type: String, default: null },
  targets: { type: Object, default: null },
  alertHouses: { type: Array, default: () => [] },
})
const emit = defineEmits(['house', 'room', 'code'])
const showMep = ref(true)

const FILL = { BEDROOM_MAIN: '#f0dcc0', BEDROOM_2: '#f0dcc0', BEDROOM_3: '#ecd9bf', LIVING: '#f6ead6', KITCHEN: '#dfe7e3', BATHROOM: '#d8e6ee', BALCONY: '#e5e1d8', STORAGE: '#e6e1d6' }
const roomFill = (id) => FILL[id] || '#eee'

const house = computed(() => (props.houseId ? houseById(props.houseId) : null))
const title = computed(() => props.houseId ? `${props.houseId} 户型平面图` : `${props.floor || ''} 层平面图`)
const subtitle = computed(() => house.value ? `${house.value.layout} · ${house.value.area_m2}㎡ · ${house.value.batch_id} 批次` : '一梯六户 · 点击住户进入')

const vb = computed(() => {
  if (props.houseId) {
    const { slot } = parseHouseId(props.houseId)
    const b = slotBounds(slot)
    return { x: b.minX - 1.2, y: b.minZ - 1.2, w: b.maxX - b.minX + 2.4, h: b.maxZ - b.minZ + 2.4 }
  }
  return { x: PLATE.minX - 1.5, y: PLATE.northZ - 2.5, w: PLATE.maxX - PLATE.minX + 3, h: PLATE.southZ - PLATE.northZ + 4.5 }
})
const viewBox = computed(() => `${vb.value.x} ${vb.value.y} ${vb.value.w} ${vb.value.h}`)

function wallRects(slot, L) {
  const { walls, glass, doors } = buildWalls(L)
  const full = walls.filter(w => w.y0 === 0).map(w => {
    const t = w.ext ? EXT_T : INT_T
    return w.a === 'h' ? rectToPlate(slot, w.from, w.at - t / 2, w.to, w.at + t / 2) : rectToPlate(slot, w.at - t / 2, w.from, w.at + t / 2, w.to)
  })
  const gl = glass.map(g => g.a === 'h' ? rectToPlate(slot, g.from, g.at - 0.06, g.to, g.at + 0.06) : rectToPlate(slot, g.at - 0.06, g.from, g.at + 0.06, g.to))
  const dr = doors.filter(d => d.kind !== 'entry' || true).map(d => {
    const w = d.to - d.from
    const pts = []
    for (let i = 0; i <= 8; i++) {
      const a = (i / 8) * Math.PI / 2
      let lx, ly
      if (d.a === 'v') { const dir = d.at < L.W / 2 ? 1 : -1; lx = d.at + dir * w * Math.sin(a); ly = d.from + w * Math.cos(a) }
      else { lx = d.from + w * Math.cos(a); ly = d.at + w * Math.sin(a) * (d.kind === 'entry' ? -1 : 1) }
      pts.push(toPlate(slot, lx, ly))
    }
    const hinge = d.a === 'v' ? toPlate(slot, d.at, d.from) : toPlate(slot, d.from, d.at)
    return [hinge, ...pts, hinge].map(p => p.join(',')).join(' ')
  })
  return { full, gl, dr }
}

const floorUnits = computed(() => {
  if (!props.floor) return []
  return Object.entries(SLOTS).map(([slot, s]) => {
    const L = LAYOUTS[s.layout]
    const houseId = `${props.floor}${slot}`
    const rooms = L.rooms.flatMap(r => r.rects.map(q => ({ id: r.id, ...rectToPlate(slot, ...q) })))
    const { full } = wallRects(slot, L)
    return {
      houseId, layout: houseById(houseId)?.layout || s.layout, rooms, walls: full, bb: slotBounds(slot),
      alert: props.alertHouses.includes(houseId) || props.targets?.houseId === houseId,
      related: (props.targets?.related || []).includes(houseId),
    }
  })
})

const FIX_SIZE = {
  B_TOILET: [0.45, 0.65, true], B_BASIN: [0.8, 0.45], B_SHOWER: [0.9, 0.9], B_FLOOR_DRAIN: [0.2, 0.2, true], B_HEATER: [0.8, 0.35],
  K_SINK: [0.5, 0.7], L_AC1: [0.9, 0.22], L_AC2: [0.9, 0.22],
}

const unit = computed(() => {
  const h = house.value
  if (!h) return null
  const { slot } = parseHouseId(h.house_id)
  const L = LAYOUTS[h.layout_id]
  const rooms = L.rooms.flatMap(r => r.rects.map((q, i) => ({ key: `${r.id}${i}`, id: r.id, ...rectToPlate(slot, ...q) })))
  const roomLabels = L.rooms.map(r => { const [x, y] = roomCenter(L, r.id); const [px, pz] = toPlate(slot, x, y); return { id: r.id, name: ROOM_NAMES[r.id], x: px, y: pz } })
  const { full, gl, dr } = wallRects(slot, L)
  const furniture = L.furniture.map(f => rectToPlate(slot, f.x - f.w / 2, f.y - f.d / 2, f.x + f.w / 2, f.y + f.d / 2))
  const pl = (pts) => pts.map(p => { const [x, z] = toPlate(slot, p[0], p[1]); return `${x},${z}` }).join(' ')
  const supply = supplyRoutes(h).flatMap(s => s.routes.filter(r => r.length > 1).map((r, i) => ({ key: s.code + i, side: s.side === 'HOT' ? 'hot' : 'cold', points: pl(r) })))
  const drain = drainRoutes(h).flatMap(s => s.routes.filter(r => r.length > 1).map((r, i) => ({ key: s.code + i, points: pl(r) })))
  const circuits = circuitRoutes(h).flatMap(c => c.routes.map((r, i) => ({ key: c.code + i, points: pl(r) })))
  const sensors = h.sensors.map(s => { const r = resolveCode(s.sensor_code); if (!r) return null; const [x, y] = toPlate(slot, r.local[0], r.local[1]); return { code: s.sensor_code, x, y } }).filter(Boolean)
  const fixtures = h.devices.filter(d => FIX_SIZE[d.role]).map(d => {
    const r = resolveCode(d.device_code)
    if (!r) return null
    const [x, y] = toPlate(slot, r.local[0], r.local[1])
    const [w, hh, round] = FIX_SIZE[d.role]
    return { code: d.device_code, x, y, w, h: hh, round }
  }).filter(Boolean)
  return { rooms, roomLabels, walls: full, glass: gl, doors: dr, furniture, supply, drain, circuits, sensors, fixtures }
})

const hotspots = computed(() => {
  const t = props.targets
  const h = house.value
  if (!h) return []
  const out = []
  const add = (code, cls, label) => {
    const r = resolveCode(code)
    if (!r || r.houseId !== h.house_id) return
    const [x, y] = toPlate(r.slot, r.local[0], r.local[1])
    out.push({ code, cls, x, y, label })
  }
  if (t && t.houseId === h.house_id) {
    if (t.primary) add(t.primary, 'primary', resolveCode(t.primary)?.name)
    t.secondary.forEach(c => add(c, 'secondary'))
    t.sensors.forEach(c => add(c, 'sensor'))
  }
  if (props.selectedCode && props.selectedCode !== t?.primary) add(props.selectedCode, 'selected')
  return out
})

// 楼层总图上的问题点：立管段、或本层住户的首选部位
const floorHotspots = computed(() => {
  const t = props.targets
  if (props.houseId || !t?.primary) return []
  const r = resolveCode(t.primary)
  if (!r) return []
  if (r.kind === 'stack') {
    const L = LAYOUTS[SLOTS[r.slot].layout]
    const [x, y] = toPlate(r.slot, L.fix.stack.x, L.fix.stack.y)
    return [{ code: t.primary, x, y, label: r.name }]
  }
  if (r.floor !== props.floor || !r.local) return []
  const [x, y] = toPlate(r.slot, r.local[0], r.local[1])
  return [{ code: t.primary, x, y, label: r.name }]
})

const hotRoom = computed(() => {
  const t = props.targets
  if (!t?.primary || t.houseId !== props.houseId) return null
  return resolveCode(t.primary)?.room || null
})
</script>

<style scoped>
.plan { display: flex; flex-direction: column; padding: 10px 12px; min-height: 0; }
.plan-head { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; font-size: 13px; }
.grow { flex: 1; }
.svg { flex: 1; min-height: 0; width: 100%; background: rgba(255, 255, 255, 0.55); border-radius: 8px; }
:root[data-theme='night'] .svg { background: rgba(10, 30, 60, 0.6); }
.room { stroke: none; cursor: pointer; }
.room-g:hover .room { filter: brightness(0.95); }
.room-g.hot .room { fill: #ffccc7; animation: blink 1s infinite; }
.wall { fill: #4a5563; }
.window { fill: #8fd0ff; stroke: #3c8cc8; stroke-width: 0.03; }
.door { fill: rgba(184, 138, 90, 0.12); stroke: #b88a5a; stroke-width: 0.04; }
.furn rect { fill: rgba(140, 120, 100, 0.18); stroke: rgba(120, 100, 80, 0.45); stroke-width: 0.03; }
.room-label { font-size: 0.42px; fill: #3b4a5a; text-anchor: middle; pointer-events: none; font-weight: 600; }
.corridor { fill: #e9e5dc; }
.core { stroke: #8994a0; stroke-width: 0.06; }
.core-label { font-size: 0.8px; text-anchor: middle; fill: #5b6b7c; }
.unit { cursor: pointer; }
.unit-outline { fill: transparent; stroke: #1677ff; stroke-width: 0; }
.unit:hover .unit-outline { stroke-width: 0.25; fill: rgba(22, 119, 255, 0.08); }
.unit.alert .unit-outline { stroke: #f5222d; stroke-width: 0.35; fill: rgba(245, 34, 45, 0.15); animation: blink 1s infinite; }
.unit.related .unit-outline { stroke: #fa8c16; stroke-width: 0.25; fill: rgba(250, 140, 22, 0.12); }
.unit-label { font-size: 1.3px; font-weight: 700; text-anchor: middle; fill: #1f2d3d; pointer-events: none; }
.unit-sub { font-size: 0.7px; text-anchor: middle; fill: #5b6b7c; pointer-events: none; }
.pipe { fill: none; stroke-width: 0.06; }
.pipe.cold { stroke: #2f7fe0; }
.pipe.hot { stroke: #e2483b; }
.pipe.drain { stroke: #7a7f86; stroke-width: 0.09; stroke-dasharray: 0.25 0.12; }
.pipe.circuit { stroke: #f1b21b; stroke-width: 0.04; stroke-dasharray: 0.15 0.1; }
.sensor { fill: #13c2c2; stroke: #fff; stroke-width: 0.03; cursor: pointer; }
.fixture rect { fill: #ffffff; stroke: #6b7680; stroke-width: 0.04; cursor: pointer; }
.fixture.sel rect { stroke: #1677ff; stroke-width: 0.1; }
.hotspot { cursor: pointer; }
.hotspot .ring { fill: none; stroke-width: 0.1; transform-box: fill-box; transform-origin: center; animation: pulse 0.9s infinite; }
.hotspot.primary .ring { stroke: #f5222d; }
.hotspot.primary .core-dot { fill: #f5222d; animation: blink 0.8s infinite; }
.hotspot.secondary .ring { stroke: #fadb14; }
.hotspot.secondary .core-dot { fill: #fadb14; }
.hotspot.sensor .ring { stroke: #13c2c2; }
.hotspot.sensor .core-dot { fill: #13c2c2; }
.hotspot.selected .ring { stroke: #1677ff; }
.hotspot.selected .core-dot { fill: #1677ff; }
.hot-label.big { font-size: 1px; stroke-width: 0.18px; }
.hot-label { font-size: 0.42px; fill: #cf1322; font-weight: 700; paint-order: stroke; stroke: #fff; stroke-width: 0.08px; }
.compass circle { fill: rgba(255, 255, 255, 0.8); stroke: #8994a0; stroke-width: 0.05; }
.compass path { fill: #f5222d; }
.compass text { font-size: 0.6px; text-anchor: middle; fill: #1f2d3d; font-weight: 700; }
.legend { display: flex; gap: 10px; margin-top: 4px; flex-wrap: wrap; }
.lg { display: inline-block; width: 14px; height: 3px; margin-right: 3px; vertical-align: middle; }
.lg.cold { background: #2f7fe0; } .lg.hot { background: #e2483b; } .lg.drain { background: #7a7f86; } .lg.circuit { background: #f1b21b; } .lg.alert { background: #f5222d; border-radius: 50%; width: 8px; height: 8px; }
</style>
