<template>
  <div class="chart-root">
    <div class="chart-head">
      <span class="chart-title">{{ chart.title }}<template v-if="chart.unit">（{{ chart.unit }}）</template></span>
      <span class="chart-note">
        <template v-if="series.length > 1">
          <span v-for="s in series" :key="s.key" class="legend-item"><i :style="{ background: s.color }"></i>{{ s.label }}</span>
        </template>
        <span v-if="hasFlags" class="legend-item"><b class="flag-key">●</b> 异常</span>
      </span>
    </div>
    <div class="chart-plot" @mouseleave="hover = null">
      <svg :viewBox="`0 0 ${W} ${H}`" preserveAspectRatio="none" class="chart-svg" role="img" :aria-label="chart.title">
        <line v-for="t in yTicks" :key="`g${t}`" :x1="PL" :x2="W - PR" :y1="y(t)" :y2="y(t)" class="grid" />
        <line v-for="th in chart.thresholds" :key="`t${th.value}`" :x1="PL" :x2="W - PR" :y1="y(th.value)" :y2="y(th.value)" class="threshold" />
        <line v-if="markerX !== null" :x1="markerX" :x2="markerX" :y1="PT" :y2="H - PB" class="marker" />
        <path v-for="s in series" :key="`p${s.key}`" :d="s.path" class="series" :style="{ stroke: s.color }" />
        <template v-for="s in series" :key="`d${s.key}`">
          <circle v-for="p in s.points" :key="`${s.key}-${p.i}`" :cx="p.x" :cy="p.y" :r="p.flagged ? 4 : 2.2"
                  :class="p.flagged ? 'dot-flag' : 'dot'" :style="p.flagged ? null : { fill: s.color }" />
        </template>
        <rect v-for="i in chart.x.length" :key="`h${i}`" :x="xOf(i - 1) - step / 2" :y="PT" :width="step" :height="H - PT - PB"
              class="hit" @mouseenter="hover = i - 1" />
        <line v-if="hover !== null" :x1="xOf(hover)" :x2="xOf(hover)" :y1="PT" :y2="H - PB" class="crosshair" />
      </svg>
      <div class="y-labels">
        <span v-for="t in yTicks" :key="`l${t}`" :style="{ top: `${(y(t) / H) * 100}%` }">{{ fmt(t) }}</span>
      </div>
      <div v-for="th in chart.thresholds" :key="`tl${th.value}`" class="threshold-label" :style="{ top: `${(y(th.value) / H) * 100}%` }">
        {{ th.label }}
      </div>
      <div v-if="showEndLabels" class="end-labels">
        <span v-for="s in series" :key="`e${s.key}`" :style="{ top: `${(endLabelY[s.key] / H) * 100}%` }">{{ s.label }}</span>
      </div>
      <div v-if="hover !== null" class="tooltip" :style="tooltipStyle">
        <div class="tt-x">{{ chart.x[hover] }}</div>
        <div v-for="s in series" :key="`tt${s.key}`">
          <i class="tt-swatch" :style="{ background: s.color }"></i>{{ s.label }} <b>{{ s.values[hover] == null ? '—' : fmt(s.values[hover]) }}</b>
        </div>
        <div v-if="chart.flags[hover]" class="tt-flag">异常</div>
      </div>
    </div>
    <div class="x-labels">
      <span>{{ short(chart.x[0]) }}</span>
      <span v-if="chart.marker">{{ chart.marker.label }} {{ short(chart.marker.x) }}</span>
      <span>{{ short(chart.x[chart.x.length - 1]) }}</span>
    </div>
    <el-collapse class="chart-table">
      <el-collapse-item title="查看数据表" name="t">
        <el-table :data="rows" size="small" max-height="220">
          <el-table-column prop="x" :label="chart.x_label || '日期'" width="110" />
          <el-table-column v-for="s in series" :key="`c${s.key}`" :label="s.label">
            <template #default="{ row }">{{ row[s.key] == null ? '—' : fmt(row[s.key]) }}</template>
          </el-table-column>
          <el-table-column label="异常" width="70">
            <template #default="{ row }">{{ row.flag ? '是' : '' }}</template>
          </el-table-column>
        </el-table>
      </el-collapse-item>
    </el-collapse>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  // 后端 sensing_service._chart 的结构：{title, unit, x, x_label, series:[{key,label,values}], flags, thresholds, marker, value_format}
  chart: { type: Object, required: true },
})

