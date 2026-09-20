// 3D 数字孪生相关的小工具。
//
// 3D 是本前端内部的一个页面（路由 /twin，见 views/Twin3D.vue），与前端共用登录态。
// 3D 独立工程（端口 5174）需要自己登录：登录态里含访问令牌，不再通过 URL 在两个端口之间传递。

/** 按登录角色推断默认视角 */
export function twinRoleOf(auth) {
  if (auth?.isRepairer) return 'repairer'
  if (auth?.isProperty) return 'property'
  if (auth?.isResident) return 'owner'
  return 'property'
}
