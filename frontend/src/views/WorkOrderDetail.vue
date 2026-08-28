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
          <!-- 阶段5.7：独立派单入口，仅「已审核通过且未派单」显示 -->
          <el-button v-if="showAssignBtn" type="primary" @click="openAssignDialog">
            派单
          </el-button>
          <!-- 阶段5.8：开始维修入口，仅「已派单待开始」显示（pending_assign + assigned_to 非空） -->
          <el-button v-if="showStartRepairBtn" type="success" :loading="starting" @click="startRepair">
            开始维修
          </el-button>
          <el-button v-if="order.status === 'processing'" type="success" @click="openCompleteDialog">
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
          <el-descriptions-item label="维修人员" v-if="order.assigned_to">{{ order.assigned_to }}</el-descriptions-item>
          <el-descriptions-item label="完成时间" v-if="order.completed_at">{{ formatTime(order.completed_at) }}</el-descriptions-item>
          <el-descriptions-item label="实际故障" :span="2" v-if="order.actual_fault">{{ order.actual_fault }}</el-descriptions-item>
          <el-descriptions-item label="处理方式" :span="2" v-if="order.actual_action">{{ order.actual_action }}</el-descriptions-item>
          <el-descriptions-item label="使用部件" v-if="order.used_parts">{{ order.used_parts }}</el-descriptions-item>
          <el-descriptions-item label="结果" v-if="order.result">{{ order.result }}</el-descriptions-item>
        </el-descriptions>
      </div>

      <!-- Related Equipment（阶段5.10：改用 GET /houses/{id}/components 获取设备，
           不再依赖 getHouse 返回的 components（该字段后端从不返回）） -->
      <div v-if="relatedEquipment.length" class="card">
        <h3 class="section-title">关联设备（来自一房一码档案）</h3>
        <el-table :data="relatedEquipment" border size="small">
          <el-table-column prop="name" label="设备名称" width="120" />
          <el-table-column prop="spec" label="规格型号" width="120" />
          <el-table-column prop="device_code" label="设备编号" width="160" />
          <el-table-column prop="location" label="位置" width="100" />
          <el-table-column prop="manufacturer" label="厂家" width="100" />
          <el-table-column prop="installDate" label="安装日期" />
        </el-table>
      </div>
      <!-- 空状态：工单声明了关联设备，但房屋查无匹配设备时给出提示，不报错 -->
      <div v-else-if="equipmentMissing" class="card">
        <h3 class="section-title">关联设备（来自一房一码档案）</h3>
        <el-empty description="该工单关联的设备未在房屋档案中找到" :image-size="60" />
      </div>

      <!-- 阶段3：【故障记忆】卡片 —— 展示同设备近180天历史维修记录 + 重复故障提醒 + AI维修连续性建议。
           数据来自独立接口 getFaultMemory（GET /workorders/{order_no}/fault-memory），
           在工单详情加载成功后自动请求一次；v-loading 显示加载遮罩。
           请求失败只显示下方兜底文案，绝不影响工单基本信息 / 审核 / 派单 / 维修。 -->
      <div class="card" v-loading="faultMemoryLoading">
        <h3 class="section-title">故障记忆</h3>

        <!-- 请求失败兜底：与工单其它功能完全隔离 -->
        <el-empty v-if="faultMemoryError" description="故障记忆加载失败，不影响当前工单操作" :image-size="60" />

        <template v-else-if="faultMemory">
          <!-- 重复故障警告（>=2次历史维修时置顶展示）。
               用黄色警告而不是红色错误：老修不好是「关注/提醒」，不是系统故障。 -->
          <el-alert
            v-if="faultMemory.is_repeat_fault"
            type="warning"
            :closable="false"
            show-icon
            title="⚠ 重复故障"
            class="repeat-fault-alert"
          >
            <div>该设备近 {{ faultMemory.time_range_days }} 天存在 {{ faultMemory.history_count }} 次历史维修，当前再次发生相关故障。</div>
          </el-alert>

          <!-- 无法识别设备：后端返回的 message 优先展示，不显示时间线 -->
          <el-empty
            v-if="faultMemory.can_identify_device === false"
            :description="faultMemory.message || '暂无法准确查询设备历史维修记录'"
            :image-size="60"
          />

          <template v-else-if="faultMemory.has_history">
            <!-- 设备概览：设备名 + 近180天次数说明 -->
            <div class="fm-summary">
              <el-tag type="info" effect="plain">{{ faultMemory.device_name || '未知设备' }}</el-tag>
              <span>该设备近 {{ faultMemory.time_range_days }} 天存在 {{ faultMemory.history_count }} 次相关维修记录</span>
            </div>

            <!-- 历史维修时间线：重点展示 日期/工单号/原始报修/实际故障/维修措施，
                 配件/维修人/结果为次要文字（有才显示，页面不拥挤）。
                 最后追加「当前工单」节点，帮用户理解：过去维修 → 过去维修 → 当前再次报修。 -->
            <el-timeline class="fm-timeline">
              <el-timeline-item
                v-for="h in faultMemory.history"
                :key="h.order_no"
                :timestamp="formatTime(h.created_at)"
                placement="top"
              >
                <div class="fm-history-item">
                  <div class="fm-line">工单 {{ h.order_no }}</div>
                  <div class="fm-line">原始报修：{{ h.original_description || '—' }}</div>
                  <div class="fm-line">实际故障：{{ h.actual_fault || '—' }}</div>
                  <div class="fm-line">维修措施：{{ h.actual_action || '—' }}</div>
                  <div class="fm-sub" v-if="h.used_parts || h.repair_person || h.result">
                    配件：{{ h.used_parts || '—' }} ｜ 维修人：{{ h.repair_person || '—' }} ｜ 结果：{{ h.result || '—' }}
                  </div>
                </div>
              </el-timeline-item>
              <el-timeline-item timestamp="当前工单" placement="top" color="#e6a23c">
                <div class="fm-line">本次报修（{{ faultMemory.order_no }}），请使用上方按钮进行审核 / 派单 / 维修</div>
              </el-timeline-item>
            </el-timeline>

            <!-- AI维修连续性建议：有历史才展示该区域；AI不可用时显示「暂不可用」兜底文案 -->
            <div class="fm-ai">
              <div class="fm-ai-title">AI维修连续性建议</div>
              <p v-if="faultMemory.ai_suggestion" class="fm-ai-text">{{ faultMemory.ai_suggestion }}</p>
              <p v-else class="fm-ai-text fm-ai-muted">AI连续性建议暂不可用</p>
            </div>
          </template>

          <!-- 无历史：简洁空状态（不显示 AI 建议区域） -->
          <el-empty v-else description="暂无相关历史维修记录" :image-size="60" />
        </template>
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

    <!-- Assign Dialog（阶段5.7：独立派单，只能从在册维修人员中选择） -->
    <el-dialog v-model="showAssignDialog" title="派单" width="460px">
      <el-form label-width="100px">
        <el-form-item label="维修人员" required>
          <el-select v-model="assignForm.assigned_to" placeholder="请选择在册维修人员" filterable style="width: 100%">
            <el-option
              v-for="r in repairers"
              :key="r.id"
              :label="r.real_name"
              :value="r.real_name"
            />
          </el-select>
          <div class="form-tip">仅能选择维修人员名单中的人员，不能手动输入</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showAssignDialog = false">取消</el-button>
        <el-button type="primary" :disabled="!assignForm.assigned_to" @click="submitAssign">确认派单</el-button>
      </template>
    </el-dialog>

    <!-- Complete Dialog -->
    <el-dialog v-model="showCompleteDialog" title="完成维修" width="500px">
      <el-form label-width="100px">
        <el-form-item label="维修人员">
          <!-- 阶段5.9：自动带出本工单已指派的维修人，禁止手动输入。
               完成后端 complete 的「完成人必须=派单人」校验；后端仍会只读校验兜底 -->
          <el-input v-model="completeForm.repair_person" disabled />
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
// 阶段5.10：房屋设备清单（GET /houses/{id}/components 返回的按分类分组对象，
// 如 {"plumbing":[...], "electrical":[...]}）。不再依赖 getHouse()——它不带 components 字段。
const houseComponents = ref({})
const showReviewDialog = ref(false)
const showCompleteDialog = ref(false)