const W = 600, H = 180, PL = 46, PR = 64, PT = 12, PB = 10
// 分类色槽 1、2（dataviz 参考配色，相邻两色已通过色觉差异校验）
const COLORS = ['#2a78d6', '#eb6834']
const hover = ref(null)

const allValues = computed(() => [
  ...props.chart.series.flatMap(s => s.values.filter(v => v != null)),
  ...props.chart.thresholds.map(t => t.value),
])
const pad = computed(() => {
  const vals = allValues.value
  const span = Math.max(...vals) - Math.min(...vals)
  return span > 0 ? span * 0.08 : 1
})
const yMin = computed(() => Math.min(...allValues.value) - pad.value)
const yMax = computed(() => Math.max(...allValues.value) + pad.value)
const y = v => PT + (yMax.value - v) / (yMax.value - yMin.value || 1) * (H - PT - PB)
const step = computed(() => (W - PL - PR) / Math.max(props.chart.x.length - 1, 1))
const xOf = i => PL + i * step.value

const yTicks = computed(() => {
  const span = yMax.value - yMin.value
  const raw = span / 4
  const mag = 10 ** Math.floor(Math.log10(raw || 1))
  const unit = [1, 2, 2.5, 5, 10].map(m => m * mag).find(u => u >= raw) || mag
  const ticks = []
  for (let t = Math.ceil(yMin.value / unit) * unit; t <= yMax.value; t += unit) ticks.push(Math.round(t / unit) * unit)
  return ticks
})

