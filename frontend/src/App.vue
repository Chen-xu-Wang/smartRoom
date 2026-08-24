<template>
  <div class="app-container">
    <header class="app-header">
      <div class="header-inner">
        <div class="logo" @click="$router.push('/')">
          <el-icon size="24" color="#2563eb"><HomeFilled /></el-icon>
          <span class="logo-text">筑维AI</span>
          <span class="logo-sub">一房一码住宅智能运维助手</span>
        </div>
        <nav class="nav-menu">
          <router-link to="/" class="nav-item">首页</router-link>
          <router-link to="/scan" class="nav-item">扫码报修</router-link>
          <router-link to="/property" class="nav-item">物业管理</router-link>
          <router-link to="/repair" class="nav-item">维修任务</router-link>
        </nav>
      </div>
    </header>
    <main class="app-main">
      <router-view />
    </main>
    <footer class="app-footer">
      <p>筑维AI Demo | 基于中国建筑国际"一房一码"数字档案 | AI辅助，人类决策</p>
    </footer>
  </div>
</template>

<script setup>
import { HomeFilled } from '@element-plus/icons-vue'
</script>

<style scoped>
.app-container {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}
.app-header {
  background: white;
  border-bottom: 1px solid var(--border-color);
  position: sticky;
  top: 0;
  z-index: 100;
}
.header-inner {
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 20px;
  height: 60px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.logo {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}
.logo-text {
  font-size: 20px;
  font-weight: 700;
  color: var(--primary-color);
}
.logo-sub {
  font-size: 12px;
  color: var(--text-secondary);
  margin-left: 4px;
}
.nav-menu {
  display: flex;
  gap: 24px;
}
.nav-item {
  text-decoration: none;
  color: var(--text-secondary);
  font-size: 14px;
  font-weight: 500;
  padding: 6px 0;
  border-bottom: 2px solid transparent;
  transition: all 0.2s;
}
.nav-item:hover, .nav-item.router-link-active {
  color: var(--primary-color);
  border-bottom-color: var(--primary-color);
}
.app-main {
  flex: 1;
}
.app-footer {
  text-align: center;
  padding: 16px;
  color: var(--text-secondary);
  font-size: 12px;
  background: white;
  border-top: 1px solid var(--border-color);
}
</style>
