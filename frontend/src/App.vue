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
          <!-- 居民 -->
          <router-link v-if="auth.isResident" to="/scan" class="nav-item">扫码报修</router-link>
          <!-- 物业/管理员 -->
          <template v-if="auth.isProperty">
            <router-link to="/property" class="nav-item">物业管理</router-link>
            <router-link to="/admin/houses" class="nav-item">房屋管理</router-link>
            <router-link to="/admin/users" class="nav-item">人员管理</router-link>
            <router-link to="/repair" class="nav-item">维修调度</router-link>
          </template>
          <!-- 维修工：仅看自己工单 -->
          <router-link v-if="auth.isRepairer" to="/repair" class="nav-item">我的工单</router-link>
          <template v-if="auth.isLoggedIn">
            <el-dropdown @command="onUserCommand">
              <span class="user-chip">
                <el-icon><Avatar /></el-icon>
                {{ auth.user.name }}
                <el-tag size="small" :type="auth.isRepairer ? 'info' : auth.isProperty ? 'warning' : 'success'">
                  {{ auth.roleLabel }}
                </el-tag>
              </span>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="logout">退出登录</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </template>
          <router-link v-else to="/login" class="nav-item nav-login">登录</router-link>
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
import { HomeFilled, Avatar } from '@element-plus/icons-vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from './stores/auth'

const router = useRouter()
const auth = useAuthStore()

function onUserCommand(cmd) {
  if (cmd === 'logout') {
    auth.logout()
    ElMessage.success('已退出登录')
    router.push('/')
  }
}
</script>

<style scoped>
.app-container {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}
.app-header {
  background: rgba(255,255,255,0.85);
  backdrop-filter: blur(16px) saturate(180%);
  border-bottom: 1px solid rgba(226,232,240,0.8);
  position: sticky;
  top: 0;
  z-index: 100;
  box-shadow: 0 1px 3px rgba(15,23,42,0.04);
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
  font-weight: 800;
  letter-spacing: -0.02em;
  background: linear-gradient(135deg, var(--primary-color), #7C3AED);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}
.logo-sub {
  font-size: 12px;
  color: var(--text-secondary);
  margin-left: 4px;
}
.nav-menu {
  display: flex;
  align-items: center;
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
.nav-login {
  color: white;
  background: var(--primary-color);
  border-radius: 18px;
  padding: 6px 20px;
  border-bottom: none;
}
.nav-login:hover, .nav-login.router-link-active {
  color: white;
  border-bottom-color: transparent;
  opacity: 0.9;
}
.user-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
  color: var(--text-color, #303133);
  cursor: pointer;
  outline: none;
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
