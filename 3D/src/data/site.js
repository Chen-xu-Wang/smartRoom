// 小区总图（世界坐标，米）：x 向东，z 向南，y 向上。
// 6 栋楼复用同一标准层；只有 1栋接入模拟数据。

export const FLOORS = 18
export const FLOOR_H = 3.0

export const BUILDINGS = [
  { no: 1, name: '1栋', x: 0, z: 38, live: true },
  { no: 2, name: '2栋', x: -62, z: 38, live: false },
  { no: 3, name: '3栋', x: 62, z: 38, live: false },
  { no: 4, name: '4栋', x: -62, z: -34, live: false },
  { no: 5, name: '5栋', x: 0, z: -34, live: false },
  { no: 6, name: '6栋', x: 62, z: -34, live: false },
]

export const SITE = {
  bounds: { minX: -112, maxX: 112, minZ: -96, maxZ: 104 },
  gate: { x: 0, z: 104 },
  ring: { minX: -98, maxX: 98, minZ: -82, maxZ: 86, width: 7 },
}

// 配套设施：code 对应 sim_building.json 的 building_points
export const FACILITIES = [
  { id: 'service', name: '物业服务中心', x: -78, z: 72, w: 20, d: 12, h: 7, color: 'service' },
  { id: 'pump', name: '二次供水泵房', x: 84, z: -66, w: 16, d: 12, h: 5, color: 'utility',
    codes: ['WS-BLDG-PUMP-MID', 'WS-BLDG-PUMP-HIGH', 'WS-BLDG-LOW-MT', 'WS-BLDG-MID-MT', 'WS-BLDG-HIGH-MT'] },
  { id: 'power', name: '配电房', x: -86, z: -66, w: 14, d: 10, h: 5, color: 'utility', codes: ['CB-BLDG-PUB'] },
  { id: 'charging', name: '电动车集中充电棚', x: 80, z: 72, w: 22, d: 8, h: 3.2, color: 'canopy' },
  { id: 'garbage', name: '垃圾分类站', x: -100, z: 6, w: 8, d: 5, h: 3, color: 'utility' },
  { id: 'parcel', name: '快递柜', x: -64, z: 72, w: 5, d: 1.2, h: 2.2, color: 'parcel' },
  { id: 'guard', name: '门岗亭', x: 12, z: 98, w: 4, d: 3, h: 3, color: 'service' },
]

export const PLAYGROUND = { x: -30, z: 2, r: 12 }
export const FITNESS = { x: 30, z: 2, w: 20, d: 14 }
export const COURT = { x: 0, z: -72, w: 28, d: 15 }
export const POOL = { x: 0, z: 2, r: 9 }
export const GARAGE_RAMP = { x: 40, z: 94, w: 8, d: 18 }

export function buildingByNo(no) {
  return BUILDINGS.find(b => b.no === Number(no))
}
