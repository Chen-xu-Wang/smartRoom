<template>
  <div class="login-page">
    <!-- 左侧宣传海报区 -->
    <div class="poster-side">
      <div class="poster-glow glow-1"></div>
      <div class="poster-glow glow-2"></div>
      <div class="poster-content">
        <div class="poster-logo">
          <svg viewBox="0 0 48 48" width="52" height="52">
            <defs>
              <linearGradient id="lg" x1="0" y1="0" x2="1" y2="1">
                <stop offset="0%" stop-color="#60a5fa"/>
                <stop offset="100%" stop-color="#a78bfa"/>
              </linearGradient>
            </defs>
            <path d="M24 4 L44 20 V44 H28 V30 H20 V44 H4 V20 Z" fill="none" stroke="url(#lg)" stroke-width="3" stroke-linejoin="round"/>
            <circle cx="24" cy="22" r="4" fill="url(#lg)"/>
            <path d="M24 26 v8 M20 30 h8" stroke="url(#lg)" stroke-width="2.5" stroke-linecap="round"/>
          </svg>
          <span>筑维AI</span>
        </div>
        <h1>让每一套房<br/>都拥有<span>数字生命</span></h1>
        <p class="poster-desc">
          基于「一房一码」数字档案的住宅智能运维平台，从 MiC 模块数字身份到维修回写，全生命周期守护你的家。
        </p>
        <ul class="poster-points">
          <li><el-icon><MagicStick /></el-icon> AI 对话式报修，像聊天一样简单</li>
          <li><el-icon><Coin /></el-icon> 一房一码档案，设备管线一目了然</li>
          <li><el-icon><DataLine /></el-icon> 维修数据回写，档案越用越聪明</li>
        </ul>
        <!-- 装饰性房屋插画 -->
        <svg class="poster-art" viewBox="0 0 520 200" fill="none">
          <g opacity="0.9">
            <rect x="40" y="90" width="120" height="100" rx="6" fill="rgba(255,255,255,0.08)" stroke="rgba(147,197,253,0.5)"/>
            <rect x="180" y="50" width="140" height="140" rx="6" fill="rgba(255,255,255,0.10)" stroke="rgba(147,197,253,0.7)"/>
            <rect x="340" y="110" width="140" height="80" rx="6" fill="rgba(255,255,255,0.08)" stroke="rgba(167,139,250,0.5)"/>
            <rect x="200" y="70" width="26" height="20" rx="2" fill="rgba(147,197,253,0.5)"/>
            <rect x="240" y="70" width="26" height="20" rx="2" fill="rgba(147,197,253,0.35)"/>
            <rect x="200" y="104" width="26" height="20" rx="2" fill="rgba(147,197,253,0.35)"/>
            <rect x="240" y="104" width="26" height="20" rx="2" fill="rgba(147,197,253,0.6)"/>
            <rect x="206" y="150" width="30" height="40" rx="3" fill="rgba(167,139,250,0.55)"/>
            <circle cx="100" cy="130" r="14" stroke="rgba(147,197,253,0.6)"/>
            <path d="M94 130 l5 5 9 -10" stroke="#93c5fd" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
            <circle cx="410" cy="140" r="14" stroke="rgba(167,139,250,0.7)"/>
            <path d="M410 133 v14 M403 140 h14" stroke="#c4b5fd" stroke-width="2.5" stroke-linecap="round"/>
            <path class="pulse-line" d="M40 200 H480" stroke="rgba(147,197,253,0.6)" stroke-width="2" stroke-dasharray="6 8"/>
          </g>
        </svg>
      </div>
    </div>

    <!-- 右侧登录表单区 -->
    <div class="form-side">
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
        <p class="login-tip">{{ role === 'admin' ? '工单审核 · 派单管理 · 档案运维' : '扫码报修 · AI对话 · 维修进度跟踪' }}</p>

        <el-form @submit.prevent="handleLogin">
          <el-form-item>
            <el-input v-model="username" placeholder="用户名" size="large" clearable>
              <template #prefix><el-icon><User /></el-icon></template>
            </el-input>
          </el-form-item>
          <el-form-item>
            <el-input v-model="password" type="password" placeholder="密码" size="large" show-password @keyup.enter="handleLogin">
              <template #prefix><el-icon><Lock /></el-icon></template>
            </el-input>
          </el-form-item>
          <el-button type="primary" size="large" class="login-btn" :loading="loading" native-type="submit">
            登 录
          </el-button>
        </el-form>

        <div class="demo-accounts">
          <p>快捷登录（点击自动填充）</p>
          <div class="demo-chips">
            <el-tag class="demo-chip" @click="fill('resident1', '123456')">居民：resident1 / 123456</el-tag>
            <el-tag class="demo-chip" type="warning" @click="fill('admin', '123456')">管理员：admin / 123456</el-tag>
            <el-tag class="demo-chip" type="info" @click="fill('repairer1', '123456')">维修：repairer1 / 123456</el-tag>
          </div>
        </div>

        <router-link to="/" class="back-home">
          <el-icon><ArrowLeft /></el-icon> 返回首页
        </router-link>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const auth = useAuthStore()

