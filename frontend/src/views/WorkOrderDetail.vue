<template>
  <div class="page-container">
    <div v-if="order" class="order-detail">
      <div class="order-header card">
        <div class="header-left">
          <h2>维修工单 {{ order.id }}</h2>
          <el-tag :type="statusTag.type">{{ statusTag.label }}</el-tag>
        </div>
        <div class="header-right">
          <el-button v-if="order.status === 'pending_review'" type="primary" @click="showReviewDialog = true">
            审核
          </el-button>
          <el-button v-if="order.status === 'approved'" type="success" @click="showCompleteDialog = true">
            完成维修
          </el-button>
        </div>
      </div>

      <div class="order-info card">
        <h3 class="section-title">工单信息</h3>
        <el-descriptions :column="2" border>
          <el-descriptions-item label="房屋">{{ order.house_name || order.house_id }}</el-descriptions-item>
          <el-descriptions-item label="位置">{{ order.location }}</el-descriptions-item>
          <el-descriptions-item label="故障类型">{{ order.fault_type }}</el-descriptions-item>
          <el-descriptions-item label="建议工种">{{ order.suggested_trade }}</el-descriptions-item>
          <el-descriptions-item label="紧急等级">
            <span :class="`tag-${(order.urgency || '').toLowerCase()}`">{{ order.urgency }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="AI置信度">
            <el-progress :percentage="order.confidence || 0" :stroke-width="14" style="width: 140px"/>
          </el-descriptions-item>
          <el-descriptions-item label="创建时间" :span="2">{{ formatTime(order.created_at) }}</el-descriptions-item>
          <el-descriptions-item label="用户描述" :span="2">{{ order.user_description }}</el-descriptions-item>
          <el-descriptions-item label="AI分析" :span="2">{{ order.ai_analysis }}</el-descriptions-item>
          <el-descriptions-item label="审核人" v-if="order.reviewed_by">{{ order.reviewed_by }}</el-descriptions-item>
          <el-descriptions-item label="审核时间" v-if="order.reviewed_at">{{ formatTime(order.reviewed_at) }}</el-descriptions-item>
          <el-descriptions-item label="审核备注" :span="2" v-if="order.review_notes">{{ order.review_notes }}</el-descriptions-item>
          <el-descriptions-item label="维修人员" v-if="order.repair_person">{{ order.repair_person }}</el-descriptions-item>
          <el-descriptions-item label="完成时间" v-if="order.completed_at">{{ formatTime(order.completed_at) }}</el-descriptions-item>
          <el-descriptions-item label="实际故障" :span="2" v-if="order.actual_fault">{{ order.actual_fault }}</el-descriptions-item>
          <el-descriptions-item label="处理方式" :span="2" v-if="order.actual_action">{{ order.actual_action }}</el-descriptions-item>
          <el-descriptions-item label="使用部件" v-if="order.used_parts">{{ order.used_parts }}</el-descriptions-item>
          <el-descriptions-item label="结果" v-if="order.result">{{ order.result }}</el-descriptions-item>
        </el-descriptions>
      </div>

      <!-- Related Equipment -->
      <div v-if="relatedEquipment.length" class="card">
        <h3 class="section-title">关联设备（来自一房一码档案）</h3>
        <el-table :data="relatedEquipment" border size="small">
          <el-table-column prop="name" label="设备名称" width="120" />
          <el-table-column prop="spec" label="规格型号" width="120" />
          <el-table-column prop="id" label="设备编号" width="160" />
          <el-table-column prop="manufacturer" label="厂家" width="100" />
          <el-table-column prop="installDate" label="安装日期" />
          <el-table-column prop="warrantyPeriod" label="保修期" />
        </el-table>
      </div>

      <!-- Back to house archive -->
      <div class="card" style="text-align: center">
        <el-button @click="$router.push(`/archive/${order.house_id}`)">
          <el-icon><Document /></el-icon> 查看房屋完整档案
        </el-button>
      </div>
    </div>

    <!-- Review Dialog -->
    <el-dialog v-model="showReviewDialog" title="审核工单" width="500px">
      <el-form label-width="100px">
        <el-form-item label="紧急等级">
          <el-select v-model="reviewForm.urgency" style="width: 100%">
            <el-option label="低" value="低" />
            <el-option label="中" value="中" />
            <el-option label="高" value="高" />
            <el-option label="紧急" value="紧急" />
          </el-select>
        </el-form-item>
        <el-form-item label="维修工种">
          <el-input v-model="reviewForm.suggested_trade" />
        </el-form-item>
        <el-form-item label="指派人员">
          <el-input v-model="reviewForm.assigned_to" placeholder="如：水电维修组A" />
        </el-form-item>
        <el-form-item label="审核备注">
          <el-input v-model="reviewForm.review_notes" type="textarea" :rows="2" placeholder="如：持续漏水可能影响楼下，升级为高优先级" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showReviewDialog = false">取消</el-button>
        <el-button type="primary" @click="submitReview('approved')">确认批准</el-button>
        <el-button type="danger" @click="submitReview('rejected')">驳回</el-button>
      </template>
    </el-dialog>

    <!-- Complete Dialog -->
    <el-dialog v-model="showCompleteDialog" title="完成维修" width="500px">
      <el-form label-width="100px">
        <el-form-item label="维修人员">
          <el-input v-model="completeForm.repair_person" placeholder="如：张工" />
        </el-form-item>
        <el-form-item label="实际故障">
          <el-input v-model="completeForm.actual_fault" type="textarea" :rows="2" placeholder="如：角阀密封圈失效" />
        </el-form-item>
        <el-form-item label="处理方式">
          <el-input v-model="completeForm.actual_action" type="textarea" :rows="2" placeholder="如：更换角阀AF-105" />
        </el-form-item>
        <el-form-item label="使用部件">
          <el-input v-model="completeForm.used_parts" placeholder="如：AF-105角阀 x1" />
        </el-form-item>
      </el-form>
      <el-alert type="success" :closable="false" style="margin: 12px 0">
        维修完成后，数据将自动回写至「一房一码」数字档案
      </el-alert>
      <template #footer>
        <el-button @click="showCompleteDialog = false">取消</el-button>
        <el-button type="success" @click="submitComplete">确认完成</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Document } from '@element-plus/icons-vue'
