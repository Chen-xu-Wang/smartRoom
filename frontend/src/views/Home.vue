<template>
  <div class="landing">
    <!-- Hero -->
    <section class="hero">
      <div class="hero-blob blob-1"></div>
      <div class="hero-blob blob-2"></div>
      <div class="hero-blob blob-3"></div>
      <div class="hero-grid" aria-hidden="true"></div>
      <div class="hero-inner">
        <div class="hero-text">
          <div class="hero-badge">🏗️ 基于 MiC 模块化建造 · 一房一码数字档案</div>
          <h1>
            让每一套房<br/>
            都拥有<span class="gradient-text">数字生命</span>
          </h1>
          <p class="hero-sub">
            筑维AI —— 从 MiC 模块数字身份码到维修数据回写，
            覆盖住宅运维全生命周期的智能助手。
            居民一句话报修，AI 读懂你的家。
          </p>
          <div class="hero-actions">
            <el-button type="primary" size="large" class="cta-main" @click="enter('resident')">
              <el-icon><Iphone /></el-icon>&nbsp;居民 · 扫码报修
            </el-button>
            <el-button size="large" class="cta-ghost" @click="enter('admin')">
              <el-icon><OfficeBuilding /></el-icon>&nbsp;管理员 · 物业工作台
            </el-button>
          </div>
          <div class="hero-stats">
            <div class="stat"><b>1</b><span>房一码<br/>终身数字档案</span></div>
            <div class="stat"><b>8</b><span>步闭环<br/>报修到回写</span></div>
            <div class="stat"><b>AI</b><span>驱动<br/>人工最终决策</span></div>
          </div>
        </div>

        <!-- 手机对话预览 -->
        <div class="hero-phone">
          <div class="phone-frame">
            <div class="phone-notch"></div>
            <div class="phone-title">💬 AI 报修助手</div>
            <div class="chat-bubble user">卫生间天花板渗水，最近下雨才出现</div>
            <div class="chat-bubble ai">已定位：3栋2单元1302室 主卫顶部排水管接口。<br/>该户型采用 PC 预制卫浴，疑似密封圈老化。已生成工单 <b>WO-1302-0831</b>，建议工种：水工 💧（置信度 92%）</div>
            <div class="chat-tags">
              <span>档案匹配 ✓</span><span>知识库 RAG ✓</span><span>待物业确认</span>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- 项目宣传海报 -->
    <section class="poster-section page-container">
      <h2 class="section-title">项目宣传海报</h2>
      <p class="section-sub">一张海报，读懂「一房一码」的智慧运维故事</p>
      <div class="poster">
        <div class="poster-bg"></div>
        <svg class="poster-svg" viewBox="0 0 900 500" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="一房一码宣传海报">
          <defs>
            <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stop-color="#0b1e46"/>
              <stop offset="60%" stop-color="#1e3a8a"/>
              <stop offset="100%" stop-color="#4c3a9e"/>
            </linearGradient>
            <linearGradient id="accent" x1="0" y1="0" x2="1" y2="0">
              <stop offset="0%" stop-color="#60a5fa"/>
              <stop offset="100%" stop-color="#c4b5fd"/>
            </linearGradient>
            <linearGradient id="glass" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0%" stop-color="rgba(255,255,255,0.16)"/>
              <stop offset="100%" stop-color="rgba(255,255,255,0.05)"/>
            </linearGradient>
          </defs>
          <rect width="900" height="500" fill="url(#sky)"/>
          <circle cx="770" cy="90" r="150" fill="rgba(96,165,250,0.18)"/>
          <circle cx="120" cy="420" r="130" fill="rgba(167,139,250,0.16)"/>
          <!-- 星点 -->
          <g fill="#93c5fd" opacity="0.7">
            <circle cx="90" cy="70" r="1.6"/><circle cx="180" cy="120" r="1.2"/>
            <circle cx="320" cy="60" r="1.4"/><circle cx="520" cy="80" r="1.2"/>
            <circle cx="640" cy="50" r="1.6"/><circle cx="840" cy="180" r="1.3"/>
          </g>
          <!-- 城市剪影 -->
          <g opacity="0.35" fill="#0b1e46">
            <rect x="0" y="330" width="70" height="170"/>
            <rect x="80" y="360" width="50" height="140"/>
            <rect x="760" y="350" width="60" height="150"/>
            <rect x="830" y="320" width="70" height="180"/>
          </g>
          <!-- 主视觉房屋 -->
          <g transform="translate(330,120)">
            <rect x="0" y="110" width="240" height="170" rx="10" fill="url(#glass)" stroke="rgba(147,197,253,0.7)" stroke-width="2"/>
            <path d="M-16 112 L120 18 L256 112" fill="none" stroke="url(#accent)" stroke-width="6" stroke-linejoin="round" stroke-linecap="round"/>
            <rect x="36" y="150" width="42" height="36" rx="4" fill="rgba(147,197,253,0.55)"/>
            <rect x="100" y="150" width="42" height="36" rx="4" fill="rgba(147,197,253,0.85)"/>
            <rect x="164" y="150" width="42" height="36" rx="4" fill="rgba(147,197,253,0.4)"/>
            <rect x="36" y="206" width="42" height="36" rx="4" fill="rgba(167,139,250,0.5)"/>
            <rect x="100" y="206" width="42" height="36" rx="4" fill="rgba(147,197,253,0.6)"/>
            <rect x="104" y="244" width="36" height="36" rx="4" fill="rgba(167,139,250,0.75)"/>
            <!-- QR 身份码 -->
            <g transform="translate(300,150)">
              <rect x="0" y="0" width="96" height="96" rx="10" fill="white" opacity="0.96"/>
              <g fill="#1e3a8a">
                <rect x="10" y="10" width="24" height="24" rx="4"/>
                <rect x="62" y="10" width="24" height="24" rx="4"/>
                <rect x="10" y="62" width="24" height="24" rx="4"/>
                <rect x="42" y="12" width="8" height="8"/>
                <rect x="42" y="30" width="8" height="8"/>
                <rect x="44" y="44" width="10" height="8"/>
                <rect x="42" y="62" width="24" height="8"/>
                <rect x="62" y="44" width="8" height="24"/>
                <rect x="44" y="78" width="8" height="8"/>
                <rect x="76" y="62" width="8" height="24"/>
              </g>
              <text x="48" y="118" text-anchor="middle" fill="#93c5fd" font-size="14" font-family="monospace">HS-1302</text>
            </g>
            <!-- 连接线 -->
            <path d="M240 198 C270 198 275 198 298 198" stroke="url(#accent)" stroke-width="2.5" stroke-dasharray="5 6" fill="none"/>
          </g>
          <!-- 标语 -->
          <text x="450" y="72" text-anchor="middle" fill="#ffffff" font-size="46" font-weight="800" letter-spacing="6">一房一码 · 智慧运维</text>
          <text x="450" y="106" text-anchor="middle" fill="url(#accent)" font-size="20" letter-spacing="3">筑维AI —— 让每一套房都拥有数字生命</text>
          <text x="450" y="462" text-anchor="middle" fill="rgba(255,255,255,0.75)" font-size="15" letter-spacing="2">扫码报修 → AI对话 → 档案调用 → 智能工单 → 维修回写</text>
        </svg>
      </div>
    </section>

    <!-- 全生命周期流程 -->
    <section class="flow-section">
      <div class="page-container">
        <h2 class="section-title">全生命周期 · 八步闭环</h2>
        <p class="section-sub">从模块出厂到维修回写，数字身份贯穿住宅的一生</p>
        <div class="flow-track">
          <div class="flow-node" v-for="(s, i) in flowSteps" :key="s.label" :style="{ animationDelay: i * 0.08 + 's' }">
            <div class="flow-dot">{{ i + 1 }}</div>
            <div class="flow-card">
              <div class="flow-emoji">{{ s.emoji }}</div>
              <div class="flow-label">{{ s.label }}</div>
              <div class="flow-desc">{{ s.desc }}</div>
            </div>
            <div class="flow-line" v-if="i < flowSteps.length - 1"></div>
          </div>
        </div>
      </div>
    </section>

    <!-- 核心特色 -->
    <section class="page-container feature-section">
      <h2 class="section-title">为什么选择筑维AI</h2>
      <p class="section-sub">AI 提效，人类决策 —— 让运维更聪明，也更可靠</p>
      <div class="feature-grid">
        <div class="feature-card" v-for="f in features" :key="f.title" :style="{ '--c': f.color }">
          <div class="feature-emoji">{{ f.emoji }}</div>
          <h3>{{ f.title }}</h3>
          <p>{{ f.desc }}</p>
        </div>
      </div>
    </section>

    <!-- 角色入口 -->
    <section class="entry-section">
      <div class="page-container">
        <h2 class="section-title">选择你的身份</h2>
        <p class="section-sub">居民与管理员各自拥有专属工作台</p>
        <div class="entry-grid">
          <div class="entry-card resident" @click="enter('resident')">
            <div class="entry-emoji">🏠</div>
            <h3>居民端</h3>
            <p>扫码报修 · AI对话报修 · 维修进度实时跟踪 · 房屋档案随时查</p>
            <span class="entry-link">立即体验 →</span>
          </div>
          <div class="entry-card admin" @click="enter('admin')">
            <div class="entry-emoji">🏢</div>
            <h3>管理员端</h3>
            <p>工单审核纠偏 · 智能派单 · 维修知识库 · 档案数据沉淀</p>
            <span class="entry-link">进入工作台 →</span>
          </div>
        </div>
      </div>
    </section>

    <!-- 底部 CTA -->
    <section class="final-cta">
      <h2>准备好让房子「活」起来了吗？</h2>
      <p>现在登录，体验一房一码带来的智慧运维之旅</p>
      <el-button type="primary" size="large" @click="enter(auth.isLoggedIn ? (auth.isAdmin ? 'admin' : 'resident') : 'login')">
        {{ auth.isLoggedIn ? '进入我的工作台' : '立即登录体验' }}
      </el-button>
    </section>
  </div>
