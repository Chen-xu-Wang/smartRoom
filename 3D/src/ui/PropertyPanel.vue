<template>
  <div class="role-panel">
    <h3>小区运行看板</h3>
    <div class="kpis">
      <div v-for="k in kpis" :key="k.key" class="kpi" :style="{ '--c': k.color }" @click="filter = filter === k.key ? null : k.key">
        <div class="num">{{ k.value }}</div><div class="sub">{{ k.label }}</div>
      </div>
    </div>
    <div class="domains sub">
      <span v-for="d in domains" :key="d.key">{{ d.label }} <b>{{ d.value }}</b></span>
    </div>
    <div class="row">
      <el-button type="danger" size="small" icon="Aim" @click="store.locateTop()">定位最高优先级问题</el-button>
      <el-switch v-model="batchHeat" size="small" active-text="批次热力" />
    </div>
    <div class="section-title"><span>待处理问题（{{ list.length }}）</span><span v-if="filter" class="sub link" @click="filter = null">清除筛选</span></div>
    <EventList :events="list" />
    <div class="section-title"><span>工单概况（{{ store.mode === 'demo' ? '演示' : '联机' }}）</span></div>
    <div class="orders sub">
      <span v-for="s in orderStats" :key="s.label">{{ s.label }} <b>{{ s.value }}</b></span>
    </div>
    <div class="section-title"><span>楼栋</span></div>
    <div class="buildings">
      <el-button v-for="b in BUILDINGS" :key="b.no" size="small" :type="store.level.buildingNo === b.no ? 'primary' : 'default'" @click="goBuilding(b)">
        {{ b.name }}<span v-if="!b.live" class="sub">（未接入）</span>
      </el-button>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import EventList from './EventList.vue'
import { useTwinStore, getEngine } from '../stores/twin'
import { SEVERITY_META, TYPE_META } from '../data/events'
import { BUILDINGS } from '../data/site'

const store = useTwinStore()
const filter = ref(null)
const kpis = computed(() => ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'].map(k => ({ key: k, label: SEVERITY_META[k].label, color: SEVERITY_META[k].color, value: store.counts[k] || 0 })))
const list = computed(() => store.openEvents.filter(e => !filter.value || e.severity === filter.value))
const domains = computed(() => {
  const c = { WATER: 0, POWER: 0, JOINT: 0, CARE: 0 }
  for (const e of store.openEvents) c[TYPE_META[e.type]?.domain || 'WATER']++
  return [{ key: 'WATER', label: '用水', value: c.WATER }, { key: 'POWER', label: '用电', value: c.POWER }, { key: 'JOINT', label: '水电联合', value: c.JOINT }, { key: 'CARE', label: '关怀', value: c.CARE }]
})
const orderStats = computed(() => {
  const o = store.orders
  return [{ label: '工单', value: o.length }, { label: '已派单', value: o.filter(x => x.status === 'ASSIGNED').length }, { label: '维修中', value: o.filter(x => x.status === 'PROCESSING').length }, { label: '紧急', value: o.filter(x => x.priority === 'URGENT').length }]
})
const batchHeat = computed({ get: () => store.colorMode === 'batch', set: (v) => { store.setColorMode(v ? 'batch' : 'none'); if (v && !store.level.buildingNo) getEngine().goBuilding(1) } })
const goBuilding = (b) => getEngine().goBuilding(b.no)
</script>

<style scoped>
.role-panel { display: flex; flex-direction: column; gap: 8px; }
.kpis { display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; }
.kpi { border-radius: 8px; padding: 6px 4px; text-align: center; background: color-mix(in srgb, var(--c) 12%, transparent); border: 1px solid color-mix(in srgb, var(--c) 45%, transparent); cursor: pointer; }
.kpi .num { font-size: 22px; font-weight: 800; color: var(--c); line-height: 1.1; }
.domains, .orders { display: flex; gap: 10px; flex-wrap: wrap; }
.row { display: flex; justify-content: space-between; align-items: center; }
.section-title { display: flex; justify-content: space-between; font-weight: 700; font-size: 13px; margin-top: 4px; }
.link { cursor: pointer; color: var(--accent); }
.buildings { display: flex; flex-wrap: wrap; gap: 4px; }
.buildings .el-button { margin: 0; }
</style>
