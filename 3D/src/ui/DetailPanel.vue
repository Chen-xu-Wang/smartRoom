<template>
  <div class="detail panel scroll">
    <!-- 事件详情 -->
    <template v-if="ev">
      <div class="head">
        <span class="sev-dot big" :style="{ background: sevMeta.color }"></span>
        <div class="grow">
          <div class="title">{{ typeMeta.label }} <el-tag size="small" :type="sevMeta.tag" effect="dark">{{ sevMeta.label }}</el-tag>
            <el-tag v-if="ev.priority" size="small" effect="plain">优先级 {{ PRIORITY_LABEL[ev.priority] || ev.priority }}</el-tag></div>
          <div class="sub">{{ scopeText }} · {{ fmtTime(ev.detectedAt) }}</div>
        </div>
        <el-button text circle size="small" icon="Close" @click="store.clearEvent()" />
      </div>
      <el-alert :title="ORIGIN_LABEL[ev.origin]" :type="ev.origin === 'DETECTION_SAMPLE' || ev.origin === 'LIVE' ? 'success' : 'info'" :closable="false" show-icon class="origin" />
      <!-- 邻居家的问题：业主只看影响提示，不显示原始标题与证据（含邻居户号、监测数据） -->
      <p class="summary">{{ neighbor ? (notices[0]?.title || '附近住户或公共管线的问题可能影响您家') : ev.title }}</p>
      <p v-if="!neighbor" class="evidence sub">{{ ev.event.evidence_text }}</p>

      <section v-if="cands.length">
        <h4>定位候选</h4>
        <div v-for="(c, i) in cands" :key="c.segment_code" class="cand" @click="store.selectCode(c.segment_code)">
          <span class="rank" :class="{ first: i === 0 }">{{ i + 1 }}</span>
          <span class="grow">{{ c.segment_name }}<span class="sub code">{{ c.segment_code }}</span></span>
          <el-progress :percentage="Math.round(c.confidence * 100)" :stroke-width="6" :color="i === 0 ? sevMeta.color : '#fadb14'" style="width: 90px" />
        </div>
      </section>

      <section v-if="controls.length">
        <h4>已执行的自动控制</h4>
        <div v-for="c in controls" :key="c.action + c.target" class="ctrl" @click="c.target && store.selectCode(c.target)">
          <el-icon color="#52c41a"><CircleCheckFilled /></el-icon>
          <span>{{ CONTROL_LABEL[c.action] || c.action }}</span>
          <span class="sub code">{{ c.target }} · {{ c.result }}</span>
        </div>
      </section>

      <section v-if="chart && role !== 'repairer' && !neighbor">
        <h4>检测诊断数据</h4>
        <SensingChart :chart="chart" />
      </section>

      <section v-if="notices.length">
        <h4>提醒 <span class="sub">（{{ ownerScope ? '本户可见' : '按对象' }}）</span></h4>
        <el-card v-for="(n, i) in notices" :key="i" shadow="never" class="notice">
          <div class="notice-top">
            <el-tag size="small" :type="AUD[n.audience]?.tag">{{ AUD[n.audience]?.label || n.audience }}</el-tag>
            <strong>{{ n.title }}</strong>
            <el-tag v-if="n.house_ids?.length > 1" size="small" effect="plain">{{ n.house_ids.length }} 户</el-tag>
          </div>
          <p>{{ n.content }}</p>
          <ol v-if="n.self_check_steps?.length"><li v-for="s in n.self_check_steps" :key="s">{{ s }}</li></ol>
          <el-button v-if="role === 'owner' && n.show_repair_button" type="primary" size="small" @click="repair(n)">一键报修</el-button>
        </el-card>
      </section>

      <section v-if="orders.length && !ownerScope">
        <h4>工单</h4>
        <el-card v-for="(w, i) in orders" :key="i" shadow="never" class="order">
          <div class="notice-top">
            <el-tag size="small" :type="w.create_mode === 'IMMEDIATE' ? 'danger' : 'info'">{{ w.create_mode === 'IMMEDIATE' ? '立即建单' : `延后建单（${w.recheck_after_days ?? '-'} 天复查）` }}</el-tag>
            <strong>{{ w.fault_type }} · {{ w.suggested_trade }}</strong>
          </div>
          <div class="kv"><span>位置</span><span>{{ w.location }}</span><span>涉及住户</span><span>{{ (w.house_ids || []).join('、') }}</span><span>建议材料</span><span>{{ (w.materials || []).join('、') }}</span></div>
          <div v-if="w.worker_safety_notice?.length" class="safety">
            <div class="safety-title"><el-icon><WarningFilled /></el-icon> 作业安全提示</div>
            <ul><li v-for="s in w.worker_safety_notice" :key="s">{{ s }}</li></ul>
          </div>
          <p v-if="role !== 'repairer'" class="sub">{{ w.ai_summary }}</p>
        </el-card>
      </section>

      <div class="actions">
        <el-button type="primary" size="small" icon="Aim" @click="store.locateEvent(ev.id)">重新定位</el-button>
        <template v-if="role === 'property'">
          <el-button size="small" :disabled="['WORKORDER_CREATED', 'ORDER_CREATED'].includes(ev.status)" @click="createOrder">为事件建单</el-button>
          <el-button v-if="ev.origin === 'LIVE'" size="small" @click="recheck">复查</el-button>
        </template>
        <el-tag size="small" effect="plain">状态：{{ STATUS_LABEL[ev.status] || ev.status }}</el-tag>
      </div>
    </template>

    <!-- 构件 / 设备档案卡 -->
    <template v-else-if="card">
      <div class="head">
        <el-icon size="22" color="#1677ff"><component :is="card.icon" /></el-icon>
        <div class="grow"><div class="title">{{ card.name }}</div><div class="sub code">{{ card.code }}</div></div>
        <el-button text circle size="small" icon="Close" @click="store.selected = null" />
      </div>
      <div class="kv">
        <template v-for="row in card.rows" :key="row[0]"><span>{{ row[0] }}</span><span>{{ row[1] }}</span></template>
      </div>
      <section v-if="card.archiveText">
        <h4>档案原文</h4>
        <p class="sub">{{ card.archiveText }}</p>
      </section>
      <section v-if="isolation.length && !ownerScope">
        <h4>作业前隔离点</h4>
        <div v-for="p in isolation" :key="p.name" class="ctrl" @click="p.code && store.selectCode(p.code)">
          <el-icon color="#fa8c16"><Lock /></el-icon><span>{{ p.action }}{{ p.name }}</span><span class="sub code">{{ p.code }}</span>
        </div>
      </section>
      <section v-if="relatedEvents.length">
        <h4>相关事件</h4>
        <div v-for="e in relatedEvents" :key="e.id" class="ctrl" @click="store.locateEvent(e.id)">
          <span class="sev-dot" :style="{ background: SEVERITY_META[e.severity].color }"></span><span>{{ TYPE_META[e.type]?.label }} · {{ e.houseId || e.scope }}</span>
        </div>
      </section>
      <p v-if="!isLive" class="sub note">该楼栋结构复用 1栋模型，告警与工单数据暂未接入。</p>
    </template>

    <!-- 住户概况 -->
    <template v-else-if="houseCard">
      <div class="head">
        <el-icon size="22" color="#1677ff"><House /></el-icon>
        <div class="grow"><div class="title">{{ level.buildingNo }}栋 {{ houseCard.house_id }}室</div><div class="sub">{{ houseCard.layout }} · {{ houseCard.area_m2 }}㎡</div></div>
      </div>
      <div class="kv">
        <span>MiC 模块</span><span>{{ houseCard.mic_module_id }}</span>
        <span>生产批次</span><span>{{ houseCard.batch_id }} 批（生产 {{ houseCard.production_date }}，交付 {{ houseCard.delivery_date }}）</span>
        <span>供水分区</span><span>{{ ZONE[houseCard.supply_zone] }}，入户静压 {{ houseCard.entry_static_pressure_mpa }} MPa{{ houseCard.has_prv ? '（含减压阀）' : '' }}</span>
        <span>排水立管</span><span>{{ houseCard.drain_stack }}</span>
        <span>电气相别</span><span>{{ houseCard.phase }}</span>
        <span>档案状态</span><span>{{ houseCard.in_archive ? '一房一码正式档案' : '模拟扩展档案' }}</span>
        <template v-if="role !== 'owner' || houseCard.house_id === store.ownerHouse">
          <span>设备 / 传感器</span><span>{{ houseCard.devices.length }} 件 / {{ houseCard.sensors.length }} 个</span>
          <span>电气回路</span><span>{{ houseCard.circuits.length }} 路</span>
        </template>
      </div>
      <p class="sub note">点击房间或构件查看档案；右下角平面图与 3D 联动。</p>
      <p v-if="!isLive" class="sub note">该楼栋结构复用 1栋模型，告警与工单数据暂未接入。</p>
    </template>

    <template v-else-if="store.selected?.kind === 'facility'">
      <div class="head"><el-icon size="22" color="#1677ff"><OfficeBuilding /></el-icon><div class="grow"><div class="title">{{ store.selected.name }}</div><div class="sub">小区配套设施</div></div></div>
      <p class="sub">{{ FACILITY_TEXT[store.selected.id] || '小区公共配套。' }}</p>
    </template>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { ElMessage } from 'element-plus'