const reviewForm = ref({
  urgency: '',
  suggested_trade: '',
  review_notes: '',
})
// 阶段5.7：独立派单表单（只存维修人员姓名，从 repairers 下拉中选择）
const showAssignDialog = ref(false)
const assignForm = ref({ assigned_to: '' })
const repairers = ref([])
const completeForm = ref({
  repair_person: '',
  actual_fault: '',
  actual_action: '',
  used_parts: '',
})

// ===== 阶段3：故障记忆（工单详情页的辅助上下文）=====
// faultMemory：保存 GET /workorders/{order_no}/fault-memory 返回的数据
// （has_history / is_repeat_fault / history[] / ai_suggestion 等）。
// 用 ref 是因为数据是异步加载的，加载完成后 Vue 会自动更新页面上
// 【故障记忆】卡片对应的区域（警告条 / 时间线 / AI建议）。
const faultMemory = ref(null)
// faultMemoryLoading：故障记忆接口请求中的标记，用于卡片 v-loading 遮罩。
const faultMemoryLoading = ref(false)
// faultMemoryError：故障记忆接口请求失败标记。失败只显示兜底文案，
// 不会抛出异常，保证审核/派单/维修等其它功能不受影响。
const faultMemoryError = ref(false)
// faultMemoryLoadedOnce：本页面是否已经请求过故障记忆。
// 为什么需要：审核/派单/完成维修成功后都会重新 loadOrder() 刷新详情，
// 而故障记忆（同设备历史维修）不会随当前工单状态变化 ——
// 若每次刷新都重新请求，就会每次刷新都重新调用 LLM 消耗 Token。
// 因此只在第一次成功拿到工单号时请求一次（组件重新挂载即进入新页面时自动重置）。
let faultMemoryLoadedOnce = false

