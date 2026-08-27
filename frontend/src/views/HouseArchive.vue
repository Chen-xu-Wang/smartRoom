<template>
  <div class="page-container" v-if="house">
    <!-- House Header -->
    <div class="card house-header-card">
      <div class="house-header-top">
        <div>
          <h2>{{ house.building }}{{ house.room }}</h2>
          <p class="house-meta">{{ house.layout }} | {{ house.area }}㎡ | {{ house.floor }}</p>
        </div>
        <div class="house-id-area">
          <div class="id-row"><span>MiC模块号：</span><code>{{ house.micModuleId }}</code></div>
          <div class="id-row"><span>数字身份码：</span><code>{{ house.digitalId }}</code></div>
          <div class="id-row"><span>一房一码：</span><code>{{ house.qrCode }}</code></div>
          <div class="id-row"><span>生产日期：</span>{{ house.productionDate }}</div>
          <div class="id-row"><span>交付日期：</span>{{ house.deliveryDate }}</div>
        </div>
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
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { House, Lightning, SetUp, WindPower, Tools, Guide, Clock, ChatLineRound } from '@element-plus/icons-vue'
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
