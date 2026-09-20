import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'
import App from './App.vue'
// 复用现有前端的全局样式变量与字体（--primary-color / --text-* / 圆角阴影等），
// 本工程自己的 styles.css 放在后面，只覆盖 3D 页面特有的部分。
import '@app/styles/main.css'
import './styles.css'
import './standalone.css'

// 复用的业务组件内部会调用 $router.push（如"查看工单"）。
// 3D 工程不承载这些页面：拦截跳转，在新标签页打开现有前端对应页面。
const router = createRouter({
  history: createMemoryHistory(),
  routes: [{ path: '/:pathMatch(.*)*', component: { render: () => null } }],
})
router.beforeEach((to) => {
  if (to.fullPath === '/' ) return true
  window.open(`${location.protocol}//${location.hostname}:5173${to.fullPath}`, '_blank')
  return false
})

const app = createApp(App)
for (const [key, component] of Object.entries(ElementPlusIconsVue)) app.component(key, component)
app.use(createPinia())
app.use(router)
app.use(ElementPlus)
app.mount('#app')
