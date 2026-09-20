<template>
  <div class="role-panel">
    <h3>我的家</h3>
    <el-empty v-if="!store.ownerHouse" :image-size="60" description="账号尚未绑定房屋，请联系物业办理绑定" />
    <div v-else class="row">
      <span class="sub">住户</span>
      <!-- 已登录：只能在名下的房子之间切换；未登录演示：可选任意住户 -->
      <el-select v-if="houses.length > 1" v-model="house" size="small" filterable style="width: 150px">
        <el-option v-for="h in houses" :key="h" :label="`1栋 ${h}室`" :value="h" />
      </el-select>
      <b v-else>1栋 {{ store.ownerHouse }}室</b>
      <el-button size="small" icon="Aim" @click="goHome">回到我家</el-button>
    </div>
    <div v-if="info" class="home-card">
      <div class="kv">
        <span>户型</span><span>{{ info.layout }} · {{ info.area_m2 }}㎡</span>
        <span>楼层</span><span>{{ info.floor }} 层 · {{ info.batch_id }} 批次 MiC 模块</span>
        <span>设备</span><span>{{ info.devices.length }} 件已建档</span>
        <span>守护</span><span>{{ info.sensors.length }} 个传感器在线</span>
      </div>
    </div>
    <div class="section-title">
      <span>健康提醒（{{ notices.length }}）</span>
    </div>
    <div v-if="!notices.length" class="ok"><el-icon color="#52c41a"><CircleCheckFilled /></el-icon> 家中水电运行正常</div>
    <el-card v-for="n in notices" :key="n.eventId + n.title" shadow="never" class="notice" @click="store.locateEvent(n.eventId)">
      <div class="notice-top">
        <span class="sev-dot" :style="{ background: SEVERITY_META[n.severity].color }"></span>
        <strong>{{ n.title }}</strong>
      </div>
      <p>{{ n.content }}</p>
      <ol v-if="n.self_check_steps?.length"><li v-for="s in n.self_check_steps" :key="s">{{ s }}</li></ol>
      <div class="actions">
        <el-button size="small" icon="Aim" @click.stop="store.locateEvent(n.eventId)">看看在哪</el-button>
        <el-button v-if="n.show_repair_button" type="primary" size="small" @click.stop="repair(n)">一键报修</el-button>
        <el-button v-if="n.show_repair_button" size="small" @click.stop="dismiss(n)">已自行处理</el-button>
      </div>
    </el-card>
    <div class="section-title"><span>设备状态</span></div>
    <div class="devices">
      <div v-for="d in deviceGroups" :key="d.label" class="dev" :class="{ warn: d.warn }">
        <el-icon><component :is="d.icon" /></el-icon>
        <span>{{ d.label }}</span>
        <span class="sub">{{ d.warn ? '需关注' : '正常' }}</span>
      </div>
    </div>
    <el-button v-if="store.ownerHouse" class="chat" icon="ChatDotRound" @click="openChat">AI 报修对话（打开现有系统）</el-button>
    <p class="sub">隐私保护：业主视角只能进入自己的住宅，其他住户只显示建筑外壳。</p>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { ElMessage } from 'element-plus'
import { useTwinStore, getEngine } from '../stores/twin'
import { SEVERITY_META, TYPE_META } from '../data/events'
import { buildingData, houseById } from '../data/resolver'

const store = useTwinStore()
const houses = computed(() => (store.loginUser ? store.loginUser.houseIds : (buildingData()?.houses || []).map(h => h.house_id)).slice().sort((a, b) => Number(a) - Number(b)))
const house = computed({ get: () => store.ownerHouse, set: (v) => store.setOwnerHouse(v) })
const info = computed(() => (store.ownerHouse ? houseById(store.ownerHouse) : null))
const myEvents = computed(() => store.visibleEvents)

const notices = computed(() => {
  const out = []
  for (const e of myEvents.value) {
    const list = e.decision?.notices || []
    for (const n of list) {
      if (!['RESIDENT', 'NEIGHBOR'].includes(n.audience) || !(n.house_ids || []).includes(store.ownerHouse)) continue
      out.push({ ...n, eventId: e.id, severity: e.severity, status: e.status })
    }
  }
  return out
})

const deviceGroups = computed(() => {
  const types = new Set(myEvents.value.filter(e => e.houseId === store.ownerHouse).map(e => TYPE_META[e.type]?.domain))
  return [
    { label: '给排水', icon: 'Drizzling', warn: types.has('WATER') },
    { label: '用电安全', icon: 'Lightning', warn: types.has('POWER') },
    { label: '热水器', icon: 'Sunny', warn: myEvents.value.some(e => e.houseId === store.ownerHouse && e.type === 'WATER_HEATER_SCALING') },
    { label: '空调', icon: 'Cold', warn: myEvents.value.some(e => e.houseId === store.ownerHouse && e.type === 'AC_EFFICIENCY_DROP') },
  ]
})

const goHome = () => store.ownerHouse && getEngine().goHouse(1, store.ownerHouse)
const repair = (n) => { const e = store.events.find(x => x.id === n.eventId); if (e) e.status = 'REPAIR_REQUESTED'; ElMessage.success(store.mode === 'demo' ? '演示模式：已模拟一键报修，工单进入物业待审核' : '已提交报修') }
const dismiss = () => ElMessage.info('已记录：您已自行处理，系统将在复查时确认是否恢复')
const openChat = () => window.open(`${location.protocol}//${location.hostname}:5173/chat/${store.ownerHouse}`, '_blank')
</script>

<style scoped>
.role-panel { display: flex; flex-direction: column; gap: 8px; }
.row { display: flex; gap: 6px; align-items: center; }
.row > .sub { white-space: nowrap; }
.home-card { padding: 8px; border-radius: 8px; background: rgba(22, 119, 255, 0.06); }
.section-title { font-weight: 700; font-size: 13px; margin-top: 4px; }
.ok { display: flex; gap: 6px; align-items: center; font-size: 13px; }
.notice { --el-card-padding: 10px; cursor: pointer; }
.notice p { margin: 6px 0; font-size: 12.5px; line-height: 1.6; }
.notice ol { margin: 0 0 6px; padding-left: 18px; font-size: 12px; }
.notice-top { display: flex; align-items: center; font-size: 13px; }
.actions { display: flex; gap: 4px; flex-wrap: wrap; }
.actions .el-button { margin: 0; }
.devices { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
.dev { display: flex; gap: 6px; align-items: center; padding: 6px 8px; border-radius: 8px; border: 1px solid var(--panel-border); font-size: 13px; }
.dev .sub { margin-left: auto; }
.dev.warn { border-color: #fa8c16; background: rgba(250, 140, 22, 0.08); }
.dev.warn .sub { color: #d46b08; }
.chat { width: 100%; }
</style>
