<template>
  <section class="card sensing-card" v-loading="loading">
    <div class="sensing-header">
      <div class="sensing-title">
        <div class="sensing-mark">💧⚡</div>
        <div>
          <h3>主动感知 · 水电安全 <el-tag size="small" type="info">模拟数据</el-tag></h3>
          <p>传感器数据自动发现进水堵塞、暗漏爆管、漏电与电压异常，并定位到部件或回路；紧急情况自动关阀/建单，其余先提醒住户，复查仍未恢复再建单。</p>
        </div>
      </div>
      <div class="sensing-actions">
        <el-select v-model="houseId" style="width: 90px" @change="loadAll">
          <el-option v-for="h in houseOptions" :key="h" :label="h" :value="h" />
        </el-select>
        <el-select v-model="detector" style="width: 180px" placeholder="检测类型" @change="pickFirstScenario">
          <el-option v-for="(label, key) in detectorOptions" :key="key" :label="label" :value="key" />
        </el-select>
        <el-select v-model="scenario" style="width: 210px" placeholder="样例数据">
          <el-option v-for="s in scenarioOptions" :key="s.scenario" :label="scenarioLabel(s.scenario)" :value="s.scenario" />
        </el-select>
        <el-button type="primary" :loading="running" :disabled="!scenario" @click="runDetection">运行检测</el-button>
        <el-button :loading="resetting" @click="resetDemo">重置演示</el-button>
      </div>
    </div>

    <el-alert v-if="error" type="warning" :closable="false" show-icon :title="error" class="sensing-alert" />
    <el-alert v-else-if="!samples.length && !loading" type="info" :closable="false" show-icon class="sensing-alert"
              title="暂无样例数据：请先运行 data/scripts/run_sample_blockage.py、run_sample_water_leak.py、run_sample_power.py 生成模拟传感器数据" />

    <div v-if="lastRun && !lastRun.events.length" class="run-result">
      <div class="run-result-text"><b>{{ scenarioLabel(lastRun.scenario) }}</b>：{{ statusText(lastRun.detector, lastRun.detection_status) }}</div>
      <div class="run-charts">
        <SensingChart v-for="(c, i) in lastRun.charts" :key="i" :chart="c" />
      </div>
    </div>

    <el-empty v-if="!events.length && !loading" description="暂无感知事件" :image-size="54" />
    <div v-else class="event-list">
      <article v-for="ev in events" :key="ev.event_id" class="event-item" :class="{ 'event-critical': ev.severity === 'CRITICAL' }">
        <div class="event-top">
          <div class="event-main">
            <div class="event-tags">
              <span class="domain-mark">{{ ev.domain === 'POWER' ? '⚡' : '💧' }}</span>
              <el-tag size="small" :type="severityTag(ev.severity)">{{ severityLabel(ev.severity) }}</el-tag>
              <el-tag size="small" effect="plain">{{ typeLabel(ev.event_type) }}</el-tag>
              <el-tag v-if="ev.scope === 'BUILDING'" size="small" type="warning" effect="plain">楼栋公共</el-tag>
              <el-tag size="small" :type="statusTag(ev.status)" effect="plain">{{ statusLabel(ev.status) }}</el-tag>
              <span class="event-id">{{ ev.event_id }}</span>
            </div>
            <strong>{{ ev.fault_summary }}</strong>
            <p class="event-evidence">{{ ev.evidence_text }}</p>
            <p v-for="a in ev.control_actions_taken || []" :key="a.action + a.executed_at" class="control-line">
              ✅ {{ controlLabel(a.action) }}（{{ a.target }}，{{ formatTime(a.executed_at) }}，{{ a.result === 'SUCCESS' ? '成功' : '失败' }}）
            </p>
          </div>
          <div class="event-side">
            <span>检测于 {{ formatTime(ev.detected_at) }}</span>
            <span v-if="ev.recheck_due && ev.status === 'NOTIFIED'">复查日 {{ ev.recheck_due }}</span>
            <el-link v-if="ev.work_order_id" type="primary" :underline="false" @click="$router.push(`/workorder/${ev.work_order_id}`)">
              工单 {{ ev.work_order_id }}
            </el-link>
          </div>
        </div>
        <div class="event-actions">
          <el-button size="small" @click="toggleDetail(ev.event_id)">{{ expanded === ev.event_id ? '收起' : '定位与趋势' }}</el-button>
          <el-button size="small" @click="$router.push({ path: '/twin', query: { role: 'property', event: ev.event_id, house: ev.house_id || undefined, live: 1 } })">3D 定位</el-button>
          <template v-if="ev.status === 'NOTIFIED'">
            <el-button v-if="RECHECKABLE.includes(ev.event_type)" size="small" :loading="acting === `recheck-${ev.event_id}`" @click="recheck(ev)">复查</el-button>
            <el-button size="small" type="primary" plain :loading="acting === `order-${ev.event_id}`" @click="createOrder(ev)">直接建单</el-button>
          </template>
        </div>
        <div v-if="expanded === ev.event_id && detail" class="event-detail">
          <div class="candidates">
            <template v-if="detail.event.location_candidates?.length">
              <div class="detail-label">定位候选</div>
              <div v-for="c in detail.event.location_candidates" :key="c.segment_code + (c.device_code || '')" class="candidate">
                <div class="candidate-line">
                  <span class="candidate-name">{{ c.segment_name }}</span>
                  <span class="candidate-code">{{ c.device_code || c.segment_code }}{{ c.in_archive ? '' : '（模拟拓扑）' }}</span>
                </div>
                <el-progress :percentage="Math.round(c.confidence * 100)" :stroke-width="8" />
              </div>
            </template>
            <template v-if="detail.event.evidence?.appliances_at_risk?.length">
              <div class="detail-label">超出允许电压的电器</div>
              <p v-for="r in detail.event.evidence.appliances_at_risk" :key="r.appliance" class="notice-line">
                {{ r.name }}（允许 {{ r.range_v[0] }}–{{ r.range_v[1] }} V）：{{ r.minutes_outside }} 分钟
              </p>
            </template>
            <template v-if="detail.event.evidence?.source_inference">
              <div class="detail-label">原因判断</div>
              <p class="notice-line">{{ inferenceText(detail.event.evidence) }}</p>
            </template>
            <div class="detail-label">已发出的提醒</div>
            <p v-for="g in groupNotices(detail.notices)" :key="g.key" class="notice-line">
              {{ audienceLabel(g.audience) }}{{ g.audience === 'PROPERTY' ? '' : g.houses.length > 1 ? ` ${g.houses.length} 户` : ` ${g.houses[0]}` }} · {{ g.title }} ·
              {{ Object.entries(g.statuses).map(([s, c]) => g.houses.length > 1 ? `${noticeStatusLabel(s)} ${c}` : noticeStatusLabel(s)).join('，') }}
            </p>
            <div class="detail-label">维修安全提示</div>
            <p class="notice-line">{{ (detail.decision.workorders?.[0]?.worker_safety_notice || []).join('；') || '—' }}</p>
          </div>
          <SensingChart v-if="detail.diagnostics?.chart" :chart="detail.diagnostics.chart" />
        </div>
      </article>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '../api'
