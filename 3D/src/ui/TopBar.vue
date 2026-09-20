<template>
  <div class="topbar panel" :class="{ embedded }">
    <div v-if="!embedded" class="brand">
      <span class="logo">筑维AI</span>
      <span class="name">小区数字孪生</span>
    </div>
    <div class="roles">
      <!-- 只显示当前账号有权使用的视角 -->
      <button v-for="r in roles" :key="r.id" class="role" :class="{ on: store.role === r.id }" @click="store.setRole(r.id)">
        <el-icon><component :is="r.icon" /></el-icon>{{ r.label }}
      </button>
    </div>
    <el-tag v-if="store.readOnly" size="small" type="info" effect="plain">只读</el-tag>
    <div class="tools">
      <el-button type="danger" size="small" icon="Aim" :loading="store.locating" @click="store.locateTop()">一键定位</el-button>
      <el-segmented :model-value="store.mode" :options="modeOptions" size="small" @change="v => store.setMode(v, api)" />
      <el-tooltip :content="store.backendOnline ? '后端在线' : '后端未连接，使用演示样例'">
        <span class="dot" :class="{ on: store.backendOnline }"></span>
      </el-tooltip>
      <el-tag v-if="embedded" size="small" type="warning" effect="plain">演示数据</el-tag>
      <el-button v-else size="small" text :icon="'Back'" title="返回现有系统（工单、报修、派单）" @click="backToApp">控制台</el-button>
      <el-button size="small" circle :icon="store.theme === 'day' ? 'Moon' : 'Sunny'" :title="store.theme === 'day' ? '切换夜间科技风' : '切换白天沙盘风'" @click="toggleTheme" />
      <el-dropdown v-if="store.loginUser && !embedded" @command="c => c === 'logout' && logout()">
        <span class="user-chip">
          <el-icon><Avatar /></el-icon>{{ store.loginUser.name }}
          <el-tag size="small" :type="userTag">{{ store.loginUser.roleLabel }}</el-tag>
        </span>
        <template #dropdown><el-dropdown-menu><el-dropdown-item command="logout">退出登录</el-dropdown-item></el-dropdown-menu></template>
      </el-dropdown>
      <el-button v-else-if="!embedded" size="small" class="login-btn" type="primary" round @click="$emit('login')">登录</el-button>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import api from '@app/api/index.js'
import { useAuthStore } from '@app/stores/auth.js'
import { useTwinStore, ROLES } from '../stores/twin'
import { Avatar } from '@element-plus/icons-vue'

defineProps({ embedded: { type: Boolean, default: false } })
defineEmits(['login'])
const store = useTwinStore()
const auth = useAuthStore()
const roles = computed(() => ROLES.filter(r => store.allowedRoles.includes(r.id)))
const modeOptions = computed(() => [{ label: '演示样例', value: 'demo' }, { label: '联机数据', value: 'live', disabled: !store.backendOnline }])
const toggleTheme = () => store.applyTheme(store.theme === 'day' ? 'night' : 'day')
const userTag = computed(() => ({ repairer: 'info', property: 'warning', owner: 'success' }[store.loginUser?.role] || 'info'))
// 回到控制台（现有系统，端口 5173）
const backToApp = () => {
  const base = import.meta.env.VITE_APP_URL || `${location.protocol}//${location.hostname}:5173/`
  // 登录态含访问令牌，不放进 URL；控制台（5173）需要单独登录
  window.open(base, 'zhuwei-app')
}
const logout = () => store.signOut()
</script>

<style scoped>
.topbar.embedded .roles { margin-left: 0; }
.topbar { position: absolute; top: 12px; left: 12px; right: 12px; height: 52px; display: flex; align-items: center; gap: 16px; padding: 0 14px; }
.brand { display: flex; align-items: center; gap: 8px; white-space: nowrap; }
.logo {
  font-weight: 800; font-size: 20px; letter-spacing: -0.02em;
  background: linear-gradient(135deg, var(--primary-color, #4F46E5), #7C3AED);
  -webkit-background-clip: text; background-clip: text; color: transparent;
}
.user-chip { display: inline-flex; align-items: center; gap: 6px; font-size: 14px; color: var(--panel-fg); cursor: pointer; outline: none; }
.login-btn { padding: 6px 20px; }
.name { font-weight: 500; font-size: 12px; color: var(--text-secondary); margin-left: 4px; }
.roles { display: flex; gap: 4px; margin: 0 auto; background: rgba(120, 140, 160, 0.12); padding: 3px; border-radius: 10px; }
.role { border: 0; background: transparent; color: var(--panel-fg); padding: 6px 14px; border-radius: 8px; cursor: pointer; font-size: 14px; display: flex; align-items: center; gap: 4px; font-family: inherit; }
.role.on { background: var(--accent); color: #fff; font-weight: 700; box-shadow: 0 2px 8px rgba(22, 119, 255, 0.35); }
.tools { display: flex; align-items: center; gap: 8px; }
.dot { width: 8px; height: 8px; border-radius: 50%; background: #bfbfbf; display: inline-block; }
.dot.on { background: #52c41a; box-shadow: 0 0 6px #52c41a; }
@media (max-width: 1280px) { .name, .brand .el-tag { display: none; } }
</style>
