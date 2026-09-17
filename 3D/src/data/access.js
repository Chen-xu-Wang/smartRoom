// 3D 数字孪生的访问控制：登录角色 → 可用视角、只读视角、可见住户
//
// 权限表（2026-09 确认）：
//   物业 / 管理员：物业 + 住宅（全部户）+ 维修（只读）
//   业主（居民）：业主 + 住宅（仅自己绑定的户）
//   维修人员：维修 + 住宅（仅自己工单涉及的户）
// 未登录的独立运行（演示调试）不受限，四个视角自由切换。
//
// 注意：这里只是界面层的隔离，数据仍整份下发到浏览器；
// 真正的数据隔离由后端鉴权按户过滤（第三步）保证。

export const VIEWS_OF_BACKEND = {
  PROPERTY: ['property', 'archive', 'repairer'],
  ADMIN: ['property', 'archive', 'repairer'],
  RESIDENT: ['owner', 'archive'],
  REPAIRER: ['repairer', 'archive'],
}

/** 可进入但只能查看、不能操作的视角 */
export const READONLY_VIEWS = {
  PROPERTY: ['repairer'],
  ADMIN: ['repairer'],
}

/** 数据范围：all 全部；owner 仅本户及影响本户的问题；repairer 仅派给自己的工单 */
export const SCOPE_OF_BACKEND = { PROPERTY: 'all', ADMIN: 'all', RESIDENT: 'owner', REPAIRER: 'repairer' }

/** 住户名下房屋：来自登录接口返回的 house_ids（后端 user_house 表），不信任其它来源 */
export function houseIdsOf(user) {
  return Array.isArray(user?.houseIds) ? user.houseIds.map(String) : []
}

export const floorOfHouse = (h) => Number(String(h).slice(0, -2))

/** 事件提醒里涉及的住户（演示样例 decision.notices 用 house_ids，联机数据 notices 用 house_id） */
export function noticeHousesOf(ev) {
  const out = new Set()
  const list = ev.notices?.length ? ev.notices : (ev.decision?.notices || [])
  for (const n of list) {
    if (!['RESIDENT', 'NEIGHBOR'].includes(n.audience)) continue
    for (const h of n.house_ids || (n.house_id ? [n.house_id] : [])) out.add(String(h))
  }
  return out
}
