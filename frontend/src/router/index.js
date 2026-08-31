import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const routes = [
  {
    path: '/',
    name: 'Home',
    component: () => import('../views/Home.vue')
  },
  {
    path: '/login',
    name: 'Login',
    component: () => import('../views/Login.vue')
  },
  {
    path: '/scan',
    name: 'ScanCode',
    component: () => import('../views/ScanCode.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/chat/:houseId',
    name: 'ChatRepair',
    component: () => import('../views/ChatRepair.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/workorder/:id',
    name: 'WorkOrderDetail',
    component: () => import('../views/WorkOrderDetail.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/archive/:houseId',
    name: 'HouseArchive',
    component: () => import('../views/HouseArchive.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/property',
    name: 'PropertyDashboard',
    component: () => import('../views/PropertyDashboard.vue'),
    meta: { requiresAuth: true, requiresProperty: true }
  },
  {
    path: '/repair',
    name: 'RepairTasks',
    component: () => import('../views/RepairTasks.vue'),
    meta: { requiresAuth: true, requiresRepairer: true }
  },
  {
    path: '/admin/houses',
    name: 'AdminHouses',
    component: () => import('../views/AdminHouses.vue'),
    meta: { requiresAuth: true, requiresProperty: true }
  },
  {
    path: '/admin/users',
    name: 'AdminUsers',
    component: () => import('../views/AdminUsers.vue'),
    meta: { requiresAuth: true, requiresProperty: true }
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

router.beforeEach((to) => {
  const auth = useAuthStore()
  if (to.meta.requiresAuth && !auth.isLoggedIn) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }
  if (to.meta.requiresAdmin && !auth.isAdmin) {
    return { path: '/login', query: { redirect: to.fullPath, role: 'admin' } }
  }
  if (to.meta.requiresProperty && !auth.isProperty) {
    // 维修工不允许进物业/管理后台
    if (auth.isRepairer) return { path: '/repair' }
    return { path: '/login', query: { redirect: to.fullPath, role: 'admin' } }
  }
  if (to.meta.requiresRepairer && !(auth.isRepairer || auth.isProperty)) {
    return { path: '/login', query: { redirect: to.fullPath, role: 'admin' } }
  }
})

export default router