import api from '../api'
import WorkOrderCard from '../components/WorkOrderCard.vue'

const route = useRoute()
const router = useRouter()
const order = ref(null)
const houseData = ref(null)
const showReviewDialog = ref(false)
const showCompleteDialog = ref(false)

const reviewForm = ref({
  urgency: '',
  suggested_trade: '',
  assigned_to: '',
  review_notes: '',
})
const completeForm = ref({
  repair_person: '',
  actual_fault: '',
  actual_action: '',
  used_parts: '',
})

const statusMap = {
  pending_review: { type: 'warning', label: '待审核' },
  approved: { type: 'primary', label: '已批准' },
  rejected: { type: 'danger', label: '已驳回' },
  in_progress: { type: 'info', label: '维修中' },
  completed: { type: 'success', label: '已完成' },
}

const statusTag = computed(() => statusMap[order.value?.status] || { type: 'info', label: order.value?.status })

const relatedEquipment = computed(() => {
  if (!order.value || !houseData.value) return []
  const eqIds = order.value.related_equipment || []
  const allComponents = houseData.value.components || {}
  const allEquip = Object.values(allComponents).flat()
  return allEquip.filter(e => eqIds.includes(e.id))
})

const formatTime = (t) => {
  if (!t) return ''
  return new Date(t).toLocaleString('zh-CN')
}

const submitReview = async (status) => {
  try {
    await api.reviewWorkOrder(route.params.id, {
      ...reviewForm.value,
      reviewed_by: '物业管理员',
      status,
    })
    ElMessage.success(status === 'approved' ? '工单已批准' : '工单已驳回')
    showReviewDialog.value = false
    await loadOrder()
  } catch (e) {
    ElMessage.error('操作失败')
  }
}

const submitComplete = async () => {
  try {
    await api.completeWorkOrder(route.params.id, completeForm.value)
    ElMessage.success('维修完成！数据已回写至一房一码数字档案')
    showCompleteDialog.value = false
    await loadOrder()
  } catch (e) {
    ElMessage.error('操作失败')
  }
}

const loadOrder = async () => {
  const res = await api.getWorkOrder(route.params.id)
  order.value = res.data
  const hRes = await api.getHouse(res.data.house_id)
  houseData.value = hRes.data

  // Pre-fill review form
  reviewForm.value.urgency = res.data.urgency || ''
  reviewForm.value.suggested_trade = res.data.suggested_trade || ''
}

onMounted(async () => {
  await loadOrder()
})
</script>

<style scoped>
.order-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}
.header-left h2 { font-size: 18px; }
</style>
