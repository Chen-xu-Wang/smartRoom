<template>
  <div class="work-order-card">
    <div class="order-header">
      <span class="order-id">{{ order.id }}</span>
      <el-tag :type="statusType" size="small">{{ statusLabel }}</el-tag>
    </div>

    <el-descriptions :column="2" border size="small" style="margin-top: 12px">
      <el-descriptions-item label="房屋">{{ order.house_name }}</el-descriptions-item>
      <el-descriptions-item label="位置">{{ order.location }}</el-descriptions-item>
      <el-descriptions-item label="故障类型">{{ order.fault_type }}</el-descriptions-item>
      <el-descriptions-item label="建议工种">{{ order.suggested_trade }}</el-descriptions-item>
      <el-descriptions-item label="紧急等级">
        <span :class="`tag-${order.urgency?.toLowerCase()}`">{{ order.urgency }}</span>
      </el-descriptions-item>
      <el-descriptions-item label="AI置信度">
        <el-progress :percentage="order.confidence || 0" :color="confColor" :stroke-width="14" style="width: 120px"/>
      </el-descriptions-item>
      <el-descriptions-item label="用户描述" :span="2">{{ order.user_description }}</el-descriptions-item>
      <el-descriptions-item label="AI分析" :span="2">{{ order.ai_analysis }}</el-descriptions-item>
    </el-descriptions>

    <!-- Equipment -->
    <div v-if="order.equipment_details && order.equipment_details.length" class="order-section">
      <div class="order-section-title">关联设备</div>
      <div class="equipment-row">
        <el-tag v-for="eq in order.equipment_details" :key="eq.id" type="success" size="small" style="margin-right: 6px">
          {{ eq.name }} ({{ eq.spec }})
        </el-tag>
      </div>
    </div>

    <!-- Pipeline Info -->
    <div v-if="order.pipeline_info && Object.keys(order.pipeline_info).length" class="order-section">
      <div class="order-section-title">管线位置信息</div>
      <div v-for="(v, k) in order.pipeline_info" :key="k" class="pipeline-item">
        <span class="pipe-key">{{ k }}：</span><span>{{ v }}</span>
      </div>
    </div>

    <!-- Maintenance History -->
    <div v-if="order.maintenance_history && order.maintenance_history.length" class="order-section">
      <div class="order-section-title">历史维修记录</div>
      <el-timeline>
        <el-timeline-item
          v-for="h in order.maintenance_history"
          :key="h.id"
          :timestamp="h.date"
          placement="top"
        >
          <div>{{ h.fault }} - {{ h.cause }}</div>
          <div style="font-size: 12px; color: #999">{{ h.action }} | {{ h.repairPerson }}</div>
        </el-timeline-item>
      </el-timeline>
    </div>

    <!-- Actions -->
    <div v-if="showActions" class="order-actions">
      <el-button type="primary" @click="$emit('confirm')">确认提交</el-button>
      <el-button @click="$emit('modify')">需要修改</el-button>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  order: { type: Object, required: true },
  showActions: { type: Boolean, default: false }
})

defineEmits(['confirm', 'modify'])

const statusMap = {
  pending_review: { type: 'warning', label: '待审核' },
  approved: { type: 'primary', label: '已批准' },
  rejected: { type: 'danger', label: '已驳回' },
  in_progress: { type: 'info', label: '维修中' },
  completed: { type: 'success', label: '已完成' },
}

const statusType = computed(() => statusMap[props.order.status]?.type || 'info')
const statusLabel = computed(() => statusMap[props.order.status]?.label || props.order.status)

const confColor = computed(() => {
  const c = props.order.confidence || 0
  if (c >= 80) return '#16a34a'
  if (c >= 60) return '#ca8a04'
  return '#dc2626'
})
</script>

<style scoped>
.work-order-card {
  background: #f8fafc;
  border-radius: 8px;
  padding: 16px;
}
.order-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.order-id {
  font-family: monospace;
  font-size: 13px;
  color: var(--text-secondary);
}
.order-section {
  margin-top: 12px;
}
.order-section-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 6px;
}
.equipment-row {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.pipeline-item {
  font-size: 12px;
  padding: 2px 0;
}
.pipe-key { color: var(--text-secondary); font-weight: 500; }
.order-actions {
  display: flex;
  gap: 12px;
  margin-top: 16px;
  justify-content: center;
}
</style>
