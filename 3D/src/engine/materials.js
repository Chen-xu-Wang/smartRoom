// 材质库：白天沙盘风 / 夜间科技风两套配色，切换主题时原地修改材质属性。
import * as THREE from 'three'

const PALETTE = {
  day: {
    background: 0xdfe8f0, fog: 0xdfe8f0,
    ground: 0xcfd8c4, grass: 0x9fc27e, grassDark: 0x7fab63, road: 0x8d949b, roadLine: 0xf4f4ef, sidewalk: 0xd9d2c3,
    plaza: 0xe6dfd1, water: 0x6fb7d9, fence: 0x55606a,
    wall: 0xf3efe6, wallAlt: 0xe4dccd, slab: 0xfbfaf7, slabEdge: 0xc9c2b4, seam: 0x9f978a, core: 0xe8e4dc,
    glass: 0x8fb8d4, frame: 0x6b7680, railing: 0xa9cde0, acUnit: 0xf0f0ee, roof: 0xd5d0c6, solar: 0x2c4f7c,
    trunk: 0x7a5a3c, leaf: 0x6ea65a, leaf2: 0x4f8f4a, hedge: 0x5d9a52,
    carBody: 0xffffff, carGlass: 0x3b4a58, lamp: 0x5b6670, lampHead: 0xfff6d8,
    floorLiving: 0xe8d6bb, floorBed: 0xd9b98f, floorWet: 0xd3dde2, floorKitchen: 0xdfe3e0, floorBalcony: 0xcfcac0, floorStorage: 0xd8d3c8,
    intWall: 0xfdfbf6, door: 0xb88a5a, furniture: 0xcfc4b3, fabric: 0x8fa3b5, fabric2: 0xc9a27e, wood: 0xa7825b,
    ceramic: 0xffffff, metal: 0xb8bec4, appliance: 0xe9ecee, counter: 0x6f757c,
    cold: 0x2f7fe0, hot: 0xe2483b, drain: 0x7a7f86, stack: 0x5f666e, circuit: 0xf1b21b, panel: 0x9aa4ad, sensor: 0x16b5a8,
    service: 0xe9d9bf, utility: 0xbfc6cc, canopy: 0x5b8fbf, parcel: 0x2f9e6b, court: 0xc0704f, courtLine: 0xffffff, play: 0xe98e3a,
    label: '#1f2d3d',
  },
  night: {
    background: 0x050b18, fog: 0x050b18,
    ground: 0x0a1426, grass: 0x0e2233, grassDark: 0x0b1c2b, road: 0x121c2c, roadLine: 0x2a6ea8, sidewalk: 0x15213a,
    plaza: 0x132038, water: 0x0f4d7a, fence: 0x2b5c8a,
    wall: 0x16263d, wallAlt: 0x122036, slab: 0x1b3150, slabEdge: 0x2f8fd8, seam: 0x2a74b8, core: 0x14233a,
    glass: 0x3fa9ff, frame: 0x2a4d74, railing: 0x3fb8ff, acUnit: 0x223a58, roof: 0x13233a, solar: 0x1a4f8f,
    trunk: 0x1d2d40, leaf: 0x14506a, leaf2: 0x0f3f5a, hedge: 0x0f3d52,
    carBody: 0x2a3e5c, carGlass: 0x6fd0ff, lamp: 0x2b4a6a, lampHead: 0xffd98a,
    floorLiving: 0x1d3150, floorBed: 0x1a2c48, floorWet: 0x173049, floorKitchen: 0x1a2f45, floorBalcony: 0x16263b, floorStorage: 0x172639,
    intWall: 0x22406a, door: 0x2f5b88, furniture: 0x2a4466, fabric: 0x2f5580, fabric2: 0x355d8a, wood: 0x2d4a6e,
    ceramic: 0x8fc8ff, metal: 0x5d7fa3, appliance: 0x3a5c82, counter: 0x243a58,
    cold: 0x3aa0ff, hot: 0xff5a4a, drain: 0x8aa0b8, stack: 0x9fb4c8, circuit: 0xffc02a, panel: 0x4a6a8f, sensor: 0x19e6d2,
    service: 0x1d3150, utility: 0x1a2c46, canopy: 0x1f5d9a, parcel: 0x137a55, court: 0x3b2a3a, courtLine: 0x3fa9ff, play: 0x7a4a2a,
    label: '#dff1ff',
  },
}

