<template>
  <div class="navbar panel">
    <el-button size="small" icon="HomeFilled" @click="e().goSite()">小区全景</el-button>
    <el-button size="small" icon="Back" :disabled="lvl.level === 'site'" @click="up">返回上级</el-button>
    <div class="crumbs">
      <span class="crumb" @click="e().goSite()">筑维花园</span>
      <template v-if="lvl.buildingNo"><el-icon><ArrowRight /></el-icon><span class="crumb" @click="e().goBuilding(lvl.buildingNo)">{{ lvl.buildingNo }}栋</span></template>
      <template v-if="lvl.floor"><el-icon><ArrowRight /></el-icon><span class="crumb" @click="e().goFloor(lvl.buildingNo, lvl.floor)">{{ lvl.floor }}层</span></template>
      <template v-if="lvl.houseId"><el-icon><ArrowRight /></el-icon><span class="crumb" @click="e().goHouse(lvl.buildingNo, lvl.houseId)">{{ lvl.houseId }}室</span></template>
      <template v-if="partName"><el-icon><ArrowRight /></el-icon><span class="crumb cur">{{ partName }}</span></template>
    </div>
    <template v-if="lvl.buildingNo && store.role !== 'owner'">
      <el-button size="small" icon="ArrowDown" :disabled="(lvl.floor || 19) <= 1" @click="floorStep(-1)" title="下一层" />
      <el-button size="small" icon="ArrowUp" :disabled="lvl.floor === 18" @click="floorStep(1)" title="上一层" />
    </template>
    <el-tag v-if="lvl.buildingNo && lvl.buildingNo !== 1" size="small" type="info">结构复用 1栋 · 数据暂未接入</el-tag>
    <span class="grow"></span>
    <div class="legend">
      <span v-for="s in SEV" :key="s.k"><i :style="{ background: s.c }"></i>{{ s.l }}</span>
    </div>
    <span class="sub hint">左键旋转 · 右键平移 · 滚轮缩放 · 点击楼栋/楼层/住户逐级进入</span>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useTwinStore, getEngine } from '../stores/twin'
import { resolveCode } from '../data/resolver'
import { SEVERITY_META } from '../data/events'

const store = useTwinStore()
const e = () => getEngine()
const lvl = computed(() => store.level)
const partName = computed(() => (store.selected?.kind === 'code' && lvl.value.level === 'house' ? resolveCode(store.selected.code, lvl.value.buildingNo || 1)?.name : null))
const SEV = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'].map(k => ({ k, c: SEVERITY_META[k].color, l: SEVERITY_META[k].label }))
const up = () => {
  const l = lvl.value
  if (l.level === 'house') return store.role === 'owner' ? null : e().goFloor(l.buildingNo, l.floor)
  if (l.level === 'floor') return e().goBuilding(l.buildingNo)
  return e().goSite()
}
const floorStep = (d) => e().goFloor(lvl.value.buildingNo, (lvl.value.floor || (d > 0 ? 0 : 19)) + d)
</script>

<style scoped>
.navbar { position: absolute; left: 12px; right: 12px; bottom: 10px; height: 44px; display: flex; align-items: center; gap: 8px; padding: 0 12px; }
.navbar .el-button { margin: 0; }
.crumbs { display: flex; align-items: center; gap: 4px; font-size: 13px; margin-left: 6px; }
.crumb { cursor: pointer; color: var(--accent); }
.crumb.cur { color: var(--panel-fg); font-weight: 700; cursor: default; }
.grow { flex: 1; }
.legend { display: flex; gap: 8px; font-size: 12px; }
.legend i { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 3px; }
.hint { white-space: nowrap; }
@media (max-width: 1500px) { .hint { display: none; } }
</style>
