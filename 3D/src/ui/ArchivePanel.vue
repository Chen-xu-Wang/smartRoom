<template>
  <div class="role-panel">
    <h3>一房一码 · 建筑档案透视</h3>
    <div class="section-title">图层</div>
    <div class="layers">
      <el-switch :model-value="store.xray" size="small" active-text="结构透视（X 光）" @change="store.setXray" />
      <el-switch v-for="l in LAYERS" :key="l.key" :model-value="store.layers[l.key]" size="small" :active-text="l.label" @change="v => store.setLayer(l.key, v)" />
    </div>
    <div class="section-title">楼层着色</div>
    <el-radio-group :model-value="store.colorMode" size="small" @change="store.setColorMode">
      <el-radio-button value="none">无</el-radio-button>
      <el-radio-button value="batch">MiC 批次</el-radio-button>
      <el-radio-button value="zone">供水分区</el-radio-button>
    </el-radio-group>
    <div v-if="store.colorMode === 'batch'" class="legend-rows">
      <div v-for="b in batches" :key="b.batch_id" class="legend-row">
        <i :style="{ background: BATCH_COLOR[b.batch_id] }"></i>
        <b>{{ b.batch_id }} 批</b><span class="sub">{{ b.floors[0] }}–{{ b.floors[1] }} 层 · 生产 {{ b.production_date }} · 交付 {{ b.delivery_date }}</span>
      </div>
      <el-collapse>
        <el-collapse-item title="配件批号（质量追溯）">
          <el-table :data="lotRows" size="small" max-height="220">
            <el-table-column prop="component" label="配件" width="84" />
            <el-table-column prop="A" label="A 批" />
            <el-table-column prop="B" label="B 批" />
            <el-table-column prop="C" label="C 批" />
          </el-table>
        </el-collapse-item>
      </el-collapse>
    </div>
    <div v-if="store.colorMode === 'zone'" class="legend-rows">
      <div v-for="z in zones" :key="z.zone_id" class="legend-row">
        <i :style="{ background: ZONE_COLOR[z.zone_id] }"></i>
        <b>{{ ZONE_NAME[z.zone_id] }}</b><span class="sub">{{ z.floors[0] }}–{{ z.floors[1] }} 层 · {{ z.source === 'MUNICIPAL' ? '市政直供' : '变频泵' }} {{ z.source_pressure_mpa }} MPa</span>
      </div>
    </div>
    <div class="section-title">快速进入</div>
    <div class="row">
      <el-input-number v-model="floor" :min="1" :max="18" size="small" style="width: 110px" />
      <el-button size="small" @click="goFloor">进入楼层</el-button>
      <el-select v-model="houseId" size="small" filterable placeholder="户号" style="width: 100px" @change="goHouse">
        <el-option v-for="h in houses" :key="h" :label="h" :value="h" />
      </el-select>
    </div>
    <div class="section-title">本栋档案统计</div>
    <div class="kv">
      <span>住户</span><span>108 户（正式档案 3 户 + 模拟扩展 105 户）</span>
      <span>户型</span><span>T89 × 36 · T75 × 36 · T65 × 36</span>
      <span>给水管段</span><span>{{ stat.supply }} 段</span>
      <span>排水管段</span><span>{{ stat.drain }} 段 + 立管 6 根 × 18 段</span>
      <span>电气回路</span><span>{{ stat.circuits }} 路</span>
      <span>传感器</span><span>{{ stat.sensors }} 个（方案 3 布点）</span>
      <span>设备档案</span><span>{{ stat.devices }} 件</span>
    </div>
    <p class="sub">点击任意构件查看档案卡：型号、厂家、安装日期、配件批号、档案原文与监测传感器。</p>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useTwinStore, getEngine } from '../stores/twin'
import { buildingData } from '../data/resolver'

const store = useTwinStore()
const LAYERS = [
  { key: 'supply', label: '给水（冷/热）' }, { key: 'drain', label: '排水与立管' }, { key: 'circuit', label: '电气回路' },
  { key: 'sensor', label: '传感器布点' }, { key: 'furn', label: '家具' }, { key: 'labels', label: '房间名' },
]
const BATCH_COLOR = { A: '#52c41a', B: '#faad14', C: '#1890ff' }
const ZONE_COLOR = { LOW: '#13c2c2', MID: '#2f54eb', HIGH: '#722ed1' }
const ZONE_NAME = { LOW: '低区', MID: '中区', HIGH: '高区' }
const batches = computed(() => buildingData()?.batches || [])
const zones = computed(() => buildingData()?.supply_zones || [])
const houses = computed(() => (buildingData()?.houses || []).map(h => h.house_id).sort((a, b) => Number(a) - Number(b)))
const lotRows = computed(() => {
  const rows = {}
  for (const b of batches.value) for (const l of b.component_lots) { rows[l.component] ||= { component: l.component }; rows[l.component][b.batch_id] = l.lot }
  return Object.values(rows)
})
const stat = computed(() => {
  const hs = buildingData()?.houses || []
  const sum = (f) => hs.reduce((a, h) => a + f(h), 0)
  return { supply: sum(h => h.supply.length), drain: sum(h => h.drain.length), circuits: sum(h => h.circuits.length), sensors: sum(h => h.sensors.length), devices: sum(h => h.devices.length) }
})
const floor = ref(13)
const houseId = ref(null)
const goFloor = () => getEngine().goFloor(store.level.buildingNo || 1, floor.value)
const goHouse = (h) => getEngine().goHouse(store.level.buildingNo || 1, h)
</script>

<style scoped>
.role-panel { display: flex; flex-direction: column; gap: 8px; }
.section-title { font-weight: 700; font-size: 13px; margin-top: 4px; }
.layers { display: grid; grid-template-columns: 1fr 1fr; gap: 4px 8px; }
.legend-rows { display: flex; flex-direction: column; gap: 4px; }
.legend-row { display: flex; gap: 6px; align-items: center; font-size: 12.5px; }
.legend-row i { width: 12px; height: 12px; border-radius: 3px; flex: none; }
.row { display: flex; gap: 6px; align-items: center; }
</style>
