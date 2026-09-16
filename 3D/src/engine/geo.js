// 几何工具：按材质合并的盒子批处理、管线折线、文字贴图
import * as THREE from 'three'
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js'
import { mat } from './materials'

const UNIT_BOX = new THREE.BoxGeometry(1, 1, 1)

/** 按材质键收集几何，最后合并成少量 Mesh */
export class Batch {
  constructor() { this.parts = new Map() }
  _push(key, g) {
    if (!this.parts.has(key)) this.parts.set(key, [])
    this.parts.get(key).push(g)
  }
  /** 轴对齐盒子：min/max 世界（或父级局部）坐标 */
  box(key, x0, y0, z0, x1, y1, z1) {
    const w = Math.abs(x1 - x0), h = Math.abs(y1 - y0), d = Math.abs(z1 - z0)
    if (w < 1e-4 || h < 1e-4 || d < 1e-4) return
    const g = UNIT_BOX.clone()
    g.scale(w, h, d)
    g.translate((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2)
    this._push(key, g)
  }
  cyl(key, x, y0, z, y1, r, seg = 10) {
    const g = new THREE.CylinderGeometry(r, r, Math.abs(y1 - y0), seg)
    g.translate(x, (y0 + y1) / 2, z)
    this._push(key, g)
  }
  geom(key, g) { this._push(key, g) }
  build(opts = {}) {
    const group = new THREE.Group()
    for (const [key, list] of this.parts) {
      const merged = mergeGeometries(list.map(g => (g.index ? g.toNonIndexed() : g)), false)
      list.forEach(g => g.dispose())
      if (!merged) continue
      const mesh = new THREE.Mesh(merged, mat(key))
      mesh.castShadow = !!opts.castShadow && !['glass', 'railing', 'water'].includes(key)
      mesh.receiveShadow = !!opts.receiveShadow
      mesh.userData.matKey = key
      group.add(mesh)
    }
    this.parts.clear()
    return group
  }
}

/** 单个独立盒子 Mesh（可拾取、可高亮） */
export function boxMesh(material, x0, y0, z0, x1, y1, z1) {
  const g = new THREE.BoxGeometry(Math.max(Math.abs(x1 - x0), 1e-3), Math.max(Math.abs(y1 - y0), 1e-3), Math.max(Math.abs(z1 - z0), 1e-3))
  const m = new THREE.Mesh(g, material)
  m.position.set((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2)
  return m
}

/** 折线管道：多段圆柱 + 弯头球，返回合并后的 BufferGeometry（几何中心在包围盒中心，便于脉冲放大） */
export function pipeGeometry(points, radius, radial = 8) {
  const geos = []
  const up = new THREE.Vector3(0, 1, 0)
  for (let i = 1; i < points.length; i++) {
    const a = new THREE.Vector3(...points[i - 1])
    const b = new THREE.Vector3(...points[i])
    const len = a.distanceTo(b)
    if (len < 1e-4) continue
    const g = new THREE.CylinderGeometry(radius, radius, len, radial, 1, true)
    const q = new THREE.Quaternion().setFromUnitVectors(up, b.clone().sub(a).normalize())
    g.applyQuaternion(q)
    g.translate((a.x + b.x) / 2, (a.y + b.y) / 2, (a.z + b.z) / 2)
    geos.push(g.toNonIndexed())
  }
  for (let i = 0; i < points.length; i++) {
    const s = new THREE.SphereGeometry(radius * 1.15, radial, 6)
    s.translate(...points[i])
    geos.push(s.toNonIndexed())
  }
  if (!geos.length) {
    const s = new THREE.SphereGeometry(radius * 1.6, radial, 6)
    s.translate(...points[0])
    geos.push(s.toNonIndexed())
  }
  const merged = mergeGeometries(geos, false)
  geos.forEach(g => g.dispose())
  merged.computeBoundingBox()
  return merged
}

/** 把几何平移到以包围盒中心为原点，返回中心坐标（用于放大动画绕自身中心缩放） */
export function centerGeometry(geometry) {
  geometry.computeBoundingBox()
  const c = new THREE.Vector3()
  geometry.boundingBox.getCenter(c)
  geometry.translate(-c.x, -c.y, -c.z)
  return c
}

/** 文字贴图精灵 */
export function textSprite(text, { color = '#1f2d3d', bg = 'rgba(255,255,255,0.85)', size = 48, scale = 1, border = null, depthTest = false } = {}) {
  const canvas = document.createElement('canvas')
  const ctx = canvas.getContext('2d')
  ctx.font = `600 ${size}px "Microsoft YaHei", "PingFang SC", sans-serif`
  const w = Math.ceil(ctx.measureText(text).width) + size
  const h = Math.ceil(size * 1.6)
  canvas.width = w; canvas.height = h
  ctx.font = `600 ${size}px "Microsoft YaHei", "PingFang SC", sans-serif`
  if (bg) {
    ctx.fillStyle = bg
    roundRect(ctx, 0, 0, w, h, h * 0.3); ctx.fill()
  }
  if (border) { ctx.strokeStyle = border; ctx.lineWidth = 4; roundRect(ctx, 2, 2, w - 4, h - 4, h * 0.3); ctx.stroke() }
  ctx.fillStyle = color
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle'
  ctx.fillText(text, w / 2, h / 2 + 2)
  const tex = new THREE.CanvasTexture(canvas)
  tex.colorSpace = THREE.SRGBColorSpace
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, depthTest, transparent: true }))
  sprite.scale.set((w / h) * scale, scale, 1)
  sprite.renderOrder = 10
  return sprite
}

function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath()
  ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r)
  ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath()
}

export function disposeTree(obj) {
  obj.traverse(o => {
    if (o.geometry) o.geometry.dispose()
    if (o.material) {
      const ms = Array.isArray(o.material) ? o.material : [o.material]
      ms.forEach(m => { if (m.userData?.unique || m.map) { m.map?.dispose(); m.dispose() } })
    }
  })
}
