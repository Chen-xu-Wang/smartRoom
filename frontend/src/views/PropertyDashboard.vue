<template>
  <div class="page-container">
    <h2 class="section-title"><el-icon><OfficeBuilding /></el-icon> 物业管理后台</h2>

    <!-- Stats（5 卡：总数/待审核/待派单·待维修/维修中/已完成，与后端 by_status 新键对齐） -->
    <div class="stats-row">
      <div class="stat-card card">
        <div class="stat-value">{{ stats.total || 0 }}</div>
        <div class="stat-label">工单总数</div>
      </div>
      <div class="stat-card card">
        <div class="stat-value stat-warn">{{ stats.by_status?.pending_review || 0 }}</div>
        <div class="stat-label">待审核</div>
      </div>
      <div class="stat-card card">
        <div class="stat-value stat-primary">{{ stats.by_status?.pending_assign || 0 }}</div>
        <div class="stat-label">待派单/待维修</div>
      </div>
      <div class="stat-card card">
        <div class="stat-value stat-info">{{ stats.by_status?.processing || 0 }}</div>
        <div class="stat-label">维修中</div>
      </div>
      <div class="stat-card card">
        <div class="stat-value stat-success">{{ stats.by_status?.completed || 0 }}</div>
        <div class="stat-label">已完成</div>
      </div>
    </div>

    <!-- AI Confidence -->
    <div class="card" v-if="stats.avg_confidence">
      <div class="conf-display">
        <span>AI平均置信度</span>
        <el-progress :percentage="stats.avg_confidence" :stroke-width="20" :text-inside="true" />
      </div>
    </div>

    <!-- Filters -->
    <div class="card">
      <div class="filter-bar">
        <el-radio-group v-model="filterStatus" @change="loadOrders">
          <el-radio-button label="">全部</el-radio-button>
          <el-radio-button label="pending_review">待审核</el-radio-button>
          <el-radio-button label="pending_assign">待派单/待维修</el-radio-button>
          <el-radio-button label="processing">维修中</el-radio-button>
          <el-radio-button label="completed">已完成</el-radio-button>
          <el-radio-button label="rejected">已驳回</el-radio-button>
        </el-radio-group>
        <el-input v-model="filterHouse" placeholder="按房屋号筛选" style="width: 200px" clearable @clear="loadOrders" @keyup.enter="loadOrders" />
      </div>
    </div>

    <!-- Work Order List -->
    <div class="card">
      <el-table :data="orders" border style="width: 100%" v-loading="loading">
        <el-table-column prop="id" label="工单号" width="200" />
        <el-table-column prop="house_id" label="房屋" width="80" />
        <el-table-column prop="location" label="位置" width="80" />
        <el-table-column prop="fault_type" label="故障类型" width="100" />
        <el-table-column prop="ai_analysis" label="AI分析" show-overflow-tooltip />
        <el-table-column prop="suggested_trade" label="工种" width="100" />
        <el-table-column prop="urgency" label="紧急度" width="80">
          <template #default="{ row }">
            <el-tag :type="urgencyTag(row.urgency)" size="small">{{ row.urgency }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="confidence" label="置信度" width="100">
          <template #default="{ row }">
            <el-progress :percentage="row.confidence || 0" :stroke-width="10" :show-text="false" />
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="120">
          <template #default="{ row }">
            <el-tag :type="statusTag(row.status)" size="small">{{ statusLabel(row) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="100" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="primary" @click="$router.push(`/workorder/${row.id}`)">详情</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- Repeat Maintenance Warning -->
    <div class="card" v-if="repeatWarnings.length">
      <h3 class="section-title"><el-icon><Warning /></el-icon> 重复维修预警</h3>
      <el-alert
        v-for="(w, i) in repeatWarnings"
        :key="i"
        type="warning"
        :closable="false"
        style="margin-bottom: 8px"
      >{{ w }}</el-alert>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { OfficeBuilding, Warning } from '@element-plus/icons-vue'
import api from '../api'

const stats = ref({})
const orders = ref([])
const loading = ref(false)
const filterStatus = ref('')
const filterHouse = ref('')
const repeatWarnings = ref([])

const urgencyTag = (u) => {
  const map = { '紧急': 'danger', '高': 'warning', '中': 'info', '低': 'success' }
  return map[u] || 'info'
}

// 状态标签颜色（与后端 STATUS_EN2CN 输出对齐）
const statusTag = (s) => {
  const map = {
    pending_review: 'warning',
    pending_assign: 'primary',
    processing: 'info',
    completed: 'success',
    cancelled: 'info',
    rejected: 'danger',
  }
  return map[s] || 'info'
}

// 状态显示文字：pending_assign 需按是否已派单区分（传整行而非只传状态）
const statusLabel = (row) => {
  const map = {
    pending_review: '待审核',
    pending_assign: row.assigned_to ? '已派单/待维修' : '待派单',
    processing: '维修中',
    completed: '已完成',
    cancelled: '已取消',
    rejected: '已驳回',
  }
  return map[row.status] || row.status
}

const loadOrders = async () => {
  loading.value = true
  try {
    const params = {}
    if (filterStatus.value) params.status = filterStatus.value
    if (filterHouse.value) params.house_id = filterHouse.value
    const res = await api.getWorkOrders(params)
    orders.value = res.data.orders
  } finally {
    loading.value = false
  }
}

const loadStats = async () => {
  const res = await api.getWorkOrderStats()
  stats.value = res.data
}

const loadRepeatWarnings = async () => {
  const houses = ['1302', '805', '503']
  for (const hid of houses) {
    const res = await api.getMaintenanceHistory(hid)
    repeatWarnings.value.push(...(res.data.repeat_warnings || []))
  }
}

onMounted(async () => {
  await Promise.all([loadOrders(), loadStats(), loadRepeatWarnings()])
})
</script>

<style scoped>
.stats-row {
  display: flex;
  gap: 16px;
  margin-bottom: 16px;
}
.stat-card {
  flex: 1;
  text-align: center;
  padding: 20px;
}
.stat-value {
  font-size: 32px;
  font-weight: 700;
  color: var(--text-primary);
}
.stat-warn { color: #ea580c; }
.stat-primary { color: #2563eb; }
.stat-info { color: #0891b2; }
.stat-success { color: #16a34a; }
.stat-label {
  font-size: 13px;
  color: var(--text-secondary);
  margin-top: 4px;
}
.conf-display {
  display: flex;
  align-items: center;
  gap: 16px;
}
.conf-display span {
  font-weight: 600;
  white-space: nowrap;
}
.filter-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
</style>