const role = ref('resident')
const username = ref('')
const password = ref('')
const loading = ref(false)

function switchRole(r) {
  role.value = r
  fill(r === 'admin' ? 'admin' : 'resident1', '123456')
}

function fill(u, p) {
  username.value = u
  password.value = p
}

async function handleLogin() {
  if (!username.value || !password.value) {
    ElMessage.warning('请输入用户名和密码')
    return
  }
  loading.value = true
  const res = await auth.login({ username: username.value.trim(), password: password.value, role: role.value })
  loading.value = false
  if (res.ok) {
    ElMessage.success(`欢迎回来，${res.user.name}`)
    const redirect = router.currentRoute.value.query.redirect
    if (redirect) { router.push(String(redirect)); return }
    // 按真实后端角色分流：维修工→工单，居民→报修，物业/管理员→物业后台
    const r = res.user.backendRole
    if (r === 'REPAIRER') router.push('/repair')
    else if (r === 'RESIDENT') router.push('/scan')
    else router.push('/property')
  } else {
    ElMessage.error(res.msg)
  }
}
</script>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
}
.login-page :deep(.el-form-item) { margin-bottom: 20px; }

/* 左侧海报 */
.poster-side {
  flex: 1.1;
  position: relative;
  background: linear-gradient(150deg, #0f2350 0%, #1e3a8a 45%, #3b2f8f 100%);
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}
.poster-glow {
  position: absolute;
  border-radius: 50%;
  filter: blur(80px);
  opacity: 0.5;
}
.glow-1 { width: 420px; height: 420px; background: #2563eb; top: -120px; left: -100px; }
.glow-2 { width: 380px; height: 380px; background: #7c3aed; bottom: -120px; right: -80px; }
.poster-content {
  position: relative;
  z-index: 1;
  max-width: 560px;
  padding: 48px 40px;
}
.poster-logo {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 24px;
  font-weight: 800;
  margin-bottom: 40px;
}
.poster-content h1 {
  font-size: 44px;
  line-height: 1.25;
  font-weight: 800;
  margin-bottom: 18px;
}
.poster-content h1 span {
  background: linear-gradient(90deg, #60a5fa, #c4b5fd);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}
.poster-desc {
  font-size: 15px;
  line-height: 1.8;
  opacity: 0.85;
  margin-bottom: 28px;
}
.poster-points {
  list-style: none;
  padding: 0;
  margin: 0 0 36px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.poster-points li {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 14px;
  opacity: 0.92;
}
.poster-points .el-icon { color: #93c5fd; }
.poster-art { width: 100%; }
.pulse-line { animation: dash 3s linear infinite; }
@keyframes dash { to { stroke-dashoffset: -56; } }

/* 右侧表单 */
.form-side {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f5f7fb;
  padding: 40px 24px;
}
.login-card {
  width: 100%;
  max-width: 420px;
  background: white;
  border-radius: 20px;
  padding: 40px 36px 28px;
  box-shadow: 0 12px 40px rgba(30, 58, 138, 0.10);
}
.role-switch {
  position: relative;
  display: flex;
  background: #f0f2f7;
  border-radius: 12px;
  padding: 4px;
  margin-bottom: 28px;
}
.role-slider {
  position: absolute;
  top: 4px;
  bottom: 4px;
  left: 4px;
  width: calc(50% - 4px);
  background: white;
  border-radius: 9px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.08);
  transition: transform 0.25s ease;
}
.role-slider.admin { transform: translateX(100%); }
.role-btn {
  flex: 1;
  position: relative;
  z-index: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  border: none;
  background: transparent;
  padding: 10px 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-secondary, #909399);
  cursor: pointer;
  transition: color 0.2s;
}
.role-btn.active { color: var(--primary-color, #2563eb); }

.login-card h2 { font-size: 22px; margin: 0 0 6px; }
.login-tip { font-size: 13px; color: var(--text-secondary, #909399); margin-bottom: 24px; }
.login-btn { width: 100%; margin-top: 4px; letter-spacing: 8px; }

.demo-accounts { margin-top: 24px; text-align: center; }
.demo-accounts p { font-size: 12px; color: var(--text-secondary, #909399); margin-bottom: 8px; }
.demo-chips { display: flex; justify-content: center; gap: 8px; flex-wrap: wrap; }
.demo-chip { cursor: pointer; }

.back-home {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-top: 20px;
  font-size: 13px;
  color: var(--text-secondary, #909399);
  text-decoration: none;
}
.back-home:hover { color: var(--primary-color, #2563eb); }

@media (max-width: 860px) {
  .poster-side { display: none; }
}
</style>