</template>

<script setup>
import { Iphone, OfficeBuilding } from '@element-plus/icons-vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const auth = useAuthStore()

const flowSteps = [
  { emoji: '🏷️', label: '数字身份', desc: 'MiC模块赋码出厂' },
  { emoji: '📦', label: '房屋交付', desc: '一房一码建档' },
  { emoji: '📱', label: '扫码进入', desc: '居民扫身份码' },
  { emoji: '💬', label: 'AI对话', desc: '自然语言报修' },
  { emoji: '🗂️', label: '档案调用', desc: '设备管线全知晓' },
  { emoji: '🧠', label: '智能工单', desc: 'RAG匹配生成' },
  { emoji: '🛠️', label: '维修执行', desc: '物业审核派单' },
  { emoji: '🔄', label: '数据回写', desc: '档案持续成长' },
]

const features = [
  { emoji: '🤖', title: '对话式智能报修', desc: '像聊天一样描述故障，Agent 自动追问缺失细节，一句"卫生间渗水"也能精准定位', color: '#3b82f6' },
  { emoji: '🗂️', title: '一房一码数字档案', desc: '设备型号、管线走向、维修历史一站可查，维修师傅到场前就了解你的家', color: '#8b5cf6' },
  { emoji: '📚', title: 'RAG 运维知识库', desc: '基于维修手册与专业文档的检索增强生成，AI 建议有据可依，不凭空想象', color: '#06b6d4' },
  { emoji: '📋', title: '结构化智能工单', desc: '自动生成含置信度、建议工种的结构化工单，重复故障自动识别提醒', color: '#f59e0b' },
  { emoji: '👥', title: '人工审核纠偏', desc: 'AI 只提建议，物业最终拍板。人类决策 + AI 提效，双保险更安心', color: '#10b981' },
  { emoji: '🔄', title: '维修数据回写', desc: '每次维修结果写回数字档案，房子越住越"懂自己"，档案越用越聪明', color: '#ec4899' },
]

