<template>
  <div class="home-page">
    <!-- Hero -->
    <section class="hero">
      <div class="hero-content">
        <h1>筑维<span class="highlight">AI</span></h1>
        <p class="hero-subtitle">基于「一房一码」数字档案的住宅智能运维助手</p>
        <p class="hero-desc">
          MiC模块数字身份码 → 房屋交付 → 一房一码数字档案 → AI智能报修 → 工单管理 → 维修回写
        </p>
        <div class="hero-actions">
          <el-button type="primary" size="large" @click="$router.push('/scan')">
            <el-icon><Iphone /></el-icon>&nbsp;扫码报修
          </el-button>
          <el-button size="large" @click="$router.push('/property')">
            <el-icon><OfficeBuilding /></el-icon>&nbsp;物业管理
          </el-button>
          <el-button size="large" @click="$router.push('/repair')">
            <el-icon><Tools /></el-icon>&nbsp;维修任务
          </el-button>
        </div>
      </div>
    </section>

    <!-- Flow Diagram -->
    <section class="page-container">
      <h2 class="section-title"><el-icon><Connection /></el-icon> 系统流程</h2>
      <div class="flow-diagram">
        <div class="flow-step" v-for="(step, i) in flowSteps" :key="i">
          <div class="flow-icon">{{ step.icon }}</div>
          <div class="flow-label">{{ step.label }}</div>
          <div class="flow-desc">{{ step.desc }}</div>
          <div class="flow-arrow" v-if="i < flowSteps.length - 1">→</div>
        </div>
      </div>
    </section>

    <!-- Feature Cards -->
    <section class="page-container">
      <h2 class="section-title"><el-icon><Grid /></el-icon> 核心功能</h2>
      <el-row :gutter="16">
        <el-col :span="8" v-for="feat in features" :key="feat.title">
          <div class="feature-card">
            <div class="feature-icon">{{ feat.icon }}</div>
            <h3>{{ feat.title }}</h3>
            <p>{{ feat.desc }}</p>
          </div>
        </el-col>
      </el-row>
    </section>

    <!-- House List -->
    <section class="page-container">
      <h2 class="section-title"><el-icon><House /></el-icon> 模拟房屋档案</h2>
      <el-row :gutter="16">
        <el-col :span="8" v-for="h in houses" :key="h.houseId">
          <el-card class="house-card" shadow="hover" @click="$router.push(`/chat/${h.houseId}`)">
            <template #header>
              <div class="house-card-header">
                <span>{{ h.building }}{{ h.room }}</span>
                <el-tag size="small" type="success">数字档案</el-tag>
              </div>
            </template>
            <p>户型：{{ h.layout }}</p>
            <p>面积：{{ h.area }}㎡</p>
            <p>楼层：{{ h.floor }}</p>
            <p class="house-id">数字身份：{{ h.digitalId }}</p>
          </el-card>
        </el-col>
      </el-row>
    </section>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { Iphone, OfficeBuilding, Tools, Connection, Grid, House } from '@element-plus/icons-vue'
import api from '../api'

const houses = ref([])

const flowSteps = [
  { icon: '1', label: '扫码进入', desc: '扫描一房一码' },
  { icon: '2', label: 'AI对话', desc: '自然语言报修' },
  { icon: '3', label: '调用档案', desc: '查询房屋设备' },
  { icon: '4', label: 'RAG检索', desc: '匹配维修知识' },
  { icon: '5', label: '生成工单', desc: 'AI结构化输出' },
  { icon: '6', label: '人工确认', desc: '物业审核纠偏' },
  { icon: '7', label: '维修执行', desc: '现场处理' },
  { icon: '8', label: '数据回写', desc: '档案持续增长' },
]

const features = [
  { icon: 'AI', title: '智能报修Agent', desc: '理解居民自然语言，提取故障信息，自动追问缺失细节' },
  { icon: 'DB', title: '一房一码档案', desc: '查询具体房屋的设备型号、管线位置、维修历史' },
  { icon: 'RAG', title: '运维知识库', desc: '基于维修手册和专业文档的检索增强生成' },
  { icon: 'WO', title: '智能工单', desc: 'AI生成结构化工单，附带置信度和建议工种' },
  { icon: 'HR', title: '人工审核纠偏', desc: '物业修改AI建议，人类决策系统执行' },
  { icon: 'DM', title: '维修回写', desc: '维修结果回写数字档案，档案持续增长' },
]

onMounted(async () => {
  try {
    const res = await api.getHouses()
    houses.value = res.data.houses
  } catch (e) {
    console.error('Failed to load houses:', e)
  }
})
</script>

<style scoped>
.hero {
  background: linear-gradient(135deg, #1e3a8a 0%, #2563eb 50%, #3b82f6 100%);
  color: white;
  padding: 60px 20px;
  text-align: center;
}
.hero h1 { font-size: 42px; font-weight: 800; margin-bottom: 8px; }
.hero .highlight { color: #93c5fd; }
.hero-subtitle { font-size: 20px; opacity: 0.95; margin-bottom: 8px; }
.hero-desc { font-size: 13px; opacity: 0.8; max-width: 600px; margin: 0 auto 24px; }
.hero-actions { display: flex; gap: 12px; justify-content: center; flex-wrap: wrap; }

.flow-diagram {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: center;
  padding: 20px 0;
}
.flow-step {
  display: flex;
  flex-direction: column;
  align-items: center;
  position: relative;
  min-width: 100px;
}
.flow-icon {
  width: 40px; height: 40px;
  border-radius: 50%;
  background: var(--primary-color);
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  margin-bottom: 8px;
}
.flow-label { font-size: 13px; font-weight: 600; }
.flow-desc { font-size: 11px; color: var(--text-secondary); text-align: center; }
.flow-arrow {
  position: absolute;
  right: -18px;
  top: 14px;
  color: var(--primary-color);
  font-size: 18px;
}

.feature-card {
  background: white;
  border-radius: 12px;
  padding: 24px;
  text-align: center;
  box-shadow: 0 1px 3px rgba(0,0,0,0.06);
  height: 100%;
  transition: transform 0.2s;
}
.feature-card:hover { transform: translateY(-4px); }
.feature-icon {
  width: 48px; height: 48px;
  border-radius: 12px;
  background: var(--primary-light);
  color: var(--primary-color);
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  font-size: 14px;
  margin: 0 auto 12px;
}
.feature-card h3 { font-size: 15px; margin-bottom: 8px; }
.feature-card p { font-size: 12px; color: var(--text-secondary); }

.house-card { cursor: pointer; transition: transform 0.2s; }
.house-card:hover { transform: translateY(-2px); }
.house-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-weight: 600;
}
.house-id { font-size: 11px; color: var(--text-secondary); font-family: monospace; }
</style>