import SensingChart from '@app/components/SensingChart.vue'
import api from '@app/api/index.js'
import { useTwinStore } from '../stores/twin'
import { TYPE_META, SEVERITY_META, ORIGIN_LABEL, STATUS_LABEL, PRIORITY_LABEL, CONTROL_LABEL, isolationPoints } from '../data/events'
import { resolveCode, houseById, buildingData } from '../data/resolver'
import { ROOM_NAMES } from '../data/layouts'
import { SENSOR_NAME } from '../engine/buildUnit'

const store = useTwinStore()
const role = computed(() => store.role)
const level = computed(() => store.level)
const isLive = computed(() => store.isLiveBuilding)
const ev = computed(() => store.activeEvent)
const ownerScope = computed(() => store.scopeKind === 'owner')
const neighbor = computed(() => store.isNeighborEvent(ev.value))

const AUD = { RESIDENT: { label: '住户', tag: 'primary' }, NEIGHBOR: { label: '相关住户', tag: 'warning' }, PROPERTY: { label: '物业', tag: 'info' }, FAMILY: { label: '家属', tag: 'success' } }
const ZONE = { LOW: '低区（市政直供）', MID: '中区（变频泵）', HIGH: '高区（变频泵）' }
const FACILITY_TEXT = {
  pump: '中区、高区二次供水变频泵与分区总水表。楼栋公共管网漏损、泵效率分析的数据来源。',
  power: '小区公区用电（照明、电梯、水泵）配电房。',
  charging: '电动车集中充电棚：引导电动车集中充电，减少入户充电的消防隐患。',
  service: '物业服务中心：工单审核、派单、SLA 管理。',
}

