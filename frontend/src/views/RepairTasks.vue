<template>
  <div class="page-container">
    <h2 class="section-title"><el-icon><Tools /></el-icon> 维修人员任务</h2>

    <!-- Filter -->
    <div class="card">
      <el-radio-group v-model="filterStatus" @change="loadOrders">
        <el-radio-button label="pending_assign">待维修</el-radio-button>
        <el-radio-button label="processing">维修中</el-radio-button>
        <el-radio-button label="completed">已完成</el-radio-button>
      </el-radio-group>
    </div>

    <!-- Task Cards -->
    <div v-loading="loading">
      <div v-if="orders.length === 0" class="card" style="text-align: center; padding: 40px">
        <el-empty description="暂无任务" />
      </div>

      <div v-for="order in orders" :key="order.id" class="task-card card">
        <div class="task-header">
          <div class="task-title">
            <h3>{{ order.location }} - {{ order.fault_type }}</h3>
            <span class="task-house">{{ order.house_id }} | {{ order.suggested_trade }}</span>
          </div>
          <el-tag :type="urgencyTag(order.urgency)" size="small">{{ order.urgency }}</el-tag>
        </div>

        <div class="task-body">
          <div class="task-section">
            <span class="task-label">用户描述：</span>{{ order.user_description }}
          </div>
          <div class="task-section">
            <span class="task-label">AI分析：</span>{{ order.ai_analysis }}
          </div>
          <div class="task-section">
            <span class="task-label">建议检查：</span>
            <span v-if="order.ai_analysis">{{ parseCauses(order.ai_analysis) }}</span>
          </div>
          <div v-if="order.assigned_to" class="task-section">
            <span class="task-label">指派：</span>{{ order.assigned_to }}
          </div>
          <div v-if="order.completed_at" class="task-section completed-section">
            <span class="task-label">实际故障：</span>{{ order.actual_fault }}
            <br><span class="task-label">处理方式：</span>{{ order.actual_action }}
            <br><span class="task-label">维修人员：</span>{{ order.repair_person }}
            <br><span class="task-label">完成时间：</span>{{ formatTime(order.completed_at) }}
          </div>
        </div>

        <div class="task-actions">
          <el-button size="small" @click="$router.push(`/workorder/${order.id}`)">
            查看详情
          </el-button>
          <el-button size="small" @click="$router.push(`/archive/${order.house_id}`)">
            查看房屋档案
          </el-button>
          <!-- 阶段5.8：已派单待开始维修 → 直接调 /start 开工 -->
          <!-- 仅当 pending_assign 且 assigned_to 已存在时显示；未派单不显示 -->
          <el-button
            v-if="order.status === 'pending_assign' && order.assigned_to"
            size="small"
            type="success"
            :loading="startingId === order.id"
            @click="startRepair(order)"
          >
            开始维修
          </el-button>
          <!-- 阶段5.8：维修中 → 只进详情继续处理，不重复调用 /start -->
          <el-button
            v-if="order.status === 'processing'"
            size="small"
            type="success"
            @click="$router.push(`/workorder/${order.id}`)"
          >
            继续处理
          </el-button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { Tools } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import api from '../api'

const orders = ref([])
const loading = ref(false)
const filterStatus = ref('pending_assign')
// 阶段5.8：正在执行「开始维修」的工单号（loading 用，防重复点击）
const startingId = ref('')

const urgencyTag = (u) => {
  const map = { '紧急': 'danger', '高': 'warning', '中': 'info', '低': 'success' }
  return map[u] || 'info'
}

const parseCauses = (analysis) => {
  // Parse possible causes from AI analysis string
  const causes = analysis?.replace(/疑似/g, '').replace(/\*\*/g, '').split('、').slice(0, 3)
  return causes?.join(' → 检查 ') || '需现场检查'
}

const formatTime = (t) => {
  if (!t) return ''
  return new Date(t).toLocaleString('zh-CN')
}

const loadOrders = async () => {
  loading.value = true
  try {
    const res = await api.getWorkOrders({ status: filterStatus.value, page_size: 50 })
    orders.value = res.data.orders
  } finally {
    loading.value = false
  }
}

// 阶段5.8：开始维修 —— 显式传当前工单已指派的维修人姓名
// （后端会只读校验「发起人 = 派单人」，防止非指派维修人开工）
const startRepair = async (order) => {
  if (startingId.value) return
  startingId.value = order.id
  try {
    await api.startWorkOrder(order.id, { repair_person: order.assigned_to })
    ElMessage.success('已开始维修，工单状态更新为维修中')
    await loadOrders()  // 刷新列表：该工单从「待维修」移到「维修中」筛选下
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '开始维修失败')
  } finally {
    startingId.value = ''
  }
}

onMounted(() => {
  loadOrders()
})
</script>

<style scoped>
.task-card {
  padding: 16px;
  margin-bottom: 12px;
}
.task-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--border-color);
}
.task-title h3 { font-size: 16px; }
.task-house { font-size: 12px; color: var(--text-secondary); }
.task-body {
  font-size: 13px;
}
.task-section {
  padding: 4px 0;
}
.task-label {
  color: var(--text-secondary);
  font-weight: 500;
}
.completed-section {
  background: #f0fdf4;
  padding: 8px;
  border-radius: 6px;
  margin-top: 4px;
}
.task-actions {
  display: flex;
  gap: 8px;
  margin-top: 12px;
  padding-top: 8px;
  border-top: 1px solid var(--border-color);
}
</style>
