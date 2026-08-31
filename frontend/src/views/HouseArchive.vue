<template>
  <div class="page-container" v-if="house">
    <!-- House Header Premium -->
    <div class="card house-header-card" style="padding:0; overflow:hidden; border:none; box-shadow: var(--shadow-lg);">
      <div style="background: linear-gradient(135deg, #4F46E5 0%, #7C3AED 55%, #06B6D4 100%); padding:28px; color:white; position:relative; overflow:hidden">
        <div style="position:absolute; width:260px; height:260px; background:rgba(255,255,255,0.08); border-radius:50%; top:-80px; right:-60px;"></div>
        <div style="position:absolute; width:180px; height:180px; background:rgba(255,255,255,0.06); border-radius:50%; bottom:-40px; left:40%;"></div>
        <div style="position:relative; display:flex; justify-content:space-between; gap:20px; flex-wrap:wrap">
          <div>
            <div style="display:flex; align-items:center; gap:10px; margin-bottom:10px">
              <div style="width:42px; height:42px; background:rgba(255,255,255,0.15); backdrop-filter:blur(8px); border-radius:12px; display:grid; place-items:center"><el-icon size="22"><House /></el-icon></div>
              <div>
                <h2 style="font-size:26px; font-weight:800; letter-spacing:-0.02em; line-height:1">{{ house.building }}{{ house.room }}</h2>
                <p style="opacity:0.85; font-size:13px; margin-top:4px">{{ house.layout }} · {{ house.area }}㎡ · {{ house.floor }}</p>
              </div>
              <el-tag effect="dark" round size="small" style="background:rgba(255,255,255,0.2); border:none; color:white; backdrop-filter:blur(6px)">一房一码</el-tag>
            </div>
            <div style="display:flex; gap:8px; flex-wrap:wrap; margin-top:14px">
              <span style="background:rgba(255,255,255,0.14); padding:6px 12px; border-radius:999px; font-size:12px; backdrop-filter:blur(6px)">MiC {{ house.micModuleId }}</span>
              <span style="background:rgba(255,255,255,0.14); padding:6px 12px; border-radius:999px; font-size:12px; backdrop-filter:blur(6px)">{{ house.digitalId }}</span>
            </div>
          </div>
          <div style="background:rgba(255,255,255,0.12); backdrop-filter:blur(12px); border:1px solid rgba(255,255,255,0.15); border-radius:16px; padding:16px 20px; min-width:220px">
            <div class="id-row" style="color:rgba(255,255,255,0.9)"><span style="opacity:0.7">一房一码：</span><code style="color:white; background:rgba(255,255,255,0.15); padding:2px 8px; border-radius:6px">{{ house.qrCode }}</code></div>
            <div class="id-row" style="color:rgba(255,255,255,0.85); margin-top:6px"><span style="opacity:0.7">交付：</span>{{ house.deliveryDate }} <span style="opacity:0.5">·</span> 生产 {{ house.productionDate }}</div>
            <div style="margin-top:10px; display:flex; gap:8px">
              <el-button size="small" style="background:white; color:#4F46E5; border:none; font-weight:600" @click="$router.push(`/chat/${houseId}`)">AI报修</el-button>
              <el-tag v-if="warrantyStatus" :type="warrantyStatus.type" effect="dark" round size="small" style="border:none">{{ warrantyStatus.label }}</el-tag>
            </div>
          </div>
        </div>
      </div>
      <!-- Warranty strip -->
      <div v-if="house.warranty" style="display:flex; gap:16px; align-items:center; padding:16px 24px; background:#F8FAFC; border-top:1px solid var(--border-light); flex-wrap:wrap">
        <el-icon color="#059669"><CircleCheck /></el-icon>
        <div style="flex:1; min-width:200px">
          <div style="font-weight:600; font-size:13px">质保信息 · {{ house.warranty.coverage || '主体结构终身保修' }}</div>
          <div style="font-size:12px; color:var(--text-secondary)">{{ house.warranty.startDate }} 至 {{ house.warranty.endDate }} <span v-if="warrantyStatus" :style="{color: warrantyStatus.color}">· {{ warrantyStatus.detail }}</span></div>
        </div>
        <el-progress v-if="warrantyPercent!==null" :percentage="warrantyPercent" :width="56" type="circle" :stroke-width="6" :color="warrantyStatus.color" />
      </div>
    </div>

    <!-- Components by Category -->
    <div class="card" v-for="(cat, key) in categoryMap" :key="key">
      <h3 class="section-title">
        <el-icon><component :is="cat.icon" /></el-icon>
        {{ cat.label }}
        <span class="count-badge">{{ (houseComponents?.[key] || []).length }}项</span>
      </h3>
      <el-table :data="houseComponents?.[key] || []" border size="small">
        <el-table-column prop="id" label="设备编号" width="160" />
        <el-table-column prop="name" label="名称" width="120" />
        <el-table-column prop="spec" label="规格型号" width="120" />
        <el-table-column prop="location" label="位置" />
        <el-table-column prop="manufacturer" label="厂家" width="100" />
        <el-table-column prop="installDate" label="安装日期" width="120" />
        <el-table-column prop="remark" label="备注" width="120" />
      </el-table>
    </div>

    <!-- Pipeline Layout -->
    <div class="card">
      <h3 class="section-title"><el-icon><Guide /></el-icon> 管线位置布局</h3>
      <div v-for="(pipes, area) in house.pipelineLayout" :key="area" class="pipeline-area">
        <h4>{{ area }}</h4>
        <div v-for="(v, k) in pipes" :key="k" class="pipe-row">
          <span class="pipe-label">{{ k }}：</span>
          <span>{{ v }}</span>
        </div>
      </div>
    </div>

    <!-- Maintenance History -->
    <div class="card">
      <h3 class="section-title">
        <el-icon><Clock /></el-icon> 维修历史记录
        <span class="count-badge">{{ maintenanceHistory.length }}条</span>
      </h3>
      <el-alert
        v-for="w in repeatWarnings"
        :key="w"
        type="warning"
        :closable="false"
        style="margin-bottom: 8px"
      >{{ w }}</el-alert>
      <el-timeline v-if="maintenanceHistory.length">
        <el-timeline-item
          v-for="r in maintenanceHistory"
          :key="r.id"
          :timestamp="r.date"
          placement="top"
        >
          <div class="history-item">
            <strong>{{ r.fault }}</strong> - {{ r.cause }}
            <div class="history-detail">{{ r.action }} | 维修人：{{ r.repairPerson }} | 结果：{{ r.result }}</div>
          </div>
        </el-timeline-item>
      </el-timeline>
      <el-empty v-else description="暂无维修记录" />
    </div>

    <!-- Actions -->
    <div class="card" style="text-align: center">
      <el-button type="primary" @click="$router.push(`/chat/${houseId}`)">
        <el-icon><ChatLineRound /></el-icon> AI智能报修
      </el-button>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { House, Lightning, SetUp, WindPower, Tools, Guide, Clock, ChatLineRound, CircleCheck } from '@element-plus/icons-vue'