const typeMeta = computed(() => TYPE_META[ev.value?.type] || { label: ev.value?.type })
const sevMeta = computed(() => SEVERITY_META[ev.value?.severity] || SEVERITY_META.LOW)
// 业主视角只保留本户内的定位候选与控制动作（store.activeTargets 已按本户裁剪）
const cands = computed(() => {
  const list = ev.value?.event.location_candidates || []
  if (!ownerScope.value) return list
  const t = store.activeTargets
  const own = new Set([t?.primary, ...(t?.secondary || [])].filter(Boolean))
  return list.filter(c => own.has(c.segment_code))
})
const controls = computed(() => {
  const list = ev.value?.event.control_actions_taken || []
  if (!ownerScope.value) return list
  const own = new Set(store.activeTargets?.controls || [])
  return list.filter(c => own.has(c.target))
})
const scopeText = computed(() => {
  const e = ev.value?.event
  if (!e) return ''
  if (neighbor.value) return '关联问题 · 可能影响您家'
  if (e.scope === 'BATCH') return `1栋 ${e.batch_id} 批次`
  if (e.scope === 'STACK') return `1栋 ${e.archive_context?.stack_id || ''} 立管`
  if (e.scope === 'BUILDING' || !e.house_id) return `1栋 公共部位 · ${(e.related_houses || []).length} 户受影响`
  return `1栋 ${e.house_id}室`
})
const notices = computed(() => {
  const list = ev.value?.notices?.length ? ev.value.notices.map(n => ({ ...n, house_ids: [n.house_id] })) : (ev.value?.decision?.notices || [])
  let out = list
  if (ownerScope.value) out = list.filter(n => ['RESIDENT', 'NEIGHBOR'].includes(n.audience) && (n.house_ids || []).includes(store.ownerHouse))
  else if (role.value === 'repairer') out = list.filter(n => n.audience === 'PROPERTY')
  // 楼栋级事件会给几十户发同一条提醒，按「对象 + 标题 + 正文」合并，房号汇总显示
  const merged = new Map()
  for (const n of out) {
    const key = `${n.audience}|${n.title}|${n.content}`
    if (merged.has(key)) merged.get(key).house_ids.push(...(n.house_ids || []))
    else merged.set(key, { ...n, house_ids: [...(n.house_ids || [])] })
  }
  return [...merged.values()]
})
const orders = computed(() => ev.value?.decision?.workorders || [])
// 联机事件直接使用后端的图表结构；演示样例按后端 _blockage_chart 的同一格式由逐日诊断数据生成
const chart = computed(() => {
  const e = ev.value
  if (!e) return null
  if (e.chart) return e.chart
  const daily = e.trend?.daily || []
  if (!daily.length) return null
  return {
    title: '淋浴出水能力（相对入住初期）', unit: '', x: daily.map(p => p.date), x_label: '日期',
    series: [{ key: 'change', label: '出水能力变化', values: daily.map(p => p.change_ratio) }],
    flags: daily.map(p => !!p.flagged), thresholds: [{ value: e.trend.threshold ?? -0.3, label: '报警线' }],
    marker: { x: (e.detectedAt || '').slice(0, 10), label: '检测日' }, value_format: 'percent',
  }
})

