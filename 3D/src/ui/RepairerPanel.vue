<template>
  <div class="role-panel">
    <h3>我的维修任务</h3>
    <div class="row">
      <span class="sub">维修人员</span>
      <el-segmented v-if="!store.roleLocked" v-model="name" :options="['王工', '李工', '张工']" size="small" />
      <b v-else>{{ store.repairerName }}</b>
    </div>
    <div v-if="!orders.length" class="sub empty">暂无派给你的任务</div>
    <div v-else-if="unassigned" class="sub">联机工单尚未派单，下面显示的是待派单的主动感知工单</div>
    <div v-for="o in orders" :key="o.order_no" class="task" :class="{ active: o.order_no === store.activeOrderNo }" @click="open(o)">
      <div class="task-top">
        <el-tag size="small" :type="o.priority === 'URGENT' ? 'danger' : o.priority === 'HIGH' ? 'warning' : 'info'" effect="dark">{{ PRIORITY_LABEL[o.priority] || '中' }}</el-tag>
        <strong class="grow">{{ o.location }}</strong>
        <el-tag size="small" effect="plain">{{ STATUS[o.status] || o.status }}</el-tag>
      </div>
      <div class="sub">{{ o.order_no }} · 1栋 {{ o.house_id }} · {{ o.trade }}{{ o.repairer ? ` · ${o.repairer}` : '' }}</div>
    </div>

    <template v-if="active">
      <div class="section-title">任务详情</div>
      <div class="safety">
        <div class="safety-title"><el-icon><WarningFilled /></el-icon> 作业安全提示（出发前确认）</div>
        <ul><li v-for="s in active.safety" :key="s">{{ s }}</li></ul>
      </div>
      <div class="section-title">作业前隔离点</div>
      <div v-for="p in isolation" :key="p.name" class="iso" @click="p.code && store.selectCode(p.code)">
        <el-icon color="#fa8c16"><Lock /></el-icon><span class="grow">{{ p.action }}{{ p.name }}</span><span class="sub code">{{ p.code }}</span>
      </div>
      <div class="section-title">建议携带</div>
      <div class="mats"><el-tag v-for="m in active.materials" :key="m" size="small" effect="plain">{{ m }}</el-tag></div>
      <div class="actions">
        <el-button type="primary" size="small" icon="Guide" @click="store.navigateToOrder(active)">导航到现场</el-button>
        <el-button size="small" icon="Aim" @click="locate">定位故障部位</el-button>
        <el-button v-if="active.status === 'ASSIGNED'" size="small" type="warning" @click="start">开始维修</el-button>
        <el-button v-if="active.status === 'PROCESSING'" size="small" type="success" @click="complete">完成维修</el-button>
      </div>
      <p class="sub">导航路线：小区大门 → 1栋北侧大堂 → 电梯 → {{ floorOf(active.house_id) }} 层 → {{ active.house_id }} 户门 → 故障部位</p>
    </template>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { ElMessage } from 'element-plus'
import { useTwinStore } from '../stores/twin'
import { PRIORITY_LABEL, eventTargets, isolationPoints } from '../data/events'
import { houseById } from '../data/resolver'

const store = useTwinStore()
const STATUS = { ASSIGNED: '已派单', PROCESSING: '维修中', COMPLETED: '已完成', PENDING_REVIEW: '待审核', PENDING_ASSIGN: '待派单' }
const name = computed({ get: () => store.repairerName, set: (v) => { store.repairerName = v; store.activeOrderNo = null } })
const orders = computed(() => store.myOrders)
const unassigned = computed(() => orders.value.length && orders.value.every(o => !o.repairer))
const active = computed(() => orders.value.find(o => o.order_no === store.activeOrderNo) || null)
const floorOf = (h) => String(h).slice(0, -2)
const isolation = computed(() => {
  const o = active.value
  if (!o) return []
  const ev = store.events.find(e => e.id === o.event_id)
  const t = ev ? eventTargets(ev) : null
  return t?.primary ? isolationPoints(houseById(t.houseId || o.house_id), t.primary) : []
})
const open = (o) => store.openOrder(o)
const locate = () => { const o = active.value; if (o) store.locateEvent(o.event_id) }
const start = () => { active.value.status = 'PROCESSING'; ElMessage.success(store.mode === 'demo' ? '演示模式：已开始维修' : '已开始维修') }
const complete = () => {
  active.value.status = 'COMPLETED'
  const ev = store.events.find(e => e.id === active.value.event_id)
  if (ev) ev.status = 'RESOLVED'
  store.refreshMarkers()
  store.clearEvent()
  ElMessage.success('维修完成：结果已回写一房一码档案，事件关闭（演示）')
}
</script>

<style scoped>
.role-panel { display: flex; flex-direction: column; gap: 8px; }
.row { display: flex; gap: 8px; align-items: center; }
.task { padding: 8px; border-radius: 8px; border: 1px solid var(--panel-border); cursor: pointer; }
.task.active { border-color: var(--accent); background: rgba(22, 119, 255, 0.1); }
.task-top { display: flex; gap: 6px; align-items: center; font-size: 13px; margin-bottom: 2px; }
.grow { flex: 1; min-width: 0; }
.section-title { font-weight: 700; font-size: 13px; margin-top: 4px; }
.safety { background: rgba(250, 140, 22, 0.1); border-left: 3px solid #fa8c16; padding: 6px 8px; border-radius: 4px; font-size: 12.5px; }
.safety-title { color: #d46b08; font-weight: 700; display: flex; align-items: center; gap: 4px; }
.safety ul { margin: 4px 0; padding-left: 18px; }
.iso { display: flex; gap: 6px; align-items: center; font-size: 13px; padding: 4px 6px; border-radius: 6px; cursor: pointer; }
.iso:hover { background: rgba(22, 119, 255, 0.08); }
.code { font-family: Consolas, monospace; font-size: 11px; }
.mats { display: flex; flex-wrap: wrap; gap: 4px; }
.actions { display: flex; flex-wrap: wrap; gap: 4px; }
.actions .el-button { margin: 0; }
.empty { padding: 10px; text-align: center; }
</style>
