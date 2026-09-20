// 小区环境：地面、道路、车位与车辆、绿化、围墙大门、景观与配套设施
import * as THREE from 'three'
import { Batch, textSprite } from './geo'
import { mat } from './materials'
import { BUILDINGS, SITE, FACILITIES, PLAYGROUND, FITNESS, COURT, POOL, GARAGE_RAMP } from '../data/site'

function rng(seed) {
  let s = seed >>> 0
  return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296)
}

export function buildSite() {
  const root = new THREE.Group()
  root.name = 'site'
  const b = new Batch()
  const { minX, maxX, minZ, maxZ } = SITE.bounds
  const R = SITE.ring
  const rand = rng(20260915)

  // 地面与草地
  b.box('ground', minX - 60, -0.4, minZ - 60, maxX + 60, -0.05, maxZ + 60)
  b.box('grass', minX, -0.05, minZ, maxX, 0.0, maxZ)

  // 环路
  const road = (x0, z0, x1, z1) => b.box('road', x0, 0.0, z0, x1, 0.04, z1)
  road(R.minX - R.width / 2, R.minZ - R.width / 2, R.maxX + R.width / 2, R.minZ + R.width / 2)
  road(R.minX - R.width / 2, R.maxZ - R.width / 2, R.maxX + R.width / 2, R.maxZ + R.width / 2)
  road(R.minX - R.width / 2, R.minZ, R.minX + R.width / 2, R.maxZ)
  road(R.maxX - R.width / 2, R.minZ, R.maxX + R.width / 2, R.maxZ)
  // 中间东西向道路与大门道路
  road(R.minX, 0 - 3, R.maxX, 0 + 3)
  road(-4, R.maxZ, 4, maxZ + 8)
  road(-3, -12, 3, R.maxZ)
  // 道路中线（虚线）
  const dashes = (x0, z0, x1, z1) => {
    const len = Math.hypot(x1 - x0, z1 - z0); const n = Math.floor(len / 6)
    for (let i = 0; i < n; i++) {
      const t0 = i / n, t1 = t0 + 0.5 / n
      const ax = x0 + (x1 - x0) * t0, az = z0 + (z1 - z0) * t0, bx = x0 + (x1 - x0) * t1, bz = z0 + (z1 - z0) * t1
      b.box('roadLine', Math.min(ax, bx) - 0.08, 0.04, Math.min(az, bz) - 0.08, Math.max(ax, bx) + 0.08, 0.06, Math.max(az, bz) + 0.08)
    }
  }
  dashes(R.minX, R.minZ, R.maxX, R.minZ); dashes(R.minX, R.maxZ, R.maxX, R.maxZ)
  dashes(R.minX, R.minZ, R.minX, R.maxZ); dashes(R.maxX, R.minZ, R.maxX, R.maxZ)
  dashes(0, R.maxZ + 4, 0, maxZ + 8)
  // 斑马线
  for (let i = 0; i < 7; i++) b.box('roadLine', -3.6 + i * 1.1, 0.04, R.maxZ - 5, -3.0 + i * 1.1, 0.06, R.maxZ - 1.5)

  // 楼栋周边人行铺装与入口雨棚
  for (const bd of BUILDINGS) {
    b.box('sidewalk', bd.x - 23, 0.0, bd.z - 12.5, bd.x + 23, 0.08, bd.z + 16)
    b.box('plaza', bd.x - 3, 0.0, bd.z - 9, bd.x + 3, 0.1, bd.z - 26) // 北侧入口步道
    // 绿篱
    b.box('hedge', bd.x - 23, 0.08, bd.z + 16, bd.x + 23, 0.9, bd.z + 17)
  }
  // 大门广场
  b.box('plaza', -24, 0.0, R.maxZ + 3.5, 24, 0.08, maxZ)

  // 中心景观：水池 + 喷泉
  const pool = new THREE.CylinderGeometry(POOL.r, POOL.r, 0.12, 48); pool.translate(POOL.x, 0.06, POOL.z); b.geom('plaza', pool)
  const water = new THREE.CylinderGeometry(POOL.r - 0.8, POOL.r - 0.8, 0.1, 48); water.translate(POOL.x, 0.14, POOL.z); b.geom('water', water)
  b.cyl('ceramic', POOL.x, 0.1, POOL.z, 1.6, 0.6, 16)
  const bowl = new THREE.CylinderGeometry(1.6, 0.7, 0.5, 20); bowl.translate(POOL.x, 1.7, POOL.z); b.geom('ceramic', bowl)
  // 景观步道环
  const ring = new THREE.RingGeometry(POOL.r + 1, POOL.r + 3, 48); ring.rotateX(-Math.PI / 2); ring.translate(POOL.x, 0.05, POOL.z); b.geom('sidewalk', ring)

  // 儿童游乐区
  const pg = new THREE.CylinderGeometry(PLAYGROUND.r, PLAYGROUND.r, 0.06, 36); pg.translate(PLAYGROUND.x, 0.03, PLAYGROUND.z); b.geom('court', pg)
  b.box('play', PLAYGROUND.x - 3, 0, PLAYGROUND.z - 1, PLAYGROUND.x - 1, 2.4, PLAYGROUND.z + 1)
  const slide = new THREE.BoxGeometry(0.9, 0.1, 4.2); slide.rotateX(0.55); slide.translate(PLAYGROUND.x - 2, 1.25, PLAYGROUND.z + 2.6); b.geom('canopy', slide)
  for (const dx of [2, 5]) { b.box('metal', PLAYGROUND.x + dx, 0, PLAYGROUND.z - 1.5, PLAYGROUND.x + dx + 0.12, 2.6, PLAYGROUND.z - 1.38); b.box('metal', PLAYGROUND.x + dx, 0, PLAYGROUND.z + 1.4, PLAYGROUND.x + dx + 0.12, 2.6, PLAYGROUND.z + 1.52) }
  b.box('metal', PLAYGROUND.x + 2, 2.5, PLAYGROUND.z - 1.5, PLAYGROUND.x + 5.12, 2.62, PLAYGROUND.z + 1.52)
  b.box('play', PLAYGROUND.x + 3, 0.5, PLAYGROUND.z - 0.3, PLAYGROUND.x + 4, 0.58, PLAYGROUND.z + 0.3)

  // 健身区
  b.box('court', FITNESS.x - FITNESS.w / 2, 0, FITNESS.z - FITNESS.d / 2, FITNESS.x + FITNESS.w / 2, 0.06, FITNESS.z + FITNESS.d / 2)
  for (let i = 0; i < 4; i++) {
    const x = FITNESS.x - 7 + i * 4.5
    b.box('metal', x, 0, FITNESS.z - 2, x + 0.15, 2.2, FITNESS.z - 1.85); b.box('metal', x + 2, 0, FITNESS.z - 2, x + 2.15, 2.2, FITNESS.z - 1.85)
    b.box('canopy', x, 2.1, FITNESS.z - 2, x + 2.15, 2.25, FITNESS.z - 1.85)
    b.box('play', x + 0.6, 0, FITNESS.z + 2, x + 1.6, 0.8, FITNESS.z + 3.2)
  }

  // 篮球场
  b.box('court', COURT.x - COURT.w / 2, 0, COURT.z - COURT.d / 2, COURT.x + COURT.w / 2, 0.06, COURT.z + COURT.d / 2)
  const cl = (x0, z0, x1, z1) => b.box('courtLine', x0, 0.06, z0, x1, 0.08, z1)
  cl(COURT.x - COURT.w / 2, COURT.z - COURT.d / 2, COURT.x + COURT.w / 2, COURT.z - COURT.d / 2 + 0.12)
  cl(COURT.x - COURT.w / 2, COURT.z + COURT.d / 2 - 0.12, COURT.x + COURT.w / 2, COURT.z + COURT.d / 2)
  cl(COURT.x - 0.06, COURT.z - COURT.d / 2, COURT.x + 0.06, COURT.z + COURT.d / 2)
  const cc = new THREE.RingGeometry(1.7, 1.85, 32); cc.rotateX(-Math.PI / 2); cc.translate(COURT.x, 0.08, COURT.z); b.geom('courtLine', cc)
  for (const s of [-1, 1]) {
    const x = COURT.x + s * (COURT.w / 2 - 0.6)
    b.box('metal', x - 0.1, 0, COURT.z - 0.1, x + 0.1, 3.2, COURT.z + 0.1)
    b.box('ceramic', x - s * 0.1 - 0.05, 2.9, COURT.z - 0.9, x - s * 0.1 + 0.05, 3.9, COURT.z + 0.9)
  }

  // 地下车库出入口坡道
  b.box('road', GARAGE_RAMP.x - GARAGE_RAMP.w / 2, 0.01, GARAGE_RAMP.z - GARAGE_RAMP.d / 2, GARAGE_RAMP.x + GARAGE_RAMP.w / 2, 0.05, GARAGE_RAMP.z + GARAGE_RAMP.d / 2)
  b.box('wallAlt', GARAGE_RAMP.x - GARAGE_RAMP.w / 2 - 0.3, 0, GARAGE_RAMP.z - GARAGE_RAMP.d / 2, GARAGE_RAMP.x - GARAGE_RAMP.w / 2, 1.1, GARAGE_RAMP.z + GARAGE_RAMP.d / 2)
  b.box('wallAlt', GARAGE_RAMP.x + GARAGE_RAMP.w / 2, 0, GARAGE_RAMP.z - GARAGE_RAMP.d / 2, GARAGE_RAMP.x + GARAGE_RAMP.w / 2 + 0.3, 1.1, GARAGE_RAMP.z + GARAGE_RAMP.d / 2)
  const rampRoof = new THREE.BoxGeometry(GARAGE_RAMP.w + 1.2, 0.2, GARAGE_RAMP.d * 0.55); rampRoof.translate(GARAGE_RAMP.x, 3.2, GARAGE_RAMP.z - GARAGE_RAMP.d * 0.2); b.geom('canopy', rampRoof)

  // 围墙：立柱 + 栏杆
  const fence = (x0, z0, x1, z1) => {
    const len = Math.hypot(x1 - x0, z1 - z0); const n = Math.ceil(len / 4)
    for (let i = 0; i <= n; i++) {
      const x = x0 + (x1 - x0) * (i / n), z = z0 + (z1 - z0) * (i / n)
      b.box('fence', x - 0.18, 0, z - 0.18, x + 0.18, 2.2, z + 0.18)
    }
    b.box('fence', Math.min(x0, x1) - 0.05, 1.9, Math.min(z0, z1) - 0.05, Math.max(x0, x1) + 0.05, 2.0, Math.max(z0, z1) + 0.05)
    b.box('fence', Math.min(x0, x1) - 0.05, 0.3, Math.min(z0, z1) - 0.05, Math.max(x0, x1) + 0.05, 0.6, Math.max(z0, z1) + 0.05)
  }
  fence(minX, minZ, maxX, minZ); fence(minX, minZ, minX, maxZ); fence(maxX, minZ, maxX, maxZ)
  fence(minX, maxZ, -8, maxZ); fence(8, maxZ, maxX, maxZ)
  // 大门：门柱、横梁、道闸
  b.box('wallAlt', -9, 0, maxZ - 1, -7, 5, maxZ + 1); b.box('wallAlt', 7, 0, maxZ - 1, 9, 5, maxZ + 1)
  b.box('canopy', -9.5, 5, maxZ - 1.5, 9.5, 5.8, maxZ + 1.5)
  b.box('metal', -6.5, 0, maxZ - 0.2, -6.1, 1.1, maxZ + 0.2); b.box('play', -6.1, 0.95, maxZ - 0.08, -0.5, 1.05, maxZ + 0.08)
  b.box('metal', 6.1, 0, maxZ - 0.2, 6.5, 1.1, maxZ + 0.2); b.box('play', 0.5, 0.95, maxZ - 0.08, 6.1, 1.05, maxZ + 0.08)
  const gateSign = textSprite('筑维花园 · MiC 智慧社区', { size: 56, scale: 2.4, color: '#ffffff', bg: 'rgba(40,90,140,0.9)' })
  gateSign.position.set(0, 7, maxZ); root.add(gateSign)

  // 配套设施
  const facilities = new THREE.Group(); facilities.name = 'facilities'
  for (const f of FACILITIES) {
    const fb = new Batch()
    fb.box(f.color, f.x - f.w / 2, 0, f.z - f.d / 2, f.x + f.w / 2, f.h, f.z + f.d / 2)
    if (f.id === 'charging') {
      fb.box('sidewalk', f.x - f.w / 2, 0, f.z - f.d / 2, f.x + f.w / 2, 0.1, f.z + f.d / 2)
    } else {
      fb.box('roof', f.x - f.w / 2 - 0.3, f.h, f.z - f.d / 2 - 0.3, f.x + f.w / 2 + 0.3, f.h + 0.35, f.z + f.d / 2 + 0.3)
      // 门窗
      fb.box('glass', f.x - f.w / 2 + 1, 0.2, f.z + f.d / 2, f.x + f.w / 2 - 1, f.h - 1, f.z + f.d / 2 + 0.05)
    }
    const g = fb.build({ castShadow: true, receiveShadow: true })
    if (f.id === 'charging') {
      // 充电棚：立柱 + 顶棚（顶棚单独透明化处理不做，使用实体）+ 电动车
      g.clear()
      const cb = new Batch()
      cb.box('sidewalk', f.x - f.w / 2, 0, f.z - f.d / 2, f.x + f.w / 2, 0.1, f.z + f.d / 2)
      for (let i = 0; i <= 5; i++) { const x = f.x - f.w / 2 + i * (f.w / 5); cb.box('metal', x - 0.1, 0, f.z - f.d / 2, x + 0.1, f.h, f.z - f.d / 2 + 0.2) }
      cb.box('canopy', f.x - f.w / 2 - 0.5, f.h, f.z - f.d / 2 - 0.3, f.x + f.w / 2 + 0.5, f.h + 0.15, f.z + f.d / 2 + 0.3)
      for (let i = 0; i < 12; i++) {
        const x = f.x - f.w / 2 + 1 + i * 1.75
        cb.box(i % 3 ? 'fabric' : 'play', x - 0.2, 0.3, f.z - 0.8, x + 0.2, 0.9, f.z + 1.0)
        cb.box('metal', x - 0.05, 0.1, f.z - 1.0, x + 0.05, 1.2, f.z - 0.9)
        cb.box('parcel', x - 0.15, 0.9, f.z - f.d / 2 + 0.2, x + 0.15, 1.4, f.z - f.d / 2 + 0.4)
      }
      const cg = cb.build({ castShadow: true, receiveShadow: true })
      cg.children.forEach(ch => g.add(ch))
    }
    if (f.id === 'pump') {
      const pb = new Batch()
      for (let i = 0; i < 3; i++) { pb.cyl('metal', f.x - 5 + i * 2.4, 0, f.z - f.d / 2 - 2.5, 1.6, 0.7, 16) }
      pb.box('cold', f.x - 6, 1.2, f.z - f.d / 2 - 2.6, f.x + 1, 1.35, f.z - f.d / 2 - 2.4)
      const pg2 = pb.build({ castShadow: true })
      pg2.children.forEach(ch => g.add(ch))
    }
    g.userData = { pick: 'facility', id: f.id, name: f.name }
    g.traverse(o => { if (o.isMesh) o.userData = { pick: 'facility', id: f.id, name: f.name } })
    const label = textSprite(f.name, { size: 40, scale: 1.6 })
    label.position.set(f.x, f.h + 2.2, f.z)
    label.userData.siteLabel = true
    g.add(label)
    facilities.add(g)
  }
  root.add(facilities)

  // 长椅
  for (let i = 0; i < 10; i++) {
    const a = (i / 10) * Math.PI * 2
    const x = POOL.x + Math.cos(a) * (POOL.r + 4.5), z = POOL.z + Math.sin(a) * (POOL.r + 4.5)
    b.box('wood', x - 0.9, 0.4, z - 0.25, x + 0.9, 0.5, z + 0.25); b.box('metal', x - 0.8, 0, z - 0.1, x - 0.7, 0.4, z + 0.1); b.box('metal', x + 0.7, 0, z - 0.1, x + 0.8, 0.4, z + 0.1)
  }

  const staticGroup = b.build({ receiveShadow: true, castShadow: true })
  staticGroup.name = 'siteStatic'
  root.add(staticGroup)

  // ------------------- 实例化：车位与车辆 -------------------
  const parking = []
  const bayLines = new Batch()
  const addBays = (x0, z, n, dir) => {
    for (let i = 0; i < n; i++) {
      const x = x0 + i * 2.7
      bayLines.box('roadLine', x - 0.06, 0.04, z, x + 0.06, 0.06, z + dir * 5.2)
      parking.push({ x: x + 1.35, z: z + dir * 2.6, rot: 0 })
    }
    bayLines.box('road', x0, 0.0, Math.min(z, z + dir * 5.2), x0 + n * 2.7, 0.035, Math.max(z, z + dir * 5.2))
  }
  addBays(-94, R.maxZ - 3.5, 22, -1)
  addBays(35, R.maxZ - 3.5, 20, -1)
  addBays(-94, R.minZ + 3.5, 26, 1)
  addBays(20, R.minZ + 3.5, 26, 1)
  const bayGroup = bayLines.build({ receiveShadow: true })
  root.add(bayGroup)

  const carColors = [0xffffff, 0x2b2f36, 0xb8bec4, 0x8a1c1c, 0x1f4e8c, 0xd9d4c7, 0x4b5a3c]
  const bodyGeo = new THREE.BoxGeometry(1.8, 0.75, 4.3); bodyGeo.translate(0, 0.55, 0)
  const cabinGeo = new THREE.BoxGeometry(1.6, 0.6, 2.2); cabinGeo.translate(0, 1.2, -0.2)
  const occupied = parking.filter(() => rand() < 0.72)
  const bodies = new THREE.InstancedMesh(bodyGeo, mat('carBody', { variant: 'inst' }), occupied.length)
  const cabins = new THREE.InstancedMesh(cabinGeo, mat('carGlass'), occupied.length)
  const m4 = new THREE.Matrix4(); const color = new THREE.Color()
  occupied.forEach((p, i) => {
    m4.makeRotationY(p.rot); m4.setPosition(p.x, 0, p.z)
    bodies.setMatrixAt(i, m4); cabins.setMatrixAt(i, m4)
    color.setHex(carColors[Math.floor(rand() * carColors.length)]); bodies.setColorAt(i, color)
  })
  bodies.castShadow = true
  root.add(bodies, cabins)

  // ------------------- 实例化：树木 -------------------
  const trees = []
  const tryTree = (x, z) => {
    if (x < minX + 3 || x > maxX - 3 || z < minZ + 3 || z > maxZ - 3) return
    for (const bd of BUILDINGS) if (Math.abs(x - bd.x) < 26 && Math.abs(z - bd.z) < 20) return
    if (Math.abs(z - R.minZ) < 12 || Math.abs(z - R.maxZ) < 12) { if (Math.abs(z - R.minZ) < 6 || Math.abs(z - R.maxZ) < 6) return }
    if (Math.abs(x - R.minX) < 5 || Math.abs(x - R.maxX) < 5 || Math.abs(z) < 5) return
    if (Math.hypot(x - POOL.x, z - POOL.z) < POOL.r + 7) return
    if (Math.hypot(x - PLAYGROUND.x, z - PLAYGROUND.z) < PLAYGROUND.r + 2) return
    if (Math.abs(x - FITNESS.x) < 12 && Math.abs(z - FITNESS.z) < 9) return
    if (Math.abs(x - COURT.x) < 16 && Math.abs(z - COURT.z) < 10) return
    if (Math.abs(x) < 6 && z > -12) return
    for (const f of FACILITIES) if (Math.abs(x - f.x) < f.w / 2 + 3 && Math.abs(z - f.z) < f.d / 2 + 3) return
    if (Math.abs(x - GARAGE_RAMP.x) < 7 && Math.abs(z - GARAGE_RAMP.z) < 12) return
    trees.push({ x, z, s: 0.8 + rand() * 0.6, k: rand() < 0.5 })
  }
  for (let x = minX + 4; x < maxX - 4; x += 7) { tryTree(x + rand() * 2, minZ + 5); tryTree(x + rand() * 2, maxZ - 5) }
  for (let z = minZ + 4; z < maxZ - 4; z += 7) { tryTree(minX + 5, z + rand() * 2); tryTree(maxX - 5, z + rand() * 2) }
  for (let i = 0; i < 520; i++) tryTree(minX + rand() * (maxX - minX), minZ + rand() * (maxZ - minZ))
  const trunkGeo = new THREE.CylinderGeometry(0.18, 0.25, 2.4, 6); trunkGeo.translate(0, 1.2, 0)
  const crownGeo = new THREE.IcosahedronGeometry(1.8, 1); crownGeo.translate(0, 3.6, 0)
  const coneGeo = new THREE.ConeGeometry(1.6, 4.2, 8); coneGeo.translate(0, 4.2, 0)
  const round = trees.filter(t => t.k), cone = trees.filter(t => !t.k)
  const trunks = new THREE.InstancedMesh(trunkGeo, mat('trunk'), trees.length)
  const crowns = new THREE.InstancedMesh(crownGeo, mat('leaf'), round.length)
  const cones = new THREE.InstancedMesh(coneGeo, mat('leaf2'), cone.length)
  trees.forEach((t, i) => { m4.makeScale(t.s, t.s, t.s); m4.setPosition(t.x, 0, t.z); trunks.setMatrixAt(i, m4) })
  round.forEach((t, i) => { m4.makeScale(t.s, t.s, t.s); m4.setPosition(t.x, 0, t.z); crowns.setMatrixAt(i, m4) })
  cone.forEach((t, i) => { m4.makeScale(t.s, t.s, t.s); m4.setPosition(t.x, 0, t.z); cones.setMatrixAt(i, m4) })
  ;[trunks, crowns, cones].forEach(m => { m.castShadow = true })
  root.add(trunks, crowns, cones)

  // ------------------- 实例化：路灯 -------------------
  const lamps = []
  for (let x = R.minX + 6; x < R.maxX; x += 16) { lamps.push([x, R.minZ - 4.2]); lamps.push([x, R.maxZ + 4.2]) }
  for (let z = R.minZ + 8; z < R.maxZ; z += 16) { lamps.push([R.minX - 4.2, z]); lamps.push([R.maxX + 4.2, z]) }
  const poleGeo = new THREE.CylinderGeometry(0.08, 0.12, 5.5, 6); poleGeo.translate(0, 2.75, 0)
  const headGeo = new THREE.SphereGeometry(0.35, 10, 8); headGeo.translate(0, 5.6, 0)
  const poles = new THREE.InstancedMesh(poleGeo, mat('lamp'), lamps.length)
  const heads = new THREE.InstancedMesh(headGeo, mat('lampHead'), lamps.length)
  lamps.forEach(([x, z], i) => { m4.makeTranslation(x, 0, z); poles.setMatrixAt(i, m4); heads.setMatrixAt(i, m4) })
  root.add(poles, heads)

  // 夜间路灯光晕
  const glowTex = radialTexture()
  const glowGroup = new THREE.Group(); glowGroup.name = 'nightGlow'
  for (const [x, z] of lamps) {
    const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTex, color: 0xffcf7a, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending }))
    s.position.set(x, 5.6, z); s.scale.set(6, 6, 1); glowGroup.add(s)
  }
  glowGroup.visible = false
  root.add(glowGroup)

  return root
}

let _radial = null
export function radialTexture() {
  if (_radial) return _radial
  const c = document.createElement('canvas'); c.width = c.height = 128
  const ctx = c.getContext('2d')
  const g = ctx.createRadialGradient(64, 64, 0, 64, 64, 64)
  g.addColorStop(0, 'rgba(255,255,255,1)'); g.addColorStop(0.25, 'rgba(255,255,255,0.55)'); g.addColorStop(1, 'rgba(255,255,255,0)')
  ctx.fillStyle = g; ctx.fillRect(0, 0, 128, 128)
  _radial = new THREE.CanvasTexture(c)
  return _radial
}
