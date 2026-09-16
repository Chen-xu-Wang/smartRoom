<template>
  <div class="events">
    <div v-if="!events.length" class="sub empty">暂无待处理问题</div>
    <div v-for="e in events" :key="e.id" class="ev" :class="{ active: e.id === store.activeEventId }" @click="store.locateEvent(e.id)">
      <span class="sev-dot" :style="{ background: SEVERITY_META[e.severity].color }" :class="{ blink: e.severity === 'CRITICAL' }"></span>
      <div class="grow">
        <div class="row1">
          <strong>{{ TYPE_META[e.type]?.label || e.type }}</strong>
          <span class="where">{{ where(e) }}</span>
        </div>
        <div class="sub ellipsis">{{ e.title }}</div>
        <div class="row3">
          <el-tag size="small" :type="SEVERITY_META[e.severity].tag" effect="plain">{{ SEVERITY_META[e.severity].label }}</el-tag>
          <el-tag size="small" type="info" effect="plain">{{ STATUS_LABEL[e.status] || e.status }}</el-tag>
          <el-tag v-if="e.origin === 'DEMO_SCRIPT'" size="small" type="info">样例</el-tag>
          <el-tag v-else-if="e.origin === 'DETECTION_SAMPLE'" size="small" type="success">检测</el-tag>
        </div>
      </div>
      <el-button class="loc" size="small" circle icon="Aim" title="一键定位" @click.stop="store.locateEvent(e.id)" />
    </div>
  </div>
</template>

<script setup>
import { useTwinStore } from '../stores/twin'
import { TYPE_META, SEVERITY_META, STATUS_LABEL } from '../data/events'

defineProps({ events: { type: Array, default: () => [] } })
const store = useTwinStore()
const where = (e) => {
  if (e.scope === 'BATCH') return `${e.event.batch_id} 批次`
  if (e.scope === 'STACK') return `${e.event.archive_context?.stack_id || ''} 立管`
  if (e.scope === 'BUILDING' || !e.houseId) return `1栋 公共（${(e.event.related_houses || []).length} 户受影响）`
  return `1栋 ${e.houseId}`
}
</script>

<style scoped>
.events { display: flex; flex-direction: column; gap: 6px; }
.ev { display: flex; gap: 8px; align-items: flex-start; padding: 8px; border-radius: 8px; border: 1px solid var(--panel-border); cursor: pointer; transition: background 0.15s; }
.ev:hover { background: rgba(22, 119, 255, 0.06); }
.ev.active { border-color: var(--accent); background: rgba(22, 119, 255, 0.1); }
.sev-dot { margin-top: 6px; }
.blink { animation: blink 0.9s infinite; }
.grow { flex: 1; min-width: 0; }
.row1 { display: flex; justify-content: space-between; gap: 6px; font-size: 13px; }
.where { font-size: 12px; color: var(--accent); white-space: nowrap; }
.ellipsis { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin: 2px 0 4px; }
.row3 { display: flex; gap: 4px; flex-wrap: wrap; }
.loc { flex: none; }
.empty { padding: 12px; text-align: center; }
</style>
