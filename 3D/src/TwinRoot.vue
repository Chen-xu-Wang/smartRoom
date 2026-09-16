<template>
  <!-- 3D 数字孪生主体。两种用法：
       1) 内嵌（embedded）：作为现有前端的一个页面，外面还有前端的顶部导航与页脚
       2) 独立：3D 工程自己的整页应用 -->
  <div ref="root" class="twin-root" :class="{ embedded }" :data-theme="store.theme">
    <div ref="stage" class="stage"></div>
    <div v-if="!store.ready" class="loading"><el-icon class="is-loading" size="28"><Loading /></el-icon> 正在生成小区模型…</div>

    <template v-if="store.ready">
      <TopBar :embedded="embedded" @login="showLogin = true" />

      <div class="left panel scroll">
        <PropertyPanel v-if="store.role === 'property'" />
        <OwnerPanel v-else-if="store.role === 'owner'" />
        <ArchivePanel v-else-if="store.role === 'archive'" />
        <RepairerPanel v-else-if="store.role === 'repairer'" />
      </div>

      <div class="right">
        <DetailPanel v-if="showDetail" class="detail-box" :class="{ full: !showPlan }" />
        <FloorPlan2D
          v-if="showPlan"
          class="plan-box"
          :floor="store.level.floor"
          :house-id="store.level.houseId"
          :selected-code="store.selected?.kind === 'code' ? store.selected.code : null"
          :targets="targets"
          :alert-houses="alertHouses"
          @house="goHouse"
          @room="onRoom"
          @code="c => store.selectCode(c)"
        />
      </div>

      <NavBar />

      <div v-if="store.hover && store.hover.name" class="hover" :style="{ left: store.hover.x + 14 + 'px', top: store.hover.y + 14 + 'px' }">
        {{ store.hover.name }}
      </div>
      <LoginDialog v-if="!embedded" v-model="showLogin" />
      <!-- 独立运行时的页脚；内嵌到现有前端时用前端自己的页脚 -->
      <footer v-if="!embedded" class="app-footer">筑维AI Demo | 基于中国建筑国际「一房一码」数字档案 | AI辅助，人类决策</footer>

    </template>
  </div>
</template>

<script setup>
import { computed, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import api from '@app/api/index.js'
import { Engine } from './engine/Engine'
import { loadBuilding } from './data/loader'
import { eventTargets } from './data/events'
import { useTwinStore, setEngine, getEngine } from './stores/twin'
import TopBar from './ui/TopBar.vue'
import NavBar from './ui/NavBar.vue'
import PropertyPanel from './ui/PropertyPanel.vue'
import OwnerPanel from './ui/OwnerPanel.vue'
import ArchivePanel from './ui/ArchivePanel.vue'
import RepairerPanel from './ui/RepairerPanel.vue'
import DetailPanel from './ui/DetailPanel.vue'
import FloorPlan2D from './ui/FloorPlan2D.vue'
import LoginDialog from './ui/LoginDialog.vue'

const props = defineProps({
  embedded: { type: Boolean, default: false },
  // 内嵌时由页面把路由 query 传进来（独立运行时读 location.search）
  query: { type: Object, default: null },
})

const root = ref(null)
const stage = ref(null)
const store = useTwinStore()
const showLogin = ref(false)
let engine = null

const targets = computed(() => (store.activeEvent ? eventTargets(store.activeEvent) : null))
const alertHouses = computed(() => store.openEvents.filter(e => e.houseId && Number(String(e.houseId).slice(0, -2)) === store.level.floor).map(e => e.houseId))
const showPlan = computed(() => ['floor', 'house'].includes(store.level.level))
const showDetail = computed(() => !!(store.activeEvent || store.selected || store.level.level === 'house'))

const goHouse = (h) => {
  if (store.role === 'owner' && h !== store.ownerHouse) { ElMessage.warning('隐私保护：业主视角只能进入自己的住宅'); return }
  getEngine().goHouse(store.level.buildingNo || 1, h)
}
watch(() => store.selected, (sel) => { if (engine && !(sel?.kind === 'code')) engine.setSelection(null) })
const onRoom = (room) => { store.selected = { kind: 'room', houseId: store.level.houseId, room } }

const onPointerDown = () => engine?.cancelLocate()

onMounted(async () => {
  store.setThemeRoot(props.embedded ? root.value : document.documentElement)
  store.applyTheme(store.theme, { engine: false })
  await loadBuilding()
  engine = new Engine(stage.value)
  setEngine(engine)
  engine.on('level', (l) => store.onLevel(l))
  engine.on('pick', (info) => store.onPick(info))
  engine.on('hover', (h) => store.setHover(h))
  engine.load()
  store.applyTheme(store.theme)
  // 任何新的点击都打断进行中的定位动画（"一键定位"按钮的 click 在 pointerdown 之后触发，不受影响）
  document.addEventListener('pointerdown', onPointerDown, true)
  await store.init()
  window.__twin = { engine, store }
  const search = props.query ? new URLSearchParams(props.query).toString() : location.search
  if (search && search.length > 1) await store.applyEntryParams(search, api)
})

onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', onPointerDown, true)
  document.documentElement.classList.remove('dark')
  engine?.dispose()
  engine = null
  setEngine(null)
  store.reset()
})
</script>

<style scoped>
.twin-root { position: fixed; inset: 0; }
/* 内嵌时铺满前端页面的主内容区（顶部导航 60px + 页脚约 49px） */
.twin-root.embedded { position: relative; inset: auto; width: 100%; height: calc(100vh - 110px); min-height: 560px; overflow: hidden; }
.stage { position: absolute; inset: 0; }
.loading { position: absolute; inset: 0; display: flex; gap: 10px; align-items: center; justify-content: center; font-size: 18px; color: var(--text-primary, #1f2d3d); }
.left { position: absolute; top: 76px; left: 12px; bottom: 96px; width: 340px; padding: 12px 14px; }
.right { position: absolute; top: 76px; right: 12px; bottom: 96px; width: 420px; display: flex; flex-direction: column; gap: 10px; pointer-events: none; }
.right > * { pointer-events: auto; }
.detail-box { flex: 1 1 50%; min-height: 0; }
.detail-box.full { flex: 0 1 auto; max-height: 100%; }
.plan-box { flex: 1 1 50%; min-height: 260px; }
.hover { position: fixed; pointer-events: none; background: rgba(20, 30, 45, 0.88); color: #fff; font-size: 12px; padding: 4px 8px; border-radius: 6px; z-index: 20; white-space: nowrap; }
/* 内嵌时没有 3D 自己的页脚，面板可以更贴近底部 */
.twin-root.embedded .left, .twin-root.embedded .right { bottom: 64px; }
@media (max-width: 1400px) { .left { width: 300px; } .right { width: 360px; } }
</style>