import SensingChart from './SensingChart.vue'

const emit = defineEmits(['workorder-created'])

const RECHECKABLE = ['SUPPLY_BLOCKAGE', 'HIDDEN_LEAK']
const houseOptions = ['1302']
const houseId = ref('1302')
const samples = ref([])
const detectorOptions = ref({})
const detector = ref('water_leak')
const scenario = ref('')
const events = ref([])
const loading = ref(false)
const running = ref(false)
const resetting = ref(false)
const acting = ref('')
const error = ref('')
const lastRun = ref(null)
const expanded = ref('')
const detail = ref(null)

const SCENARIO_LABELS = {
  fault: '花洒头渐进结垢（故障）',
  control_normal: '正常使用（对照）',
  control_pressure_dip: '供水压力下降（干扰）',
  hidden_leak: '马桶进水阀暗漏（故障）',
  pipe_burst: '厨房软管脱落爆管（故障）',
  control_night_use: '频繁夜间用水（干扰）',
  leakage_gradual: '卫生间回路绝缘劣化（故障）',
  leakage_wet: '厨房插座进水跳闸（故障）',
  control_humid: '梅雨季高湿（干扰）',
  voltage_supply_high: '供电侧夜间过电压（故障）',
  voltage_house_neutral: '本户零线端子松动（故障）',
}
const TYPE_LABELS = {
  SUPPLY_BLOCKAGE: '进水堵塞', HIDDEN_LEAK: '暗漏', PIPE_BURST: '爆管', LEAKAGE_CURRENT: '漏电', VOLTAGE_ABNORMAL: '电压异常',
}
const scenarioOptions = computed(() => samples.value.filter(s => s.detector === detector.value))
const scenarioLabel = s => SCENARIO_LABELS[s] || s
const typeLabel = t => TYPE_LABELS[t] || t
const statusText = (det, s) => ({
  NO_EVENT: { supply_blockage: '未发现进水堵塞', water_leak: '未发现暗漏或爆管', power_safety: '未发现漏电或电压异常' }[det] || '未发现异常',
  INSUFFICIENT_DATA: '数据不足，基线尚未建立',
  EVENT: '发现异常',
})[s] || s
const severityLabel = s => ({ LOW: '低', MEDIUM: '中', HIGH: '高', CRITICAL: '严重' })[s] || s
const severityTag = s => ({ LOW: 'info', MEDIUM: 'warning', HIGH: 'danger', CRITICAL: 'danger' })[s] || 'info'
const statusLabel = s => ({ NOTIFIED: '已提醒住户', ORDER_CREATED: '已建单', RESOLVED: '已解决', ARCHIVED: '已归档' })[s] || s
const statusTag = s => ({ NOTIFIED: 'warning', ORDER_CREATED: 'primary', RESOLVED: 'success', ARCHIVED: 'info' })[s] || 'info'
const noticeStatusLabel = s => ({ UNREAD: '未读', READ: '已读', REPAIR_REQUESTED: '住户已报修', DISMISSED: '已关闭', ARCHIVED: '已归档' })[s] || s
const audienceLabel = a => ({ RESIDENT: '住户', NEIGHBOR: '相关住户', FAMILY: '家属', PROPERTY: '物业' })[a] || a
const controlLabel = a => ({ CLOSE_MAIN_VALVE: '已自动关闭入户总阀', CLOSE_BRANCH_VALVE: '已关闭支路阀门', TRIP_CIRCUIT: '漏电保护已跳闸断电', SWITCH_OFF_PLUG: '已关闭智能插座', SPEAKER_INQUIRY: '已语音询问' })[a] || a
const inferenceText = e => ({
  SUPPLY: `供电侧问题：同为 ${e.phase} 相的邻户 ${Math.round(e.same_phase_abnormal_ratio * 100)}% 同时越限，其它相 ${Math.round(e.other_phase_abnormal_ratio * 100)}%，已通知物业联系供电部门`,
  HOUSE_WIRING: `本户接线问题：邻户正常，本户电压随用电电流明显下降，等效线路电阻 ${e.wiring_resistance_ohm} Ω（入住初期 ${e.wiring_resistance_baseline_ohm} Ω），疑似进线或零线端子松动`,
  UNKNOWN: '原因未定，需电工上门测量',
})[e.source_inference] || ''
// 楼栋级事件会给同相几十户发同样的提醒，按"对象 + 标题"合并显示
const groupNotices = notices => Object.values(notices.reduce((acc, n) => {
  const key = `${n.audience}|${n.title}`
  const g = acc[key] || (acc[key] = { key, audience: n.audience, title: n.title, houses: [], statuses: {} })
  g.houses.push(n.house_id)
  g.statuses[n.status] = (g.statuses[n.status] || 0) + 1
  return acc
}, {}))
// 后端时间带 +08:00，直接截取显示，避免浏览器按本机时区换算
const formatTime = t => t ? String(t).replace('T', ' ').slice(5, 16) : ''
const errMsg = (e, fallback) => e?.response?.data?.detail?.message || e?.response?.data?.detail || fallback

