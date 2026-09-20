<template>
  <!-- 登录 UI 与现有前端登录页保持一致：角色切换滑块、带图标输入框、快捷登录标签 -->
  <el-dialog :model-value="modelValue" width="420px" align-center :show-close="false" class="login-dialog"
             @update:model-value="v => $emit('update:modelValue', v)">
    <div class="login-card">
      <div class="role-switch">
        <div class="role-slider" :class="{ admin: role === 'admin' }"></div>
        <button class="role-btn" :class="{ active: role === 'resident' }" @click="switchRole('resident')">
          <el-icon><User /></el-icon> 居民登录
        </button>
        <button class="role-btn" :class="{ active: role === 'admin' }" @click="switchRole('admin')">
          <el-icon><OfficeBuilding /></el-icon> 管理员登录
        </button>
      </div>

      <h2>{{ role === 'admin' ? '物业管理端' : '居民服务端' }}</h2>
      <p class="login-tip">{{ role === 'admin' ? '全小区态势 · 问题定位 · 建单派单' : '我的家 · 健康提醒 · 一键报修' }}</p>

      <el-alert v-if="!store.backendOnline" type="warning" :closable="false" show-icon class="offline"
                title="后端未连接，无法登录；小区数字孪生需要登录后按账号加载数据" />

      <el-form @submit.prevent="submit">
        <el-form-item>
          <el-input v-model="username" placeholder="用户名" size="large" clearable>
            <template #prefix><el-icon><User /></el-icon></template>
          </el-input>
        </el-form-item>
        <el-form-item>
          <el-input v-model="password" type="password" placeholder="密码" size="large" show-password @keyup.enter="submit">
            <template #prefix><el-icon><Lock /></el-icon></template>
          </el-input>
        </el-form-item>
        <el-button type="primary" size="large" class="login-btn" :loading="loading" :disabled="!store.backendOnline" native-type="submit">
          登 录
        </el-button>
      </el-form>

      <div class="demo-accounts">
        <p>快捷登录（点击自动填充）</p>
        <div class="demo-chips">
          <el-tag class="demo-chip" @click="fill('resident1', '123456', 'resident')">居民：resident1 / 123456</el-tag>
          <el-tag class="demo-chip" type="warning" @click="fill('admin', '123456', 'admin')">管理员：admin / 123456</el-tag>
          <el-tag class="demo-chip" type="info" @click="fill('repairer1', '123456', 'admin')">维修：repairer1 / 123456</el-tag>
        </div>
      </div>

      <button class="back-home" @click="$emit('update:modelValue', false)">
        <el-icon><ArrowLeft /></el-icon> 暂不登录
      </button>
    </div>
  </el-dialog>
</template>

<script setup>
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { User, Lock, OfficeBuilding, ArrowLeft } from '@element-plus/icons-vue'
import { useAuthStore } from '@app/stores/auth.js'
import { useTwinStore } from '../stores/twin'

defineProps({ modelValue: Boolean })
const emit = defineEmits(['update:modelValue'])
const auth = useAuthStore()
const store = useTwinStore()

const role = ref('resident')
const username = ref('')
const password = ref('')
const loading = ref(false)

function switchRole(r) {
  role.value = r
  fill(r === 'admin' ? 'admin' : 'resident1', '123456')
}
function fill(u, p, r) {
  username.value = u
  password.value = p
  if (r) role.value = r
}

async function submit() {
  if (!username.value || !password.value) { ElMessage.warning('请输入用户名和密码'); return }
  loading.value = true
  // 与前端登录页一致：居民页签只允许居民账号，管理员页签允许物业/维修/管理员
  const res = await auth.login({ username: username.value.trim(), password: password.value, role: role.value })
  loading.value = false
  if (!res.ok) { ElMessage.error(res.msg); return }
  // 小区模型与事件按账号裁剪后下发：登录后整页刷新，重新加载该账号可见的数据
  ElMessage.success(`欢迎回来，${res.user.name}`)
  location.reload()
  emit('update:modelValue', false)
}
</script>

<style scoped>
.login-dialog :deep(.el-dialog__header) { display: none; }
.login-dialog :deep(.el-dialog__body) { padding: 0; }
.login-dialog :deep(.el-form-item) { margin-bottom: 18px; }
.login-card { padding: 32px 32px 22px; border-radius: var(--radius-xl, 20px); background: var(--bg-card, #fff); }
.role-switch { position: relative; display: flex; background: var(--bg-muted, #f0f2f7); border-radius: 12px; padding: 4px; margin-bottom: 24px; }
.role-slider {
  position: absolute; top: 4px; bottom: 4px; left: 4px; width: calc(50% - 4px);
  background: var(--bg-card, #fff); border-radius: 9px; box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08); transition: transform 0.25s ease;
}
.role-slider.admin { transform: translateX(100%); }
.role-btn {
  flex: 1; position: relative; z-index: 1; display: flex; align-items: center; justify-content: center; gap: 6px;
  border: none; background: transparent; padding: 10px 0; font-size: 14px; font-weight: 600;
  color: var(--text-secondary, #909399); cursor: pointer; transition: color 0.2s; font-family: inherit;
}
.role-btn.active { color: var(--primary-color, #4F46E5); }
.login-card h2 { font-size: 22px; margin: 0 0 6px; color: var(--text-primary, #0F172A); }
.login-tip { font-size: 13px; color: var(--text-secondary, #909399); margin-bottom: 20px; }
.offline { margin-bottom: 16px; }
.login-btn { width: 100%; margin-top: 4px; letter-spacing: 8px; }
.demo-accounts { margin-top: 22px; text-align: center; }
.demo-accounts p { font-size: 12px; color: var(--text-secondary, #909399); margin-bottom: 8px; }
.demo-chips { display: flex; justify-content: center; gap: 8px; flex-wrap: wrap; }
.demo-chip { cursor: pointer; }
.back-home {
  display: inline-flex; align-items: center; gap: 4px; margin-top: 18px; padding: 0;
  font-size: 13px; color: var(--text-secondary, #909399); background: none; border: none; cursor: pointer; font-family: inherit;
}
.back-home:hover { color: var(--primary-color, #4F46E5); }
</style>
