<template>
  <!-- 3D 数字孪生：作为本前端的一个页面内嵌，顶部导航与页脚仍是现有前端的 -->
  <TwinRoot embedded :query="route.query" />
</template>

<script setup>
import { useRoute } from 'vue-router'
import TwinRoot from '@twin/TwinRoot.vue'
import '@twin/styles.css'
// 夜间科技风用到 Element Plus 的暗色变量（离开页面时会移除 html.dark）
import 'element-plus/theme-chalk/dark/css-vars.css'

const route = useRoute()
</script>