// 夜间自发光的材质键与强度
const NIGHT_EMISSIVE = {
  glass: 0.55, railing: 0.35, slabEdge: 0.9, seam: 0.45, roadLine: 0.8, water: 0.35, lampHead: 1.6, carGlass: 0.4,
  cold: 0.6, hot: 0.6, circuit: 0.8, sensor: 1.0, fence: 0.3, canopy: 0.3, courtLine: 0.7, solar: 0.3,
}

const TRANSPARENT = { glass: 0.45, railing: 0.35, water: 0.85, carGlass: 0.85 }

const cache = new Map()
let currentTheme = 'day'

export function mat(key, opts = {}) {
  const cacheKey = opts.variant ? `${key}:${opts.variant}` : key
  if (cache.has(cacheKey)) return cache.get(cacheKey)
  const color = PALETTE[currentTheme][key] ?? 0xff00ff
  const m = new THREE.MeshStandardMaterial({
    color, roughness: opts.roughness ?? (key === 'glass' || key === 'water' ? 0.15 : 0.82),
    metalness: opts.metalness ?? (key === 'metal' || key === 'glass' ? 0.25 : 0.02),
    transparent: key in TRANSPARENT || !!opts.transparent,
    opacity: TRANSPARENT[key] ?? 1,
    side: opts.side ?? THREE.FrontSide,
    depthWrite: !(key in TRANSPARENT),
  })
  m.userData = { key, baseOpacity: m.opacity }
  cache.set(cacheKey, m)
  applyThemeTo(m, currentTheme)
  return m
}

function applyThemeTo(m, theme) {
  const k = m.userData.key
  const c = PALETTE[theme][k]
  if (c !== undefined) m.color.setHex(c)
  if (theme === 'night' && NIGHT_EMISSIVE[k]) {
    m.emissive.setHex(c)
    m.emissiveIntensity = NIGHT_EMISSIVE[k]
  } else {
    m.emissive.setHex(k === 'lampHead' ? 0xfff2c8 : 0x000000)
    m.emissiveIntensity = k === 'lampHead' ? 0.4 : 0
  }
  m.needsUpdate = true
}

export function setMaterialTheme(theme) {
  currentTheme = theme
  for (const m of cache.values()) applyThemeTo(m, theme)
}

export function palette(theme = currentTheme) {
  return PALETTE[theme]
}

/** 透视（X 光）模式：降低结构类材质不透明度 */
const STRUCTURE_KEYS = ['wall', 'wallAlt', 'slab', 'intWall', 'core', 'door', 'furniture', 'fabric', 'fabric2', 'wood', 'ceramic', 'appliance', 'counter', 'metal',
  'floorLiving', 'floorBed', 'floorWet', 'floorKitchen', 'floorBalcony', 'floorStorage']
export function setStructureOpacity(opacity) {
  for (const k of STRUCTURE_KEYS) {
    const m = cache.get(k)
    if (!m) continue
    m.transparent = opacity < 0.999 || (m.userData.baseOpacity < 1)
    m.opacity = Math.min(opacity, m.userData.baseOpacity)
    m.depthWrite = opacity > 0.6
    m.needsUpdate = true
  }
}

/** 为需要独立高亮的对象创建独立材质（颜色取主题色） */
export function uniqueMat(key) {
  const base = mat(key)
  const m = base.clone()
  m.userData = { ...base.userData, unique: true }
  return m
}

export function uniqueThemeSync(m) {
  if (m?.userData?.key) applyThemeTo(m, currentTheme)
}