const series = computed(() => props.chart.series.map((s, k) => {
  const points = s.values.map((v, i) => ({ v, i })).filter(p => p.v != null)
    // 序列自带 flags 时只标该序列越限的点；否则整张图的异常日标在第一条序列上
    .map(p => ({ i: p.i, x: xOf(p.i), y: y(p.v), flagged: s.flags ? !!s.flags[p.i] : k === 0 && !!props.chart.flags[p.i] }))
  return {
    ...s, color: COLORS[k % COLORS.length], points,
    path: points.map((p, j) => `${j ? 'L' : 'M'}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' '),
    endY: points.length ? points[points.length - 1].y : 0,
  }
}))
// 序列提前结束（如爆管关阀后不再绘制）时末端标签会脱离线条，只保留图例
const showEndLabels = computed(() => series.value.length > 1
  && series.value.every(s => s.points.length && s.points[s.points.length - 1].i === props.chart.x.length - 1))
// 末端标签按纵坐标排序后保持最小间距，避免数值接近的两条线标签重叠
const endLabelY = computed(() => {
  const GAP = 14
  const sorted = series.value.map(s => ({ key: s.key, y: s.endY })).sort((a, b) => a.y - b.y)
  sorted.forEach((s, j) => { if (j && s.y - sorted[j - 1].y < GAP) s.y = sorted[j - 1].y + GAP })
  const overflow = sorted.length ? sorted[sorted.length - 1].y - (H - PB) : 0
  return Object.fromEntries(sorted.map(s => [s.key, overflow > 0 ? s.y - overflow : s.y]))
})
const hasFlags = computed(() => props.chart.flags.some(Boolean))
const markerX = computed(() => {
  const i = props.chart.marker ? props.chart.x.indexOf(props.chart.marker.x) : -1
  return i >= 0 ? xOf(i) : null
})
const rows = computed(() => props.chart.x.map((x, i) => ({
  x, flag: props.chart.flags[i], ...Object.fromEntries(props.chart.series.map(s => [s.key, s.values[i]])),
})))
const tooltipStyle = computed(() => {
  const leftPct = (xOf(hover.value) / W) * 100
  return leftPct > 60 ? { right: `${100 - leftPct + 2}%` } : { left: `${leftPct + 2}%` }
})

const fmt = v => {
  if (props.chart.value_format === 'percent') return `${v > 0 ? '+' : ''}${Math.round(v * 100)}%`
  const abs = Math.abs(v)
  return abs >= 100 ? v.toFixed(0) : abs >= 10 ? v.toFixed(1) : v.toFixed(2).replace(/\.?0+$/, '') || '0'
}
const short = x => (x && /^\d{4}-\d{2}-\d{2}$/.test(x) ? x.slice(5) : x || '')
</script>

<style scoped>
.chart-root {
  --surface-1: #fcfcfb;
  --text-primary: #0b0b0b;
  --text-secondary: #52514e;
  --text-muted: #8a8984;
  --grid: #e6e5e0;
  --status-critical: #d03b3b;
  color: var(--text-primary);
}
.chart-head { display: flex; justify-content: space-between; gap: 12px; flex-wrap: wrap; margin-bottom: 6px; }
.chart-title { font-size: 13px; font-weight: 600; }
.chart-note { display: flex; gap: 10px; font-size: 12px; color: var(--text-secondary); }
.legend-item { display: inline-flex; align-items: center; gap: 4px; }
.legend-item i { display: inline-block; width: 12px; height: 3px; border-radius: 2px; }
.flag-key { color: var(--status-critical); font-weight: 400; }
.chart-plot { position: relative; height: 180px; background: var(--surface-1); border-radius: 8px; }
.chart-svg { width: 100%; height: 100%; display: block; }
.grid { stroke: var(--grid); stroke-width: 1; vector-effect: non-scaling-stroke; }
.threshold { stroke: var(--text-secondary); stroke-width: 1.5; stroke-dasharray: 5 4; vector-effect: non-scaling-stroke; }
.marker { stroke: var(--text-muted); stroke-width: 1; vector-effect: non-scaling-stroke; }
.series { fill: none; stroke-width: 2; stroke-linejoin: round; stroke-linecap: round; vector-effect: non-scaling-stroke; }
.dot { stroke: var(--surface-1); stroke-width: 1.5; vector-effect: non-scaling-stroke; }
.dot-flag { fill: var(--status-critical); stroke: var(--surface-1); stroke-width: 2; vector-effect: non-scaling-stroke; }
.hit { fill: transparent; cursor: crosshair; }
.crosshair { stroke: var(--text-muted); stroke-width: 1; vector-effect: non-scaling-stroke; }
.y-labels span { position: absolute; left: 4px; transform: translateY(-50%); font-size: 10px; color: var(--text-muted); }
.threshold-label { position: absolute; left: 52px; transform: translateY(-115%); font-size: 11px; color: var(--text-secondary); white-space: nowrap; }
.end-labels span { position: absolute; right: 4px; transform: translateY(-50%); font-size: 11px; color: var(--text-secondary); }
.x-labels { display: flex; justify-content: space-between; font-size: 11px; color: var(--text-muted); padding: 4px 64px 0 46px; }
.tooltip {
  position: absolute; top: 8px; pointer-events: none; background: #fff; border: 1px solid var(--grid);
  border-radius: 8px; padding: 6px 10px; font-size: 12px; line-height: 1.6; box-shadow: 0 4px 14px rgba(0,0,0,.08);
  color: var(--text-primary); white-space: nowrap; z-index: 2;
}
.tt-x { font-weight: 600; }
.tt-swatch { display: inline-block; width: 8px; height: 8px; border-radius: 2px; margin-right: 4px; }
.tt-flag { font-weight: 600; }
.tt-flag::before { content: '● '; color: var(--status-critical); }
.chart-table { margin-top: 6px; border: none; }
.chart-table :deep(.el-collapse-item__header) { height: 32px; font-size: 12px; color: var(--text-secondary); border: none; }
.chart-table :deep(.el-collapse-item__wrap) { border: none; }
</style>
