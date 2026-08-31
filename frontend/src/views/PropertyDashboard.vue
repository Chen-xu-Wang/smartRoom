<template>
  <div class="page-container">
    <div class="page-heading">
      <div>
        <h2 class="section-title"><el-icon><OfficeBuilding /></el-icon> 物业管理后台</h2>
        <p>统一查看工单进度，并通过负载均衡与疲劳保护安排维修任务。</p>
      </div>
    </div>

    <!-- 工单统计 -->
    <div class="stats-row" style="grid-template-columns: repeat(6, minmax(0, 1fr))">
      <div class="stat-card card">
        <div class="stat-value">{{ stats.total || 0 }}</div>
        <div class="stat-label">工单总数</div>
      </div>
      <div class="stat-card card">
        <div class="stat-value">{{ stats.by_status?.draft || 0 }}</div>
        <div class="stat-label">草稿</div>
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

    <!-- AI 智能调度中心 -->
    <section class="card dispatch-center" v-loading="dispatchLoading">
      <div class="dispatch-header">
        <div class="dispatch-heading">
          <div class="ai-mark"><el-icon><MagicStick /></el-icon></div>
          <div>
            <h3>AI智能调度中心 <el-tag size="small" effect="dark">疲劳保护已开启</el-tag></h3>
            <p>先守住在岗、技能与负荷上限，再综合经验和公平性推荐维修人员。</p>
          </div>
        </div>
        <div class="dispatch-actions">
          <span v-if="dispatchData.generated_at" class="updated-at">更新于 {{ formatTime(dispatchData.generated_at) }}</span>
          <el-button :icon="Refresh" :loading="dispatchLoading" @click="loadDispatchOverview">刷新</el-button>
          <el-button
            type="primary"
            :loading="batchAssigning"
            :disabled="!(dispatchSummary.total_dispatchable || dispatchSummary.unassigned_orders)"
            @click="confirmBatchAssign"
          >
            一键安全派单（{{ dispatchSummary.total_dispatchable || dispatchSummary.unassigned_orders || 0 }}）
          </el-button>
        </div>
      </div>

      <el-alert
        v-if="dispatchError"
        type="error"
        show-icon
        :closable="false"
        :title="dispatchError"
        class="dispatch-error"
      >
        <template #default>
          <el-button size="small" @click="loadDispatchOverview">重新加载</el-button>
        </template>
      </el-alert>

      <template v-else>
        <div class="dispatch-summary">
          <div class="summary-item">
            <span>待审核</span>
            <strong>{{ dispatchSummary.pending_review_orders || 0 }}</strong>
            <small>高置信度可自动过审</small>
          </div>
          <div class="summary-item summary-primary">
            <span>等待派单</span>
            <strong>{{ dispatchSummary.unassigned_orders || 0 }}</strong>
            <small>按优先级排队</small>
          </div>
          <div class="summary-item summary-success">
            <span>可接单人员</span>
            <strong>{{ dispatchSummary.available_repairers || 0 }}</strong>
            <small>在岗且未触发保护</small>
          </div>
          <div class="summary-item summary-danger">
            <span>负荷预警人员</span>
            <strong>{{ dispatchSummary.overload_repairers || 0 }}</strong>
            <small>不会继续自动加单</small>
          </div>
          <div class="summary-item summary-warning">
            <span>SLA风险工单</span>
            <strong>{{ dispatchSummary.sla_risk_orders || 0 }}</strong>
            <small>需要优先响应</small>
          </div>
          <div class="summary-item">
            <span>今日已完成</span>
            <strong>{{ dispatchSummary.today_completed || 0 }}</strong>
            <small>团队完工量</small>
          </div>
          <div class="summary-item balance-item">
            <span>负载均衡分</span>
            <strong>{{ dispatchSummary.balance_score ?? '--' }}</strong>
            <el-progress
              :percentage="safePercentage(dispatchSummary.balance_score)"
              :show-text="false"
              :stroke-width="7"
              :color="balanceColor(dispatchSummary.balance_score)"
            />
          </div>
        </div>

        <div class="dispatch-columns">
          <div class="dispatch-panel">
            <div class="panel-heading">
              <div>
                <h4>团队负载与疲劳</h4>
                <p>疲劳指数综合在途任务、今日完工量与休息间隔，仅用于调度保护。</p>
              </div>
            </div>
            <el-empty v-if="!dispatchRepairers.length" description="暂无维修人员画像" :image-size="54" />
            <div v-else class="repairer-grid">
              <article v-for="repairer in dispatchRepairers" :key="repairer.id || repairer.name" class="repairer-card">
                <div class="repairer-top">
                  <div>
                    <strong>{{ repairerName(repairer) }}</strong>
                    <el-tag size="small" :type="repairer.on_duty === false ? 'info' : 'success'">
                      {{ repairer.on_duty === false ? '休息中' : '在岗' }}
                    </el-tag>
                  </div>
                  <el-tag size="small" :type="fatigueTag(repairer.fatigue_level)">
                    {{ fatigueLabel(repairer.fatigue_level) }}
                  </el-tag>
                </div>
                <div v-if="normaliseSkills(repairer.skills).length" class="skill-list">
                  <el-tag v-for="skill in normaliseSkills(repairer.skills)" :key="skill" size="small" effect="plain">{{ skill }}</el-tag>
                </div>
                <div class="load-metrics">
                  <div>
                    <span>在途工单</span>
                    <b>{{ repairer.active_orders || 0 }} / {{ repairer.max_active_orders || 0 }}</b>
                  </div>
                  <div>
                    <span>今日完工</span>
                    <b>{{ repairer.completed_today || 0 }} / {{ repairer.daily_capacity || 0 }}</b>
                  </div>
                </div>
                <div class="fatigue-row">
                  <span>疲劳指数</span>
                  <el-progress
                    :percentage="safePercentage(repairer.fatigue_index)"
                    :stroke-width="9"
                    :color="fatigueColor(repairer.fatigue_level)"
                  />
                </div>
                <div v-if="repairerBlockers(repairer).length" class="protection-note">
                  <el-icon><Warning /></el-icon>
                  <span>{{ repairerBlockers(repairer).join('；') }}</span>
                </div>
              </article>
            </div>
          </div>

          <div class="dispatch-panel sla-panel">
            <div class="panel-heading">
              <div>
                <h4>SLA响应风险</h4>
                <p>按超时程度排序，点击工单可直接处理。</p>
              </div>
            </div>
            <el-empty v-if="!slaRisks.length" description="当前没有 SLA 风险工单" :image-size="54" />
            <div v-else class="sla-list">
              <button
                v-for="risk in slaRisks.slice(0, 6)"
                :key="risk.order_no"
                type="button"
                class="sla-item"
                @click="$router.push(`/workorder/${risk.order_no}`)"
              >
                <div class="sla-item-top">
                  <div>
                    <strong>{{ risk.order_no }}</strong>
                    <span>{{ risk.house_code }} · {{ risk.location || '未标注位置' }}</span>
                  </div>
                  <el-tag size="small" :type="slaRiskTag(risk.risk_level)">{{ slaRiskLabel(risk.risk_level) }}</el-tag>
                </div>
                <el-progress
                  :percentage="safePercentage(risk.progress)"
                  :show-text="false"
                  :stroke-width="6"
                  :color="slaRiskColor(risk.risk_level)"
                />
                <div class="sla-item-bottom">
                  <span>{{ risk.message }}</span>
                  <span>{{ risk.unassigned ? '尚未派单' : statusLabelFromCode(risk.status) }}</span>
                </div>
              </button>
            </div>
          </div>
        </div>

        <div v-if="dispatchQueue.length" class="dispatch-queue">
          <div class="panel-heading queue-heading">
            <div>
              <h4>待调度队列</h4>
              <p>含待审核（高置信度可自动过审）与待派单，高优先级优先。</p>
            </div>
            <el-tag size="small" effect="plain">{{ pendingReviewOrders.length }} 待审核 + {{ unassignedOrders.length }} 待派单</el-tag>
          </div>
          <el-table :data="dispatchQueue" size="small" stripe>
            <el-table-column prop="order_no" label="工单号" min-width="190" />
            <el-table-column label="房屋/位置" min-width="130">
              <template #default="{ row }">{{ row.house_code }} · {{ row.location || '—' }}</template>
            </el-table-column>
            <el-table-column label="状态" width="90">
              <template #default="{ row }"><el-tag size="small" :type="row._queueStatus==='待审核'?'warning':'primary'">{{ row._queueStatus }}</el-tag></template>
            </el-table-column>
            <el-table-column prop="repair_category" label="维修类别" min-width="100" />
            <el-table-column label="优先级" width="90">
              <template #default="{ row }">
                <el-tag size="small" :type="priorityTag(row.priority)">{{ priorityLabel(row.priority) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="等待时长" width="110">
              <template #default="{ row }">{{ waitingTime(row.created_at) }}</template>
            </el-table-column>
            <el-table-column label="操作" width="80" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" @click="$router.push(`/workorder/${row.order_no}`)">查看</el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </template>
    </section>

    <!-- 新想法：预测性维护，让物业在故障发生前主动介入 -->
    <section class="card prediction-card" v-loading="maintenanceRiskLoading">
      <div class="prediction-header">
        <div class="prediction-title">
          <div class="prediction-mark"><el-icon><TrendCharts /></el-icon></div>
          <div>
            <h3>预测性维护</h3>
            <p>结合设备状态、维修频率和未闭环工单，提前发现可能反复报修的目标。</p>
          </div>
        </div>
        <div class="prediction-summary">
          <span><b>{{ highMaintenanceRiskCount }}</b> 高风险</span>
          <span><b>{{ mediumMaintenanceRiskCount }}</b> 中风险</span>
          <span v-if="maintenanceRiskData.summary?.average_health_score != null">
            平均健康分 <b>{{ maintenanceRiskData.summary.average_health_score }}</b>
          </span>
        </div>
      </div>
      <el-alert v-if="maintenanceRiskError" type="warning" :closable="false" show-icon :title="maintenanceRiskError" />
      <el-empty v-else-if="!topMaintenanceRisks.length" description="当前没有需要关注的维护目标" :image-size="54" />
      <div v-else class="prediction-list">
        <article v-for="risk in topMaintenanceRisks" :key="risk.target_id || `${risk.house_code}-${risk.device_name}-${risk.location}`" class="prediction-item">
          <div class="prediction-item-top">
            <div>
              <el-tag size="small" :type="maintenanceRiskTag(risk.risk_level)">{{ maintenanceRiskLabel(risk.risk_level) }}</el-tag>
              <strong>{{ risk.device_name || risk.location || '未命名维护目标' }}</strong>
              <span>{{ risk.house_code }} · {{ risk.location || '未标注位置' }}</span>
            </div>
            <div class="health-score" :class="`health-${String(risk.risk_level || '').toLowerCase()}`">
              <b>{{ risk.health_score ?? '--' }}</b><small>健康分</small>
            </div>
          </div>
          <div class="prediction-action">
            <span>建议</span>
            <p>{{ risk.recommended_action || '建议安排物业人员现场巡检并记录设备状态。' }}</p>
          </div>
          <div class="prediction-meta">
            <span>近期开单/维修 {{ risk.recent_repair_count || 0 }} 次</span>
            <span v-if="normaliseRiskFactors(risk.risk_factors).length">
              {{ normaliseRiskFactors(risk.risk_factors).slice(0, 2).join('；') }}
            </span>
          </div>
        </article>
      </div>
    </section>

    <div class="card" v-if="stats.avg_confidence">
      <div class="conf-display">
        <span>AI平均置信度</span>
        <el-progress :percentage="stats.avg_confidence" :stroke-width="20" :text-inside="true" />
      </div>
    </div>

    <!-- 工单筛选 -->
    <div class="card">
      <div class="filter-bar">
        <el-radio-group v-model="filterStatus" @change="loadOrders">
          <el-radio-button label="">全部</el-radio-button>
          <el-radio-button label="draft">草稿</el-radio-button>
          <el-radio-button label="pending_review">待审核</el-radio-button>
          <el-radio-button label="pending_assign">待派单/待维修</el-radio-button>
          <el-radio-button label="processing">维修中</el-radio-button>
          <el-radio-button label="completed">已完成</el-radio-button>
          <el-radio-button label="rejected">已驳回</el-radio-button>
        </el-radio-group>
        <el-input v-model="filterHouse" placeholder="按房屋号筛选" clearable @clear="loadOrders" @keyup.enter="loadOrders" />
      </div>
      <div v-if="orders.length===0 && !loading" style="text-align:center; padding:12px; color:var(--text-secondary); font-size:13px">
        暂无工单 · 居民扫码报修后，AI会自动提交至“待审核”，请切换“草稿”查看未完成对话的工单
      </div>
    </div>

    <!-- 工单列表 -->
    <div class="card order-table-card">
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

    <div class="card" v-if="repeatWarnings.length">
      <h3 class="section-title"><el-icon><Warning /></el-icon> 重复维修预警</h3>
      <el-alert
        v-for="(warning, index) in repeatWarnings"
        :key="index"
        type="warning"
        :closable="false"
        class="repeat-warning"
      >{{ warning }}</el-alert>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { MagicStick, OfficeBuilding, Refresh, TrendCharts, Warning } from '@element-plus/icons-vue'
import api from '../api'

const stats = ref({})
const orders = ref([])
const loading = ref(false)
const filterStatus = ref('')
const filterHouse = ref('')
const repeatWarnings = ref([])

const dispatchData = ref({ summary: {}, repairers: [], unassigned_orders: [], sla_risks: [] })
const dispatchLoading = ref(false)
const dispatchError = ref('')
const batchAssigning = ref(false)

const maintenanceRiskData = ref({ summary: {}, risks: [] })
const maintenanceRiskLoading = ref(false)
const maintenanceRiskError = ref('')

const dispatchSummary = computed(() => dispatchData.value.summary || {})
const dispatchRepairers = computed(() => dispatchData.value.repairers || [])
const pendingReviewOrders = computed(() => dispatchData.value.pending_review_orders || [])
const unassignedOrders = computed(() => dispatchData.value.unassigned_orders || [])
const dispatchQueue = computed(() => {
  const a = pendingReviewOrders.value.map(r=> ({...r, _queueStatus:'待审核'}))
  const b = unassignedOrders.value.map(r=> ({...r, _queueStatus:'待派单'}))
  return [...a, ...b].slice(0,8)
})
const slaRisks = computed(() => dispatchData.value.sla_risks || [])
const highMaintenanceRiskCount = computed(() => (
  maintenanceRiskData.value.high_risk_summary?.count
  ?? maintenanceRiskData.value.summary?.high_risk_count
  ?? 0
))
const mediumMaintenanceRiskCount = computed(() => (
  maintenanceRiskData.value.medium_risk_summary?.count
  ?? maintenanceRiskData.value.summary?.medium_risk_count
  ?? 0
))
const topMaintenanceRisks = computed(() => {
  const rank = { HIGH: 0, MEDIUM: 1, LOW: 2, high: 0, medium: 1, low: 2 }
  return [...(maintenanceRiskData.value.risks || [])]
    .filter(item => ['HIGH', 'MEDIUM', 'high', 'medium'].includes(item.risk_level))
    .sort((a, b) => (rank[a.risk_level] ?? 3) - (rank[b.risk_level] ?? 3) || (a.health_score ?? 100) - (b.health_score ?? 100))
    .slice(0, 3)
})

const getErrorMessage = (error, fallback) => {
  const detail = error?.response?.data?.detail
  if (typeof detail === 'string' && detail.trim()) return detail
  if (detail && typeof detail === 'object') {
    return detail.message || detail.msg || detail.code || fallback
  }
  return error?.response?.data?.message || fallback
}

const safePercentage = value => Math.max(0, Math.min(100, Number(value) || 0))
const repairerName = repairer => repairer.name || repairer.real_name || repairer.username || '未命名维修人员'
const normaliseSkills = skills => Array.isArray(skills) ? skills : String(skills || '').split(/[,，]/).map(item => item.trim()).filter(Boolean)
const normaliseRiskFactors = factors => {
  if (Array.isArray(factors)) return factors.map(item => typeof item === 'string' ? item : item?.message || item?.label || '').filter(Boolean)
  return factors ? [String(factors)] : []
}
const repairerBlockers = repairer => repairer.blockers || repairer.workload_blockers || []

const urgencyTag = urgency => ({ '紧急': 'danger', '高': 'warning', '中': 'info', '低': 'success' })[urgency] || 'info'
const statusTag = status => ({
  draft: 'info', pending_review: 'warning', pending_assign: 'primary', processing: '', completed: 'success', cancelled: 'info', rejected: 'danger',
})[status] || 'info'
const statusLabel = row => ({
  draft: '草稿/待补充', pending_review: '待审核', pending_assign: row.assigned_to ? '已派单/待维修' : '待派单',
  processing: '维修中', completed: '已完成', cancelled: '已取消', rejected: '已驳回',
})[row.status] || row.status
const statusLabelFromCode = status => ({
  PENDING_REVIEW: '待审核', PENDING_ASSIGN: '待响应', PROCESSING: '维修中',
  pending_review: '待审核', pending_assign: '待响应', processing: '维修中',
})[status] || '处理中'

const fatigueLabel = level => ({ low: '低疲劳', medium: '需关注', high: '高疲劳' })[String(level || '').toLowerCase()] || '待评估'
const fatigueTag = level => ({ low: 'success', medium: 'warning', high: 'danger' })[String(level || '').toLowerCase()] || 'info'
const fatigueColor = level => ({ low: '#16a34a', medium: '#f59e0b', high: '#dc2626' })[String(level || '').toLowerCase()] || '#94a3b8'
const balanceColor = score => Number(score) >= 80 ? '#16a34a' : Number(score) >= 60 ? '#f59e0b' : '#dc2626'

const slaRiskLabel = level => ({ overdue: '已超时', high: '高风险', medium: '中风险', low: '低风险' })[level] || '需关注'
const slaRiskTag = level => ({ overdue: 'danger', high: 'danger', medium: 'warning', low: 'info' })[level] || 'info'
const slaRiskColor = level => ({ overdue: '#dc2626', high: '#ef4444', medium: '#f59e0b', low: '#3b82f6' })[level] || '#94a3b8'

const priorityLabel = priority => ({ URGENT: '紧急', HIGH: '高', NORMAL: '中', LOW: '低' })[String(priority || '').toUpperCase()] || priority || '普通'
const priorityTag = priority => ({ URGENT: 'danger', HIGH: 'warning', NORMAL: 'info', LOW: 'success' })[String(priority || '').toUpperCase()] || 'info'
const maintenanceRiskLabel = level => ({ HIGH: '高风险', MEDIUM: '中风险', LOW: '低风险', high: '高风险', medium: '中风险', low: '低风险' })[level] || '待评估'
const maintenanceRiskTag = level => ({ HIGH: 'danger', MEDIUM: 'warning', LOW: 'success', high: 'danger', medium: 'warning', low: 'success' })[level] || 'info'

const formatTime = time => time ? new Date(time).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : ''
const waitingTime = time => {
  if (!time) return '—'
  const hours = Math.max(0, (Date.now() - new Date(time).getTime()) / 3600000)
  if (hours < 1) return `${Math.max(1, Math.round(hours * 60))} 分钟`
  if (hours < 24) return `${Math.floor(hours)} 小时`
  return `${Math.floor(hours / 24)} 天 ${Math.floor(hours % 24)} 小时`
}

const loadOrders = async () => {
  loading.value = true
  try {
    const params = {}
    if (filterStatus.value) params.status = filterStatus.value
    if (filterHouse.value) params.house_id = filterHouse.value
    const response = await api.getWorkOrders(params)
    orders.value = response.data.orders || []
  } catch (error) {
    ElMessage.error(getErrorMessage(error, '工单列表加载失败'))
  } finally {
    loading.value = false
  }
}

const loadStats = async () => {
  try {
    const response = await api.getWorkOrderStats()
    stats.value = response.data || {}
  } catch (error) {
    ElMessage.error(getErrorMessage(error, '工单统计加载失败'))
  }
}

const loadDispatchOverview = async () => {
  dispatchLoading.value = true
  dispatchError.value = ''
  try {
    const response = await api.getDispatchOverview()
    dispatchData.value = response.data || { summary: {}, repairers: [], unassigned_orders: [], sla_risks: [] }
  } catch (error) {
    dispatchError.value = getErrorMessage(error, '智能调度数据加载失败，请稍后重试')
  } finally {
    dispatchLoading.value = false
  }
}

const loadMaintenanceRisks = async () => {
  maintenanceRiskLoading.value = true
  maintenanceRiskError.value = ''
  try {
    const response = await api.getMaintenanceRisks()
    maintenanceRiskData.value = response.data || { summary: {}, risks: [] }
  } catch (error) {
    maintenanceRiskError.value = getErrorMessage(error, '预测性维护数据暂时不可用')
  } finally {
    maintenanceRiskLoading.value = false
  }
}

const confirmBatchAssign = async () => {
  const total = Number(dispatchSummary.value.total_dispatchable ?? dispatchSummary.value.unassigned_orders ?? 0)
  const pendingReview = Number(dispatchSummary.value.pending_review_orders || 0)
  if (!total || batchAssigning.value) return
  try {
    await ElMessageBox.confirm(
      `AI 将先对 ${pendingReview} 个待审核工单中高置信度（≥70%）的自动过审，再按优先级为最多 ${Math.min(total, 50)} 个待派工单重算最佳人选；低置信度与触发疲劳/容量保护的工单会保留待人工处理。`,
      '确认启动一键安全派单（含自动过审）？',
      {
        confirmButtonText: '确认智能派单',
        cancelButtonText: '再检查一下',
        type: 'warning',
        distinguishCancelAndClose: true,
      },
    )
  } catch (action) {
    return
  }

  batchAssigning.value = true
  try {
    const response = await api.batchAutoAssignWorkOrders({ assigned_by: '物业管理员', limit: 50 })
    const result = response.data || {}
    const approved = result.auto_approved_count || 0
    const assigned = result.assigned_count || 0
    const skipped = result.skipped_count || 0
    if (assigned || approved) {
      const parts = []
      if (approved) parts.push(`自动过审 ${approved} 单`)
      if (assigned) parts.push(`安全派单 ${assigned} 单`)
      const skipInfo = skipped ? `，另有 ${skipped} 单因保护/低置信度暂缓` : ''
      ElMessage.success(`${parts.join('，')}${skipInfo}`)
    } else {
      ElMessage.warning(skipped ? `${skipped} 个工单均触发保护/需人工审核，已保留待处理` : '当前没有可自动分配的工单')
    }
    await Promise.all([loadOrders(), loadStats(), loadDispatchOverview()])
  } catch (error) {
    ElMessage.error(getErrorMessage(error, '批量智能派单失败'))
    await loadDispatchOverview()
  } finally {
    batchAssigning.value = false
  }
}

const loadRepeatWarnings = async () => {
  const results = await Promise.allSettled(['1302', '805', '503'].map(houseId => api.getMaintenanceHistory(houseId)))
  repeatWarnings.value = results.flatMap(result => result.status === 'fulfilled' ? (result.value.data.repeat_warnings || []) : [])
}

onMounted(() => {
  Promise.all([
    loadOrders(),
    loadStats(),
    loadDispatchOverview(),
    loadMaintenanceRisks(),
    loadRepeatWarnings(),
  ])
})
</script>

<style scoped>
.page-heading { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 18px; }
.page-heading .section-title { margin-bottom: 2px; }
.page-heading p { color: var(--text-secondary); }

.stats-row { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 14px; margin-bottom: 16px; }
.stat-card { text-align: center; padding: 18px 12px; margin-bottom: 0; }
.stat-value { font-size: 30px; line-height: 1.2; font-weight: 700; color: var(--text-primary); }
.stat-warn { color: #ea580c; }
.stat-primary { color: #2563eb; }
.stat-info { color: #0891b2; }
.stat-success { color: #16a34a; }
.stat-label { font-size: 13px; color: var(--text-secondary); margin-top: 5px; }

.dispatch-center { padding: 0; overflow: hidden; border: 1px solid #dbeafe; }
.dispatch-header { display: flex; align-items: center; justify-content: space-between; gap: 24px; padding: 22px; color: #fff; background: linear-gradient(118deg, #172554 0%, #1d4ed8 58%, #0ea5e9 100%); }
.dispatch-heading { display: flex; align-items: center; gap: 14px; min-width: 0; }
.dispatch-heading h3, .prediction-title h3 { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; font-size: 20px; line-height: 1.35; }
.dispatch-heading p { margin-top: 5px; color: #dbeafe; }
.ai-mark, .prediction-mark { display: grid; place-items: center; flex: 0 0 auto; width: 46px; height: 46px; border-radius: 14px; font-size: 24px; background: rgba(255, 255, 255, .16); }
.dispatch-actions { display: flex; align-items: center; justify-content: flex-end; flex-wrap: wrap; gap: 9px; }
.dispatch-actions .el-button { margin-left: 0; }
.updated-at { width: 100%; text-align: right; font-size: 12px; color: #bfdbfe; }
.dispatch-error { margin: 20px; width: auto; }

.dispatch-summary { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: 12px; padding: 20px 20px 0; }
.summary-item { min-width: 0; padding: 14px; border: 1px solid #e2e8f0; border-radius: 12px; background: #f8fafc; }
.summary-item span, .summary-item small { display: block; color: #64748b; }
.summary-item strong { display: block; margin: 3px 0; font-size: 26px; line-height: 1.2; color: #0f172a; }
.summary-item small { font-size: 11px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.summary-primary strong { color: #2563eb; }
.summary-success strong { color: #16a34a; }
.summary-danger strong { color: #dc2626; }
.summary-warning strong { color: #d97706; }
.balance-item .el-progress { margin-top: 8px; }

.dispatch-columns { display: grid; grid-template-columns: minmax(0, 1.3fr) minmax(300px, .7fr); gap: 16px; padding: 16px 20px 0; }
.dispatch-panel { min-width: 0; padding: 17px; border: 1px solid #e2e8f0; border-radius: 14px; }
.panel-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 14px; }
.panel-heading h4 { font-size: 16px; color: #0f172a; }
.panel-heading p { margin-top: 2px; font-size: 12px; color: #64748b; }
.repairer-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.repairer-card { min-width: 0; padding: 13px; border: 1px solid #e2e8f0; border-radius: 11px; background: #fff; }
.repairer-top, .repairer-top > div { display: flex; align-items: center; justify-content: space-between; gap: 7px; }
.repairer-top strong { color: #0f172a; }
.skill-list { display: flex; gap: 5px; flex-wrap: wrap; margin-top: 9px; }
.load-metrics { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin: 11px 0; }
.load-metrics > div { padding: 8px; border-radius: 8px; background: #f8fafc; }
.load-metrics span, .load-metrics b { display: block; }
.load-metrics span { font-size: 11px; color: #64748b; }
.load-metrics b { margin-top: 2px; color: #334155; }
.fatigue-row { display: grid; grid-template-columns: 58px 1fr; align-items: center; gap: 8px; font-size: 12px; color: #64748b; }
.protection-note { display: flex; align-items: flex-start; gap: 5px; margin-top: 9px; padding: 7px 8px; border-radius: 7px; font-size: 11px; line-height: 1.45; color: #b91c1c; background: #fef2f2; }
.protection-note .el-icon { flex: 0 0 auto; margin-top: 2px; }

.sla-list { display: flex; flex-direction: column; gap: 8px; }
.sla-item { width: 100%; padding: 10px; appearance: none; text-align: left; font: inherit; color: inherit; cursor: pointer; border: 1px solid #e2e8f0; border-radius: 9px; background: #fff; transition: border-color .2s, transform .2s; }
.sla-item:hover { border-color: #93c5fd; transform: translateY(-1px); }
.sla-item-top { display: flex; justify-content: space-between; align-items: flex-start; gap: 8px; margin-bottom: 8px; }
.sla-item-top strong, .sla-item-top span { display: block; }
.sla-item-top strong { font-size: 12px; color: #1e293b; }
.sla-item-top span { margin-top: 1px; font-size: 11px; color: #64748b; }
.sla-item-bottom { display: flex; justify-content: space-between; gap: 8px; margin-top: 6px; font-size: 11px; color: #64748b; }
.sla-item-bottom span:last-child { flex: 0 0 auto; }

.dispatch-queue { margin: 16px 20px 20px; padding: 17px; border: 1px solid #e2e8f0; border-radius: 14px; }
.queue-heading { margin-bottom: 8px; }

.prediction-card { border: 1px solid #d1fae5; }
.prediction-header { display: flex; align-items: center; justify-content: space-between; gap: 18px; margin-bottom: 16px; }
.prediction-title { display: flex; align-items: center; gap: 13px; }
.prediction-title p { margin-top: 4px; color: #64748b; }
.prediction-mark { color: #047857; background: #d1fae5; }
.prediction-summary { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; }
.prediction-summary span { padding: 7px 10px; border-radius: 999px; font-size: 12px; color: #475569; background: #f1f5f9; }
.prediction-summary b { font-size: 15px; color: #0f172a; }
.prediction-list { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.prediction-item { min-width: 0; padding: 14px; border: 1px solid #e2e8f0; border-radius: 12px; background: #fbfefd; }
.prediction-item-top { display: flex; justify-content: space-between; gap: 10px; }
.prediction-item-top > div:first-child { min-width: 0; }
.prediction-item-top strong, .prediction-item-top span { display: block; }
.prediction-item-top strong { margin-top: 7px; color: #0f172a; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.prediction-item-top span { font-size: 12px; color: #64748b; }
.health-score { flex: 0 0 54px; width: 54px; height: 54px; display: grid; align-content: center; text-align: center; border-radius: 50%; color: #b45309; background: #fef3c7; }
.health-score b, .health-score small { display: block; line-height: 1.05; }
.health-score b { font-size: 19px; }
.health-score small { margin-top: 3px; font-size: 9px; }
.health-high { color: #b91c1c; background: #fee2e2; }
.health-low { color: #047857; background: #d1fae5; }
.prediction-action { display: grid; grid-template-columns: 34px 1fr; gap: 7px; margin-top: 13px; padding-top: 11px; border-top: 1px dashed #cbd5e1; }
.prediction-action span { font-size: 11px; color: #64748b; }
.prediction-action p { font-size: 12px; line-height: 1.6; color: #334155; }
.prediction-meta { display: flex; flex-direction: column; gap: 2px; margin-top: 8px; font-size: 10px; color: #94a3b8; }

.conf-display { display: flex; align-items: center; gap: 16px; }
.conf-display span { font-weight: 600; white-space: nowrap; }
.conf-display .el-progress { flex: 1; }
.filter-bar { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.filter-bar .el-input { flex: 0 0 200px; }
.order-table-card { overflow: hidden; }
.repeat-warning { margin-bottom: 8px; }
.repeat-warning:last-child { margin-bottom: 0; }

@media (max-width: 1080px) {
  .dispatch-summary { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .dispatch-columns { grid-template-columns: 1fr; }
  .prediction-list { grid-template-columns: 1fr; }
}

@media (max-width: 760px) {
  .stats-row { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .stats-row .stat-card:last-child { grid-column: span 2; }
  .dispatch-header, .prediction-header { align-items: flex-start; flex-direction: column; }
  .dispatch-actions, .prediction-summary { width: 100%; justify-content: flex-start; }
  .updated-at { text-align: left; }
  .dispatch-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); padding: 14px 14px 0; }
  .dispatch-columns { padding: 14px 14px 0; }
  .repairer-grid { grid-template-columns: 1fr; }
  .dispatch-queue { margin: 14px; padding: 12px; overflow: hidden; }
  .filter-bar { align-items: stretch; flex-direction: column; }
  .filter-bar .el-radio-group { display: flex; overflow-x: auto; }
  .filter-bar .el-input { flex: 0 0 auto; width: 100%; }
  .conf-display { align-items: stretch; flex-direction: column; }
}

@media (max-width: 460px) {
  .dispatch-heading, .prediction-title { align-items: flex-start; }
  .ai-mark, .prediction-mark { width: 40px; height: 40px; }
  .dispatch-summary { grid-template-columns: 1fr 1fr; }
  .summary-item { padding: 11px; }
  .summary-item strong { font-size: 23px; }
  .dispatch-actions .el-button { flex: 1; }
  .dispatch-actions .el-button:last-child { flex-basis: 100%; }
}
</style>
