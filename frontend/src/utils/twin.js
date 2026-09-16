// 3D 数字孪生相关的小工具。
//
// 现在 3D 是本前端内部的一个页面（路由 /twin，见 views/Twin3D.vue），
// 页面内切换不再跳转外链；本文件只剩两类用途：
//   1. 按登录角色推断默认视角（twinRoleOf）
//   2. 3D 独立工程（端口 5174，见 3D/README.md）与本前端之间的登录态传递
//
// 登录态传递：独立运行时两边端口不同、localStorage 互不相通，因此在链接上带一个
// auth 参数，内容是 stores/auth.js 存的登录用户对象（id、用户名、角色、姓名，不含密码），
// 接收方落盘后把参数从地址栏清掉。内嵌使用时同源，不需要这个参数。

export const AUTH_KEY = 'zw_auth'

export function encodeAuth(user) {
  if (!user) return ''
  const bytes = new TextEncoder().encode(JSON.stringify(user))
  return btoa(String.fromCharCode(...bytes))
}

export function decodeAuth(token) {
  try {
    const bin = atob(token)
    const bytes = Uint8Array.from(bin, c => c.charCodeAt(0))
    return JSON.parse(new TextDecoder().decode(bytes))
  } catch {
    return null
  }
}

/** 给目标地址补上当前登录态参数（供 3D 独立工程跳回控制台时使用） */
export function withAuthParam(base) {
  const url = new URL(base, location.origin)
  try {
    const raw = localStorage.getItem(AUTH_KEY)
    if (raw) url.searchParams.set('auth', encodeAuth(JSON.parse(raw)))
  } catch { /* 隐私模式下读不到 localStorage，按未登录处理 */ }
  return url.toString()
}

/** 按登录角色推断默认视角 */
export function twinRoleOf(auth) {
  if (auth?.isRepairer) return 'repairer'
  if (auth?.isProperty) return 'property'
  if (auth?.isResident) return 'owner'
  return 'property'
}

/**
 * 从 3D 独立页面跳回来时，接收 URL 上带的登录态并落盘。
 * 返回接收到的用户对象；地址栏参数由调用方用路由清理。
 */
export function adoptAuthFromUrl() {
  const token = new URLSearchParams(location.search).get('auth')
  if (!token) return null
  const user = decodeAuth(token)
  if (!user || !user.username) return null
  localStorage.setItem(AUTH_KEY, JSON.stringify(user))
  return user
}
