// 3D 数字孪生独立工程
// - @app 指向现有前端源码，复用接口封装、登录状态和部分业务组件
// - dedupe 保证复用代码与本工程共用同一份 vue / pinia / element-plus 实例
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  plugins: [vue()],
  // 楼栋与事件数据只放一份，在现有前端的 public 下；独立工程直接复用该目录
  publicDir: fileURLToPath(new URL('../frontend/public', import.meta.url)),
  resolve: {
    alias: [
      { find: /^@app\//, replacement: fileURLToPath(new URL('../frontend/src/', import.meta.url)).replace(/\\/g, '/') },
      { find: /^@\//, replacement: fileURLToPath(new URL('./src/', import.meta.url)).replace(/\\/g, '/') },
    ],
    dedupe: ['vue', 'pinia', 'vue-router', 'element-plus', '@element-plus/icons-vue', 'axios'],
  },
  server: {
    port: 5174,
    host: true,
    fs: { allow: ['..'] },
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
  build: {
    chunkSizeWarningLimit: 2000,
  },
})
