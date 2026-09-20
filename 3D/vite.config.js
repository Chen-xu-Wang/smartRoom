// 3D 数字孪生独立工程
// - @app 指向现有前端源码，复用接口封装、登录状态和部分业务组件
// - dedupe 保证复用代码与本工程共用同一份 vue / pinia / element-plus 实例
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  plugins: [vue()],
  // 楼栋与事件数据含全部住户档案，不放 public：由后端 /api/twin/* 按登录账号裁剪后下发
  publicDir: false,
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
