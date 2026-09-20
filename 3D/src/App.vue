<template>
  <!-- 独立运行入口（端口 5174）。内嵌到现有前端时用的是同一个 TwinRoot 组件 -->
  <TwinRoot />
</template>

<script setup>
import TwinRoot from './TwinRoot.vue'
</script>