import api from '../api'

const route = useRoute()
const houseId = route.params.houseId
const house = ref(null)
// 设备清单来自独立接口 GET /api/houses/{id}/components（house 详情不返回 components）
const houseComponents = ref({})
const maintenanceHistory = ref([])
const repeatWarnings = ref([])

const categoryMap = {
  plumbing: { label: '给排水设备', icon: 'Lightning' },
  electrical: { label: '电气设备', icon: 'SetUp' },
  bathroom: { label: '卫浴设备', icon: 'House' },
  hvac: { label: '空调设备', icon: 'WindPower' },
  doors_windows: { label: '门窗设备', icon: 'Tools' },
}

const warrantyStatus = computed(()=>{
  const w = house.value?.warranty
  if(!w?.endDate) return null
  const now = new Date()
  const end = new Date(w.endDate)
  const start = w.startDate ? new Date(w.startDate) : now
  const total = end - start
  const left = end - now
  const expired = left <= 0
  const daysLeft = Math.ceil(left/86400000)
  if(expired) return { label:'已过保', type:'danger', color:'#DC2626', detail:`已过期 ${Math.abs(daysLeft)} 天` }
  if(daysLeft<=90) return { label:'即将到期', type:'warning', color:'#D97706', detail:`剩余 ${daysLeft} 天` }
  return { label:'质保期内', type:'success', color:'#059669', detail:`剩余 ${daysLeft} 天` }
})
const warrantyPercent = computed(()=>{
  const w = house.value?.warranty
  if(!w?.startDate || !w?.endDate) return null
  const start = new Date(w.startDate).getTime()
  const end = new Date(w.endDate).getTime()
  const now = Date.now()
  if(now>=end) return 100
  if(now<=start) return 0
  return Math.round(((now-start)/(end-start))*100)
})

onMounted(async () => {
  // 1. 房屋基础档案
  const res = await api.getHouse(houseId)
  house.value = res.data

  // 2. 设备清单：独立接口（文档第9节 Bug#2 —— 详情接口不含 components 字段）
  const cRes = await api.getHouseComponents(houseId)
  houseComponents.value = cRes.data.components || {}

  // 3. 维修历史 + 重复预警：来自 GET /api/maintenance/history/{id}
  //    （文档第9节 Bug#1 —— 详情接口不含 maintenanceRecords，
  //      records 与 repeat_warnings 都在该接口里，一次取回）
  const mRes = await api.getMaintenanceHistory(houseId)
  maintenanceHistory.value = mRes.data.records || []
  repeatWarnings.value = mRes.data.repeat_warnings || []
})
</script>

<style scoped>
.house-header-card { padding: 24px; }
.house-header-top {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}
.house-header-top h2 { font-size: 24px; margin-bottom: 4px; }
.house-meta { color: var(--text-secondary); font-size: 14px; }
.house-id-area {
  text-align: right;
}
.id-row { font-size: 13px; padding: 2px 0; }
.id-row code { font-family: monospace; color: var(--primary-color); }
.id-row span { color: var(--text-secondary); }
.count-badge {
  background: var(--primary-light);
  color: var(--primary-color);
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 12px;
  margin-left: 8px;
}
.pipeline-area {
  padding: 12px;
  background: #f8fafc;
  border-radius: 8px;
  margin-bottom: 12px;
}
.pipeline-area h4 { font-size: 14px; margin-bottom: 8px; }
.pipe-row { font-size: 13px; padding: 3px 0; }
.pipe-label { color: var(--text-secondary); font-weight: 500; min-width: 80px; display: inline-block; }
.history-item {
  padding: 8px;
  background: #f8fafc;
  border-radius: 6px;
}
.history-detail { font-size: 12px; color: var(--text-secondary); margin-top: 4px; }
</style>