// loadFaultMemory：加载当前工单的故障记忆。
// 触发时机：loadOrder 成功拿到工单详情（含 order_no）后立即自动调用，
// 不需要用户点按钮 —— 故障记忆是「当前工单的辅助上下文」，打开页面就该看到。
// 失败时置 faultMemoryError 显示兜底文案，不影响工单其它功能。
const loadFaultMemory = async (orderNo) => {
  if (faultMemoryLoadedOnce) return   // 本页面已加载过，不再重复请求（避免重复消耗LLM Token）
  faultMemoryLoadedOnce = true
  faultMemoryLoading.value = true
  faultMemoryError.value = false
  try {
    const res = await api.getFaultMemory(orderNo)
    faultMemory.value = res.data
  } catch (e) {
    // 失败只影响故障记忆卡片本身：显示兜底文案，其余工单功能照常
    faultMemoryError.value = true
    faultMemory.value = null
  } finally {
    faultMemoryLoading.value = false
  }
}

// 工单状态显示字典（与后端 STATUS_EN2CN 输出对齐）
// pending_assign 的 label 由 statusTag 根据是否已派单动态生成
const statusMap = {
  pending_review: { type: 'warning', label: '待审核' },
  pending_assign: { type: 'primary', label: '' },      // 动态：待派单 / 已派单·待维修
  processing: { type: 'info', label: '维修中' },
  completed: { type: 'success', label: '已完成' },
  cancelled: { type: 'info', label: '已取消' },
  rejected: { type: 'danger', label: '已驳回' },
}

const statusTag = computed(() => {
  const s = order.value?.status
  const base = statusMap[s]
  if (!base) return { type: 'info', label: s }
  if (s === 'pending_assign') {
    return { ...base, label: order.value?.assigned_to ? '已派单/待维修' : '待派单' }
  }
  return base
})

// 阶段5.7：仅在「待派单（审核通过且未派单）」时显示派单按钮
// pending_assign + assigned_to 有值 → 已派单，不再显示派单入口
const showAssignBtn = computed(() => {
  return order.value?.status === 'pending_assign' && !order.value?.assigned_to
})

// 阶段5.8：仅在「已派单待开始维修」时显示开始维修按钮
// （pending_assign + assigned_to 有值；未派单 / 维修中 / 已完成均不显示）
const showStartRepairBtn = computed(() => {
  return order.value?.status === 'pending_assign' && !!order.value?.assigned_to
})
// 阶段5.8：开始维修请求中的 loading 标记（防重复点击）
const starting = ref(false)

// 阶段5.10：关联设备 = 工单 AI 记录的设备 id 列表 ∩ 房屋档案设备清单。
// related_equipment 存的是设备数字主键（如 [1,2,3,4,5]），
// 与 /houses/{id}/components 返回的设备 id（house_device 主键）一致。
const relatedEquipment = computed(() => {
  if (!order.value) return []
  const eqIds = order.value.related_equipment || []
  const allEquip = Object.values(houseComponents.value || {}).flat()
  return allEquip.filter(e => eqIds.includes(e.id))
})

// 空状态判断：工单声明了关联设备，但房屋档案里查不到任何匹配设备
const equipmentMissing = computed(() => {
  if (!order.value) return false
  const eqIds = order.value.related_equipment || []
  return eqIds.length > 0 && relatedEquipment.value.length === 0
})