const pickFirstScenario = () => {
  if (!scenarioOptions.value.some(x => x.scenario === scenario.value)) scenario.value = scenarioOptions.value[0]?.scenario || ''
}

const loadEvents = async () => {
  const res = await api.getSensingEvents({ house_id: houseId.value })
  events.value = res.data.events || []
}

const loadAll = async () => {
  loading.value = true
  error.value = ''
  try {
    const [s] = await Promise.all([api.getSensingSamples(houseId.value), loadEvents()])
    samples.value = s.data.samples || []
    detectorOptions.value = s.data.detectors || {}
    if (!samples.value.some(x => x.detector === detector.value)) detector.value = samples.value[0]?.detector || ''
    pickFirstScenario()
  } catch (e) {
    error.value = errMsg(e, '主动感知数据加载失败')
  } finally {
    loading.value = false
  }
}

const runDetection = async () => {
  running.value = true
  try {
    const res = await api.runSensingDetection(houseId.value, detector.value, scenario.value)
    lastRun.value = res.data
    const evs = res.data.events || []
    if (evs.length) {
      const created = evs.filter(e => e.created)
      ElMessage[created.some(e => e.severity === 'CRITICAL') ? 'error' : 'success'](
        created.length ? `发现 ${created.length} 个异常：${created.map(e => e.fault_summary).join('；')}` : '该样例的事件已存在（如需重演请先重置）')
      await loadEvents()
      if (evs.some(e => e.work_order_id)) emit('workorder-created')
      expanded.value = ''
      await toggleDetail(evs[0].event_id)
    } else {
      ElMessage.info(statusText(res.data.detector, res.data.detection_status))
    }
  } catch (e) {
    ElMessage.error(errMsg(e, '检测失败'))
  } finally {
    running.value = false
  }
}

