import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  {
    path: '/',
    name: 'Home',
    component: () => import('../views/Home.vue')
  },
  {
    path: '/scan',
    name: 'ScanCode',
    component: () => import('../views/ScanCode.vue')
  },
  {
    path: '/chat/:houseId',
    name: 'ChatRepair',
    component: () => import('../views/ChatRepair.vue')
  },
  {
    path: '/workorder/:id',
    name: 'WorkOrderDetail',
    component: () => import('../views/WorkOrderDetail.vue')
  },
  {
    path: '/archive/:houseId',
    name: 'HouseArchive',
    component: () => import('../views/HouseArchive.vue')
  },
  {
    path: '/property',
    name: 'PropertyDashboard',
    component: () => import('../views/PropertyDashboard.vue')
  },
  {
    path: '/repair',
    name: 'RepairTasks',
    component: () => import('../views/RepairTasks.vue')
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

export default router