const formatTime = (t) => {
  if (!t) return ''
  return new Date(t).toLocaleString('zh-CN')
}

const submitReview = async (status) => {
  try {
    // 阶段5.7：审核不再携带 assigned_to，审核与派单彻底分离
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

// 阶段5.7：打开派单弹窗，按需加载在册维修人员列表（GET /workorders/repairers）
const openAssignDialog = async () => {
  try {
    if (!repairers.value.length) {
      const res = await api.getRepairers()
      repairers.value = res.data.repairers || []
    }
    assignForm.value.assigned_to = ''
    showAssignDialog.value = true
  } catch (e) {
    ElMessage.error('获取维修人员列表失败')
  }
}

// 阶段5.7：确认派单（PUT /workorders/{id}/assign），成功后刷新详情
const submitAssign = async () => {
  if (!assignForm.value.assigned_to) return
  try {
    await api.assignWorkOrder(route.params.id, {
      assigned_to: assignForm.value.assigned_to,
      assigned_by: '物业管理员',
    })
    ElMessage.success(`已派单给「${assignForm.value.assigned_to}」，等待开始维修`)
    showAssignDialog.value = false
    await loadOrder()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '派单失败')
  }
}

// 阶段5.8：开始维修（PUT /workorders/{id}/start）
// 显式传当前工单已指派的维修人姓名，触发后端「发起人=派单人」只读校验；
// 成功后刷新详情，状态由「已派单/待维修」变为「维修中」。
const startRepair = async () => {
  if (starting.value || !order.value?.assigned_to) return
  starting.value = true
  try {
    await api.startWorkOrder(route.params.id, { repair_person: order.value.assigned_to })
    ElMessage.success('已开始维修，工单状态更新为维修中')
    await loadOrder()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '开始维修失败')
  } finally {
    starting.value = false
  }
}

// 阶段5.9：打开完成维修弹窗时自动带出本工单已指派的维修人（只读展示）。
// 完成人必须就是派单人（后端 complete 也会只读校验），
// 用户无需手动输入姓名，也不会输错成其他维修人员。
const openCompleteDialog = () => {
  completeForm.value.repair_person = order.value?.assigned_to || ''
  showCompleteDialog.value = true
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
  // 阶段5.10：设备清单改用独立接口获取（getHouse 不带 components 字段，是关联设备
  // 一直为空的原因）。house_id 即 house_code（如 "1302"），与接口入参一致。
  try {
    const cRes = await api.getHouseComponents(res.data.house_id)
    houseComponents.value = cRes.data.components || {}
  } catch (e) {
    houseComponents.value = {}
  }

  // Pre-fill review form
  reviewForm.value.urgency = res.data.urgency || ''
  reviewForm.value.suggested_trade = res.data.suggested_trade || ''

  // 阶段3：工单详情加载成功后，自动请求一次故障记忆。
  // order_no 优先取详情数据（后端返回），兜底用路由参数 —— 两者是同一个值；
  // 不 await：故障记忆是辅助上下文，即使慢或失败也不阻塞上面的主流程。
  loadFaultMemory(res.data.order_no || route.params.id)
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
.form-tip { font-size: 12px; color: #909399; line-height: 1.6; }

/* ===== 阶段3：故障记忆卡片样式 ===== */
.repeat-fault-alert { margin-bottom: 16px; }          /* 重复故障警告与下方时间线拉开距离 */
.fm-summary { display: flex; align-items: center; gap: 10px; margin-bottom: 16px; color: #606266; font-size: 14px; }
.fm-timeline { padding-left: 4px; }                   /* 时间线与卡片左边距对齐 */
.fm-history-item { line-height: 1.8; }
.fm-line { font-size: 14px; color: #303133; }         /* 主信息：日期/工单号/报修/故障/措施 */
.fm-sub { font-size: 12px; color: #909399; margin-top: 4px; }  /* 次要信息：配件/维修人/结果 */
.fm-ai { margin-top: 16px; padding: 12px 16px; background: #f4f4f5; border-radius: 6px; }  /* AI建议灰底区块 */
.fm-ai-title { font-size: 14px; font-weight: 600; color: #303133; margin-bottom: 8px; }
.fm-ai-text { font-size: 14px; color: #606266; line-height: 1.8; margin: 0; }
.fm-ai-muted { color: #909399; }                      /* 「AI连续性建议暂不可用」的弱化文字 */
</style>