const fmtTime = (t) => (t ? t.replace('T', ' ').slice(0, 16) : '')

async function repair(n) {
  if (ev.value.origin === 'LIVE' && n.id) {
    try { await api.repairFromNotice(n.id); ElMessage.success('已提交报修，物业审核后派单') } catch (e) { ElMessage.error(e?.response?.data?.detail?.message || '报修失败') }
  } else {
    ev.value.status = 'REPAIR_REQUESTED'
    ElMessage.success('演示模式：已模拟一键报修，工单进入物业待审核')
  }
}
async function createOrder() {
  if (ev.value.origin === 'LIVE') {
    try { await api.createSensingWorkOrder(ev.value.id); ev.value.status = 'ORDER_CREATED'; ElMessage.success('已建单') } catch (e) { ElMessage.error(e?.response?.data?.detail?.message || '建单失败') }
  } else {
    ev.value.status = 'WORKORDER_CREATED'
    ElMessage.success('演示模式：已模拟建单，进入物业审核与派单流程')
  }
}
async function recheck() {
  try { const r = await api.recheckSensingEvent(ev.value.id); ElMessage.info(r.data.still_abnormal ? '仍未恢复，已自动建单' : (r.data.reason || '已恢复，事件解除')) } catch (e) { ElMessage.error('复查失败') }
}

// ---------------- 档案卡 ----------------
const card = computed(() => {
  const sel = store.selected
  if (!sel) return null
  if (sel.kind === 'room') return { icon: 'Grid', code: `${sel.houseId}-${sel.room}`, name: `${sel.houseId}室 ${ROOM_NAMES[sel.room]}`, rows: roomRows(sel) }
  if (sel.kind !== 'code') return null
  const r = resolveCode(sel.code, store.level.buildingNo || 1)
  if (!r) return { icon: 'InfoFilled', code: sel.code, name: sel.name || sel.code, rows: [] }
  if (r.kind === 'stack') return { icon: 'Operation', code: r.code, name: r.name, rows: [['类型', '公共排水立管（PVC-110）'], ['位置', `${r.slot} 户位卫生间管井`], ['属于', '公共部位，由物业维护']] }
  const h = houseById(r.houseId)
  const rows = [['所在', `${store.level.buildingNo || 1}栋 ${r.houseId}室 ${ROOM_NAMES[r.room] || ''}`]]
  let archiveText = null
  const device = h.devices.find(d => d.device_code === r.code) || h.devices.find(d => d.segment_code === r.code || d.circuit_code === r.code)
  if (r.kind === 'supply' || r.kind === 'drain') {
    const seg = (r.kind === 'supply' ? h.supply : h.drain).find(s => s.segment_code === r.code)
    rows.push(['类别', r.kind === 'supply' ? `给水 · ${{ COLD: '冷水', HOT: '热水', MIXED: '混水' }[seg?.side] || ''}` : '排水'])
    rows.push(['构件类型', seg?.kind || '-'])
    if (seg?.parents?.length) rows.push(['上游', seg.parents.join('、')])
    if (seg?.downstream) rows.push(['下游', seg.downstream])
    const sensors = h.sensors.filter(s => s.target === r.code)
    if (sensors.length) rows.push(['监测传感器', sensors.map(s => `${SENSOR_NAME[s.type] || s.type} ${s.sensor_code}`).join('；')])
    const area = { K: '厨房', B: '卫生间' }[seg?.area]
    if (area && h.pipeline_layout?.[area]) archiveText = Object.entries(h.pipeline_layout[area]).map(([k, v]) => `${area}${k}：${v}`).join('；')
  } else if (r.kind === 'circuit' || r.kind === 'terminal' || r.kind === 'panel') {
    const c = h.circuits.find(x => x.circuit_code === r.code.replace(/-(OUT|IN)$/, ''))
    if (c) { rows.push(['额定电流', `${c.rating_a} A`]); rows.push(['漏电保护', c.rcd_trip_ma ? `${c.rcd_trip_ma} mA` : '无']); rows.push(['覆盖房间', c.rooms.map(x => ROOM_NAMES[x]).join('、')]); rows.push(['监测', '回路电流、剩余电流、端子温度']) }
  } else if (r.kind === 'sensor') {
    const s = h.sensors.find(x => x.sensor_code === r.code)
    rows.push(['传感器类型', SENSOR_NAME[s?.type] || s?.type]); if (s?.target) rows.push(['监测对象', s.target])
  }
  if (device) {
    rows.push(['设备档案', `${device.name}（${device.device_code}）`])
    if (device.spec) rows.push(['型号规格', device.spec])
    rows.push(['厂家', device.manufacturer || '-'])
    rows.push(['安装日期', device.install_date || '-'])
    rows.push(['档案来源', device.in_archive ? '一房一码正式档案' : '模拟扩展（档案中暂无）'])
    const lot = lotFor(h, device)
    if (lot) rows.push(['配件批号', `${lot.component} · ${lot.supplier} · ${lot.lot}`])
  }
  const iconMap = { supply: 'Drizzling', drain: 'Bottom', circuit: 'Lightning', terminal: 'Lightning', panel: 'Box', sensor: 'Aim', device: 'Setting' }
  return { icon: iconMap[r.kind] || 'Setting', code: r.code, name: r.name, rows, archiveText, house: h, resolved: r }
})