function enter(role) {
  if (!auth.isLoggedIn) {
    router.push({ path: '/login', query: role === 'admin' ? { role: 'admin' } : {} })
    return
  }
  if (role === 'admin') {
    if (auth.isAdmin) router.push('/property')
    else ElMessage.info('您当前是居民账号，如需管理端请联系管理员')
  } else if (role === 'login') {
    router.push(auth.isAdmin ? '/property' : '/scan')
  } else {
    router.push('/scan')
  }
}
</script>

<style scoped>
.landing { overflow-x: hidden; }

/* ---------- Hero ---------- */
.hero {
  position: relative;
  background: linear-gradient(140deg, #0b1e46 0%, #1e3a8a 55%, #3b2f8f 100%);
  color: white;
  padding: 90px 24px 70px;
  overflow: hidden;
}
.hero-blob {
  position: absolute;
  border-radius: 50%;
  filter: blur(90px);
  opacity: 0.45;
  animation: float 9s ease-in-out infinite;
}
.blob-1 { width: 480px; height: 480px; background: #2563eb; top: -160px; left: -120px; }
.blob-2 { width: 420px; height: 420px; background: #7c3aed; bottom: -160px; right: -100px; animation-delay: -3s; }
.blob-3 { width: 260px; height: 260px; background: #06b6d4; top: 40px; right: 30%; animation-delay: -6s; opacity: 0.3; }
@keyframes float {
  0%, 100% { transform: translateY(0) scale(1); }
  50% { transform: translateY(-24px) scale(1.05); }
}
.hero-grid {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(147,197,253,0.06) 1px, transparent 1px),
    linear-gradient(90deg, rgba(147,197,253,0.06) 1px, transparent 1px);
  background-size: 44px 44px;
  mask-image: radial-gradient(ellipse at center, black 30%, transparent 75%);
}
.hero-inner {
  position: relative;
  z-index: 1;
  max-width: 1160px;
  margin: 0 auto;
  display: flex;
  align-items: center;
  gap: 48px;
}
.hero-text { flex: 1.2; }
.hero-badge {
  display: inline-block;
  padding: 7px 16px;
  border-radius: 999px;
  border: 1px solid rgba(147,197,253,0.4);
  background: rgba(147,197,253,0.1);
  font-size: 13px;
  margin-bottom: 22px;
}
.hero h1 {
  font-size: 52px;
  line-height: 1.2;
  font-weight: 900;
  margin-bottom: 20px;
  letter-spacing: 1px;
}
.gradient-text {
  background: linear-gradient(90deg, #60a5fa, #c4b5fd, #67e8f9);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}
.hero-sub {
  font-size: 16px;
  line-height: 1.9;
  opacity: 0.85;
  max-width: 520px;
  margin-bottom: 30px;
}
.hero-actions { display: flex; gap: 14px; flex-wrap: wrap; margin-bottom: 40px; }
.cta-main {
  padding: 12px 28px;
  font-size: 16px;
  border-radius: 12px;
  background: linear-gradient(90deg, #3b82f6, #6366f1);
  border: none;
  box-shadow: 0 8px 24px rgba(59,130,246,0.45);
}
.cta-ghost {
  padding: 12px 28px;
  font-size: 16px;
  border-radius: 12px;
  background: rgba(255,255,255,0.08);
  border: 1px solid rgba(255,255,255,0.35);
  color: white;
  backdrop-filter: blur(6px);
}
.cta-ghost:hover { background: rgba(255,255,255,0.16); color: white; }
.hero-stats { display: flex; gap: 40px; }
.stat b {
  display: block;
  font-size: 34px;
  font-weight: 800;
  background: linear-gradient(90deg, #93c5fd, #c4b5fd);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}
.stat span { font-size: 12px; opacity: 0.75; line-height: 1.5; display: inline-block; margin-top: 4px; }

/* 手机模型 */
.hero-phone { flex: 0.9; display: flex; justify-content: center; }
.phone-frame {
  width: 320px;
  background: rgba(255,255,255,0.08);
  border: 1px solid rgba(255,255,255,0.22);
  border-radius: 28px;
  padding: 20px 16px 22px;
  backdrop-filter: blur(12px);
  box-shadow: 0 24px 60px rgba(0,0,0,0.35);
  animation: phoneFloat 6s ease-in-out infinite;
  position: relative;
}
@keyframes phoneFloat {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-12px); }
}
.phone-notch {
  width: 90px; height: 6px;
  border-radius: 3px;
  background: rgba(255,255,255,0.3);
  margin: 0 auto 14px;
}
.phone-title { font-size: 14px; font-weight: 700; margin-bottom: 14px; text-align: center; }
.chat-bubble {
  border-radius: 14px;
  padding: 10px 14px;
  font-size: 13px;
  line-height: 1.7;
  margin-bottom: 12px;
}
.chat-bubble.user {
  background: linear-gradient(90deg, #3b82f6, #6366f1);
  border-bottom-right-radius: 4px;
  margin-left: 40px;
}
.chat-bubble.ai {
  background: rgba(255,255,255,0.12);
  border-bottom-left-radius: 4px;
  margin-right: 30px;
}
.chat-tags { display: flex; gap: 8px; flex-wrap: wrap; }
.chat-tags span {
  font-size: 11px;
  padding: 4px 10px;
  border-radius: 999px;
  background: rgba(147,197,253,0.16);
  border: 1px solid rgba(147,197,253,0.35);
}

/* ---------- 通用段落 ---------- */
.page-container { max-width: 1160px; margin: 0 auto; padding: 0 24px; }
.section-title {
  text-align: center;
  font-size: 30px;
  font-weight: 800;
  margin: 0 0 8px;
}
.section-sub {
  text-align: center;
  color: var(--text-secondary, #6b7280);
  font-size: 14px;
  margin-bottom: 40px;
}

/* ---------- 海报 ---------- */
.poster-section { padding-top: 72px; }
.poster {
  position: relative;
  border-radius: 22px;
  overflow: hidden;
  box-shadow: 0 24px 60px rgba(30,58,138,0.25);
  transition: transform 0.3s;
}
.poster:hover { transform: translateY(-6px) scale(1.01); }
.poster-svg { display: block; width: 100%; height: auto; }

/* ---------- 流程 ---------- */
.flow-section {
  padding: 72px 0 40px;
  background: linear-gradient(180deg, #f5f7fb 0%, #ffffff 100%);
}
.flow-track {
  display: flex;
  justify-content: center;
  flex-wrap: wrap;
  gap: 6px;
}
.flow-node {
  display: flex;
  align-items: flex-start;
  animation: rise 0.6s ease both;
}
@keyframes rise {
  from { opacity: 0; transform: translateY(16px); }
  to { opacity: 1; transform: translateY(0); }
}
.flow-dot {
  width: 30px; height: 30px;
  border-radius: 50%;
  background: linear-gradient(135deg, #3b82f6, #6366f1);
  color: white;
  font-size: 13px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0 auto 10px;
  box-shadow: 0 4px 12px rgba(59,130,246,0.35);
}
.flow-card {
  width: 118px;
  background: white;
  border-radius: 14px;
  padding: 16px 10px;
  text-align: center;
  box-shadow: 0 2px 12px rgba(0,0,0,0.05);
  transition: transform 0.2s, box-shadow 0.2s;
}
.flow-card:hover { transform: translateY(-4px); box-shadow: 0 8px 20px rgba(59,130,246,0.15); }
.flow-emoji { font-size: 26px; margin-bottom: 8px; }
.flow-label { font-size: 13px; font-weight: 700; margin-bottom: 4px; }
.flow-desc { font-size: 11px; color: var(--text-secondary, #6b7280); }
.flow-line {
  width: 26px;
  height: 2px;
  margin-top: 55px;
  background: repeating-linear-gradient(90deg, #93c5fd 0 5px, transparent 5px 10px);
}

/* ---------- 特色 ---------- */
.feature-section { padding: 72px 24px; }
.feature-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 20px;
}
.feature-card {
  background: white;
  border-radius: 18px;
  padding: 28px 26px;
  border-top: 3px solid var(--c);
  box-shadow: 0 2px 14px rgba(0,0,0,0.05);
  transition: transform 0.25s, box-shadow 0.25s;
}
.feature-card:hover {
  transform: translateY(-6px);
  box-shadow: 0 14px 32px rgba(0,0,0,0.1);
}
.feature-emoji {
  width: 54px; height: 54px;
  border-radius: 14px;
  background: color-mix(in srgb, var(--c) 12%, white);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 26px;
  margin-bottom: 16px;
}
.feature-card h3 { font-size: 16px; margin-bottom: 8px; }
.feature-card p { font-size: 13px; color: var(--text-secondary, #6b7280); line-height: 1.8; }

/* ---------- 角色入口 ---------- */
.entry-section { padding: 40px 0 72px; }
.entry-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 24px;
  max-width: 860px;
  margin: 0 auto;
}
.entry-card {
  border-radius: 20px;
  padding: 36px 30px;
  color: white;
  cursor: pointer;
  transition: transform 0.25s, box-shadow 0.25s;
  position: relative;
  overflow: hidden;
}
.entry-card::after {
  content: '';
  position: absolute;
  width: 200px; height: 200px;
  border-radius: 50%;
  background: rgba(255,255,255,0.1);
  top: -80px; right: -60px;
}
.entry-card:hover { transform: translateY(-6px); box-shadow: 0 18px 40px rgba(0,0,0,0.2); }
.entry-card.resident { background: linear-gradient(135deg, #2563eb, #38bdf8); }
.entry-card.admin { background: linear-gradient(135deg, #7c3aed, #f59e0b); }
.entry-emoji { font-size: 40px; margin-bottom: 14px; }
.entry-card h3 { font-size: 20px; margin-bottom: 10px; }
.entry-card p { font-size: 13px; opacity: 0.9; line-height: 1.8; margin-bottom: 16px; }
.entry-link { font-size: 14px; font-weight: 700; }

/* ---------- 底部 CTA ---------- */
.final-cta {
  text-align: center;
  padding: 80px 24px;
  background: linear-gradient(140deg, #0b1e46, #1e3a8a);
  color: white;
}
.final-cta h2 { font-size: 30px; font-weight: 800; margin-bottom: 10px; }
.final-cta p { opacity: 0.8; margin-bottom: 26px; }
.final-cta .el-button {
  padding: 12px 36px;
  font-size: 16px;
  border-radius: 12px;
  background: linear-gradient(90deg, #3b82f6, #8b5cf6);
  border: none;
}

@media (max-width: 900px) {
  .hero-inner { flex-direction: column; }
  .hero h1 { font-size: 38px; }
  .entry-grid { grid-template-columns: 1fr; }
  .flow-line { display: none; }
}
</style>