const resetDemo = async () => {
  resetting.value = true
  try {
    const res = await api.resetSensingDemo(houseId.value)
    const { deleted_events: deleted, archived_events: archived, kept_open_events: kept } = res.data
    const parts = []
    if (deleted.length) parts.push(`清除 ${deleted.length} 个未建单事件`)
    if (archived.length) parts.push(`归档 ${archived.length} 个工单已完结的事件`)
    if (kept.length) {
      ElMessage.warning(`${parts.length ? parts.join('，') + '；' : ''}${kept.length} 个事件的工单仍在处理中（${kept.map(k => k.work_order_id).join('、')}），完工后才能重置`)
    } else {
      ElMessage.success(parts.length ? `已${parts.join('，')}，可以重新运行检测` : '没有需要重置的演示事件')
    }
    lastRun.value = null
    expanded.value = ''
    await loadEvents()
  } catch (e) {
    ElMessage.error(errMsg(e, '重置失败'))
  } finally {
    resetting.value = false
  }
}

const toggleDetail = async (eventId) => {
  if (expanded.value === eventId) {
    expanded.value = ''
    return
  }
  const res = await api.getSensingEvent(eventId)
  detail.value = res.data
  expanded.value = eventId
}

const recheck = async (ev) => {
  acting.value = `recheck-${ev.event_id}`
  try {
    const res = await api.recheckSensingEvent(ev.event_id)
    const d = res.data
    if (d.still_abnormal) {
      ElMessage.warning(`${d.recheck_day} 复查仍未恢复（${d.detail}），已生成工单 ${d.work_order_id}`)
      emit('workorder-created')
    } else if (d.rechecked) {
      ElMessage.success(`${d.recheck_day} 复查已恢复（${d.detail}），事件解除`)
    } else {
      ElMessage.info(d.reason)
    }
    await loadEvents()
  } catch (e) {
    ElMessage.error(errMsg(e, '复查失败'))
  } finally {
    acting.value = ''
  }
}

