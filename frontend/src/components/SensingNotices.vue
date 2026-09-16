<template>
  <div v-if="groups.length" class="notice-wrap">
    <h3 class="notice-heading">💧⚡ 水电安全提醒 <el-tag size="small" type="info">模拟数据</el-tag></h3>
    <el-card v-for="n in groups" :key="n.key" class="notice-card" shadow="never">
      <div class="notice-top">
        <div>
          <strong>{{ n.title }}</strong>
          <span class="notice-house">{{ houseText(n) }}{{ n.audience === 'NEIGHBOR' ? ' · 相关住户通知' : '' }}</span>
        </div>
        <el-tag size="small" :type="statusTag(n.status)">{{ statusLabel(n.status) }}</el-tag>
      </div>
      <p class="notice-content">{{ n.content }}</p>
      <ol v-if="n.self_check_steps.length && isOpen(n)" class="notice-steps">
        <li v-for="step in n.self_check_steps" :key="step">{{ step }}</li>
      </ol>
      <div class="notice-actions">
        <template v-if="isOpen(n) && n.show_repair_button && !n.work_order_id">
          <el-button type="primary" size="small" :loading="acting === n.key" @click="repair(n)">一键报修</el-button>
          <el-button size="small" :disabled="acting === n.key" @click="dismiss(n)">已自行处理 / 忽略</el-button>
        </template>
        <el-link v-if="n.work_order_id" type="primary" :underline="false"
                 @click="$router.push(`/workorder/${n.work_order_id}`)">
          {{ n.audience === 'RESIDENT' ? '物业已派单，查看工单' : '查看工单' }} {{ n.work_order_id }}
        </el-link>
        <el-button v-if="isOpen(n) && (!n.show_repair_button || n.work_order_id)" size="small" @click="acknowledge(n)">我知道了</el-button>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRouter } from 'vue-router'
import api from '../api'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const auth = useAuthStore()
const notices = ref([])
const acting = ref(null)

const isOpen = n => ['UNREAD', 'READ'].includes(n.status)
const statusLabel = s => ({ UNREAD: '新提醒', READ: '已读', REPAIR_REQUESTED: '已报修', DISMISSED: '已关闭', ARCHIVED: '已归档' })[s] || s
const statusTag = s => ({ UNREAD: 'danger', READ: 'warning', REPAIR_REQUESTED: 'primary', DISMISSED: 'info' })[s] || 'info'
const errMsg = (e, fallback) => e?.response?.data?.detail?.message || fallback

// 演示页不区分登录住户，楼栋级事件会给同相几十户发同一条通知：内容、状态一致的合并成一张卡片
const groups = computed(() => {
  const map = new Map()
  for (const n of notices.value) {
    const key = [n.event_id, n.audience, n.title, n.content, n.status === 'UNREAD' ? 'READ' : n.status, n.work_order_id].join('|')
    if (!map.has(key)) map.set(key, { ...n, key, ids: [], houses: [] })
    const g = map.get(key)
    g.ids.push(n.id)
    g.houses.push(n.house_id)
    if (n.status === 'UNREAD') g.status = 'UNREAD'
  }
  return [...map.values()]
})
const houseText = g => (g.houses.length > 3 ? `${g.houses.slice(0, 3).join('、')} 等 ${g.houses.length} 户` : g.houses.join('、'))

const load = async () => {
  try {
    const res = await api.getSensingNotices()
    notices.value = res.data.notices || []
    notices.value.filter(n => n.status === 'UNREAD').forEach(n => api.readSensingNotice(n.id).catch(() => {}))
  } catch {
    notices.value = []
  }
}

const repair = async (g) => {
  acting.value = g.key
  try {
    const res = await api.repairFromNotice(g.ids[0], auth.user?.id)
    ElMessage.success(`已提交报修，工单 ${res.data.work_order_id} 等待物业审核`)
    router.push(`/workorder/${res.data.work_order_id}`)
  } catch (e) {
    ElMessage.error(errMsg(e, '报修失败'))
  } finally {
    acting.value = null
  }
}

const closeGroup = async (g) => {
  try {
    await Promise.all(g.ids.map(id => api.dismissNotice(id)))
    await load()
  } catch (e) {
    ElMessage.error(errMsg(e, '操作失败'))
  }
}

// 紧急类提醒（已自动建单）和相关住户通知不需要住户决定是否报修，只需确认已读
const acknowledge = g => closeGroup(g)

const dismiss = async (g) => {
  try {
    await ElMessageBox.confirm('确认已自行处理，或是您自己调小了阀门？关闭后系统不再为这次提醒建单。', '关闭提醒', { type: 'info' })
  } catch {
    return
  }
  await closeGroup(g)
}

onMounted(load)
</script>

<style scoped>
.notice-wrap { margin: 20px 0 8px; }
.notice-heading { display: flex; align-items: center; gap: 8px; font-size: 16px; font-weight: 600; margin-bottom: 10px; }
.notice-card { margin-bottom: 10px; border: 1px solid #bae6fd; background: #f8fdff; }
.notice-top { display: flex; justify-content: space-between; align-items: center; gap: 10px; }
.notice-house { margin-left: 8px; font-size: 12px; color: #64748b; }
.notice-content { margin: 8px 0; font-size: 13px; line-height: 1.8; color: #334155; }
.notice-steps { margin: 0 0 8px 18px; font-size: 13px; color: #334155; line-height: 1.8; }
.notice-actions { display: flex; gap: 8px; }
.notice-actions .el-button { margin-left: 0; }
</style>
