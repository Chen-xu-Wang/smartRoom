// ============================================================
// Vite 前端配置文件（相当于 Java 前后端分离项目里 webpack/vue-cli 的配置）
// ------------------------------------------------------------
// Vite 是 Vue 官方推荐的构建工具（读音 /viːt/，法语「快」）：
//   - 开发模式：npm run dev  → 启动开发服务器，改代码即时热更新
//   - 生产打包：npm run build → 把项目编译成静态文件输出到 dist 目录
// ============================================================
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  // ---------- 插件 ----------
  // Vue 官方插件：让 Vite 能识别和编译 .vue 单文件组件
  plugins: [vue()],

  // ---------- 开发服务器配置 ----------
  server: {
    // 端口号：浏览器访问 http://localhost:5173
    port: 5173,
    // 监听地址：true 表示局域网内其他设备也能访问
    // （比如手机连同一 WiFi 后访问 http://你电脑的IP:5173 测试扫码功能）
    host: true,
    // 启动后自动打开浏览器（不需要可改成 false）
    open: false,

    // ---------- API 代理（前后端联调的关键配置）----------
    // 作用：前端代码里请求 /api/xxx，Vite 会自动把请求转发给后端 8000 端口。
    // 好处：浏览器不会报跨域错误（请求看起来始终是同源的 5173），
    //       后端地址变了只需要改这里，前端业务代码完全不用动。
    // （相当于开发阶段用 Node 帮你做了一个反向代理）
    proxy: {
      '/api': {
        // 后端 FastAPI 服务地址（对应 backend/.env 里的 HOST/PORT）
        target: 'http://localhost:8000',
        // changeOrigin: 把请求头里的 Host 改成目标地址（通常都要开）
        changeOrigin: true,
        // 不重写路径：前端请求 /api/chat/init → 后端收到的还是 /api/chat/init
        // （FastAPI 的路由本来就带 /api 前缀，所以不需要重写）
      },
    },
  },
})