const createOrder = async (ev) => {
  try {
    await ElMessageBox.confirm('不等住户报修或复查，直接按检测结果生成待审核工单？', '直接建单', { type: 'warning' })
  } catch {
    return
  }
  acting.value = `order-${ev.event_id}`
  try {
    const res = await api.createSensingWorkOrder(ev.event_id)
    ElMessage.success(`已生成工单 ${res.data.work_order_id}，进入待审核`)
    emit('workorder-created')
    await loadEvents()
  } catch (e) {
    ElMessage.error(errMsg(e, '建单失败'))
  } finally {
    acting.value = ''
  }
}

onMounted(loadAll)
</script>

<style scoped>
.sensing-card { border: 1px solid #cffafe; }
.sensing-header { display: flex; align-items: center; justify-content: space-between; gap: 18px; margin-bottom: 14px; flex-wrap: wrap; }
.sensing-title { display: flex; align-items: center; gap: 13px; min-width: 0; }
.sensing-title h3 { display: flex; align-items: center; gap: 8px; font-size: 20px; line-height: 1.35; }
.sensing-title p { margin-top: 4px; color: #64748b; }
.sensing-mark { display: grid; place-items: center; flex: 0 0 auto; width: 56px; height: 46px; border-radius: 14px; font-size: 18px; background: #cffafe; }
.sensing-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.sensing-actions .el-button { margin-left: 0; }
.sensing-alert { margin-bottom: 12px; }
.run-result { padding: 12px 14px; margin-bottom: 12px; border: 1px dashed #cbd5e1; border-radius: 12px; }
.run-result-text { margin-bottom: 8px; font-size: 13px; color: #334155; }
.run-charts { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 16px; }
.event-list { display: flex; flex-direction: column; gap: 12px; }
.event-item { padding: 14px; border: 1px solid #e2e8f0; border-radius: 12px; background: #fbfdff; }
.event-critical { border-color: #fecaca; background: #fffafa; }
.event-top { display: flex; justify-content: space-between; gap: 16px; }
.event-main { min-width: 0; }
.event-tags { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; margin-bottom: 6px; }
.domain-mark { font-size: 15px; }
.event-id { font-size: 12px; color: #64748b; font-family: monospace; }
.event-main strong { color: #0f172a; }
.event-evidence { margin-top: 4px; font-size: 13px; color: #475569; line-height: 1.6; }
.control-line { margin-top: 4px; font-size: 12px; color: #15803d; }
.event-side { display: flex; flex-direction: column; align-items: flex-end; gap: 2px; flex: 0 0 auto; font-size: 12px; color: #64748b; }
.event-actions { display: flex; gap: 8px; margin-top: 10px; }
.event-actions .el-button { margin-left: 0; }
.event-detail { display: grid; grid-template-columns: minmax(0, .9fr) minmax(0, 1.1fr); gap: 18px; margin-top: 12px; padding-top: 12px; border-top: 1px solid #e2e8f0; }
.detail-label { margin: 8px 0 4px; font-size: 12px; font-weight: 600; color: #334155; }
.detail-label:first-child { margin-top: 0; }
.candidate { margin-bottom: 8px; font-size: 12px; }
.candidate-line { display: flex; justify-content: space-between; gap: 8px; flex-wrap: wrap; margin-bottom: 2px; }
.candidate-name { color: #0f172a; }
.candidate-code { color: #64748b; font-family: monospace; }
.notice-line { font-size: 12px; color: #475569; line-height: 1.6; }
@media (max-width: 900px) { .event-detail { grid-template-columns: 1fr; } .event-top { flex-direction: column; } .event-side { align-items: flex-start; } }
</style>