function roomRows(sel) {
  const h = houseById(sel.houseId)
  if (!h) return []
  const circuits = h.circuits.filter(c => c.rooms.includes(sel.room)).map(c => c.name)
  const sensors = h.sensors.filter(s => s.room === sel.room).map(s => SENSOR_NAME[s.type] || s.type)
  return [['户型', `${h.layout} ${h.area_m2}㎡`], ['供电回路', circuits.join('、') || '-'], ['房间传感器', sensors.join('、') || '-']]
}

function lotFor(h, device) {
  const b = buildingData()?.batches.find(x => x.batch_id === h.batch_id)
  const key = { B_TOILET: '马桶进水阀', K_ANGLE_VALVE: '角阀', K_HOSE: '连接软管', B_FLOOR_DRAIN: '地漏', K_SOCKET_1: '插座', K_SOCKET_2: '插座', B_SOCKET: '插座' }[device.role]
  return key ? b?.component_lots.find(l => l.component === key) : null
}

const isolation = computed(() => (card.value?.house ? isolationPoints(card.value.house, card.value.code) : []))
const relatedEvents = computed(() => {
  const code = card.value?.code
  if (!code || !isLive.value) return []
  return store.visibleEvents.filter(e => { const t = store.targetsOf(e); return t.primary === code || t.secondary.includes(code) || t.sensors.includes(code) })
})
const houseCard = computed(() => (store.level.level === 'house' ? houseById(store.level.houseId) : null))
</script>

<style scoped>
.detail { padding: 12px 14px; font-size: 13px; }
.head { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.grow { flex: 1; min-width: 0; }
.title { font-weight: 700; font-size: 15px; display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.sev-dot.big { width: 14px; height: 14px; animation: blink 1s infinite; }
.origin { margin: 4px 0 8px; padding: 4px 8px; }
.summary { font-weight: 600; margin: 6px 0 4px; }
.evidence { line-height: 1.6; margin: 0 0 6px; }
h4 { margin: 12px 0 6px; font-size: 13px; }
.cand, .ctrl { display: flex; align-items: center; gap: 8px; padding: 5px 6px; border-radius: 6px; cursor: pointer; }
.cand:hover, .ctrl:hover { background: rgba(22, 119, 255, 0.08); }
.rank { width: 18px; height: 18px; border-radius: 50%; background: #d9d9d9; color: #fff; font-size: 11px; display: grid; place-items: center; flex: none; }
.rank.first { background: #f5222d; }
.code { margin-left: 6px; font-family: Consolas, monospace; font-size: 11px; }
.notice, .order { margin-bottom: 8px; --el-card-padding: 10px; }
.notice p { margin: 6px 0; line-height: 1.6; }
.notice ol, .safety ul { margin: 4px 0; padding-left: 18px; }
.notice-top { display: flex; gap: 6px; align-items: center; margin-bottom: 6px; }
.safety { margin-top: 8px; background: rgba(250, 140, 22, 0.1); border-left: 3px solid #fa8c16; padding: 6px 8px; border-radius: 4px; }
.safety-title { color: #d46b08; font-weight: 700; display: flex; align-items: center; gap: 4px; }
.actions { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; margin-top: 10px; }
.note { margin-top: 10px; }
</style>
