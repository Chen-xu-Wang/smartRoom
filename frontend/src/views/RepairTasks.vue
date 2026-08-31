<template>
  <div class="page-container">
    <div class="page-heading">
      <div>
        <h2 class="section-title"><el-icon><Tools /></el-icon> {{ auth.isRepairer ? '我的维修工单' : '维修任务调度' }}</h2>
        <p v-if="auth.isRepairer">仅展示指派给您（{{ auth.user.name }}）的工单，请及时开工与闭环。</p>
        <p v-else>物业/管理员视角：查看全量维修任务，可按状态与人员筛选。</p>
      </div>
      <el-tag v-if="auth.isRepairer" type="info">{{ auth.user.name }} · 维修工</el-tag>
    </div>

    <!-- 维修工个人统计 -->
    <div v-if="auth.isRepairer" class="stats-row">
      <div class="stat-card card"><div class="stat-value">{{ counts.pending }}</div><div class="stat-label">待维修</div></div>
      <div class="stat-card card"><div class="stat-value stat-primary">{{ counts.processing }}</div><div class="stat-label">进行中</div></div>
      <div class="stat-card card"><div class="stat-value stat-success">{{ counts.completed }}</div><div class="stat-label">已完成</div></div>
    </div>

    <!-- Filter -->
    <div class="card">
      <div style="display:flex; gap:12px; align-items:center; flex-wrap:wrap; justify-content:space-between">
        <el-radio-group v-model="filterStatus" @change="loadOrders">
          <el-radio-button label="pending_assign">待维修</el-radio-button>
          <el-radio-button label="processing">维修中</el-radio-button>
          <el-radio-button label="completed">已完成</el-radio-button>
        </el-radio-group>
        <el-input v-if="!auth.isRepairer" v-model="filterAssignee" placeholder="按维修工姓名筛选" clearable @clear="loadOrders" @keyup.enter="loadOrders" style="max-width:200px" />
      </div>
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
          <!-- 待维修：已指派可直接开工 -->
          <el-button
            v-if="order.status === 'pending_assign' && order.assigned_to"
            size="small"
            type="success"
            :loading="startingId === order.id"
            @click="startRepair(order)"
          >
            开始维修
          </el-button>
          <!-- 维修中：维修工可直接完成 -->
          <el-button
            v-if="order.status === 'processing'"
            size="small"
            type="primary"
            @click="openComplete(order)"
          >
            填写完成
          </el-button>
          <el-button
            v-if="order.status === 'processing'"
            size="small"
            @click="$router.push(`/workorder/${order.id}`)"
          >
            详情/回写
          </el-button>
        </div>
      </div>
    </div>

    <!-- 完成表单弹窗（置于列表外，避免重复渲染） -->
    <el-dialog v-model="completeVisible" title="完成维修并回写档案" width="520px">
      <el-form :model="completeForm" label-width="90px">
        <el-form-item label="实际故障" required><el-input v-model="completeForm.actual_fault" type="textarea" :rows="2" placeholder="如 角阀密封圈老化" /></el-form-item>
        <el-form-item label="处理措施" required><el-input v-model="completeForm.actual_action" type="textarea" :rows="2" placeholder="如 更换密封圈并复紧" /></el-form-item>
        <el-form-item label="使用配件"><el-input v-model="completeForm.used_parts" placeholder="如 密封圈 x1" /></el-form-item>
        <el-form-item label="结果"><el-select v-model="completeForm.result" style="width:100%"><el-option label="完成" value="完成" /><el-option label="需返修" value="需返修" /></el-select></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="completeVisible=false">取消</el-button>
        <el-button type="primary" :loading="!!completingId" @click="submitComplete">提交回写</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue'
import { Tools } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '../stores/auth'
import api from '../api'

const auth = useAuthStore()
const orders = ref([])
const loading = ref(false)
const filterStatus = ref('pending_assign')
const filterAssignee = ref('')
const counts = ref({ pending:0, processing:0, completed:0 })
// 阶段5.8：正在执行「开始维修」的工单号（loading 用，防重复点击）
const startingId = ref('')
const completeVisible = ref(false)
const completingId = ref('')
const completeForm = ref({ actual_fault:'', actual_action:'', used_parts:'', result:'完成' })

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
    const params = { status: filterStatus.value, page_size: 50 }
    if (auth.isRepairer) params.assigned_to = String(auth.user.id)
    else if (filterAssignee.value) params.assigned_to = filterAssignee.value.trim()
    const res = await api.getWorkOrders(params)
    orders.value = res.data.orders
    if (auth.isRepairer) loadCounts()
  } finally {
    loading.value = false
  }
}
const loadCounts = async ()=>{
  try{
    const base = auth.isRepairer ? { assigned_to: String(auth.user.id), page_size:1 } : {}
    const [p,a,c] = await Promise.all([
      api.getWorkOrders({ ...base, status:'pending_assign' }),
      api.getWorkOrders({ ...base, status:'processing' }),
      api.getWorkOrders({ ...base, status:'completed' }),
    ])
    // 后端未返回总数，前端用 page_size 1 时可通过额外查询总数？暂用 orders 长度兜底，实际应由后端返回总数；这里用查询结果长度近似
    // 为准确，改为请求 page_size 100 并计长度（维修工数据量小）
    const rp = await api.getWorkOrders({ ...base, status:'pending_assign', page_size:100 })
    const ra = await api.getWorkOrders({ ...base, status:'processing', page_size:100 })
    const rc = await api.getWorkOrders({ ...base, status:'completed', page_size:100 })
    counts.value = { pending: rp.data.orders.length, processing: ra.data.orders.length, completed: rc.data.orders.length }
  }catch{}
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
const openComplete = (order)=>{
  completingId.value = order.id
  completeForm.value = { actual_fault:'', actual_action:'', used_parts:'', result:'完成' }
  completeVisible.value = true
}
const submitComplete = async ()=>{
  if(!completeForm.value.actual_fault || !completeForm.value.actual_action){ ElMessage.warning('请填写实际故障与处理措施'); return }
  const order = orders.value.find(o=>o.id===completingId.value)
  const person = order?.assigned_to || auth.user.name
  try{
    await api.completeWorkOrder(completingId.value, { repair_person: person, actual_fault: completeForm.value.actual_fault, actual_action: completeForm.value.actual_action, used_parts: completeForm.value.used_parts, result: completeForm.value.result })
    ElMessage.success('已完成并回写档案')
    completeVisible.value=false
    await loadOrders()
  }catch(e){ ElMessage.error(e.response?.data?.detail||'完成失败') }
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
  flex-wrap: wrap;
}
.page-heading{ display:flex; justify-content:space-between; align-items:flex-start; gap:12px; margin-bottom:14px; }
.page-heading p{ font-size:12px; color:var(--text-secondary); margin-top:4px; }
.stats-row{ display:grid; grid-template-columns: repeat(3,1fr); gap:12px; margin-bottom:14px; }
.stat-card{ text-align:center; padding:14px; }
.stat-value{ font-size:22px; font-weight:700; }
.stat-label{ font-size:12px; color:#64748b; margin-top:4px; }
.stat-primary{ color:#2563eb; } .stat-success{ color:#16a34a; }
</style>
