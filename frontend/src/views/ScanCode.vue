<template>
  <div class="page-container scan-page">
    <h2 class="section-title"><el-icon><Iphone /></el-icon> 扫码进入房屋数字档案</h2>
    <p class="section-sub">通过一房一码进入专属房屋，AI 对话一键触发真实工单</p>

    <!-- 工单触发链路说明 -->
    <el-alert type="info" :closable="false" class="trigger-guide" show-icon>
      <template #title>如何触发工单</template>
      <div class="guide-steps">
        <span class="step"><b>①</b> 扫码或选择房屋</span>
        <span class="arrow">→</span>
        <span class="step"><b>②</b> AI 对话描述故障</span>
        <span class="arrow">→</span>
        <span class="step"><b>③</b> AI 生成结构化工单</span>
        <span class="arrow">→</span>
        <span class="step"><b>④</b> 确认提交</span>
        <span class="arrow">→</span>
        <span class="step"><b>⑤</b> 物业审核派单</span>
      </div>
      <div class="guide-tip">工单创建后状态为 <b>待物业审核</b>，物业审核通过后自动进入智能派单，真实写入 MySQL 并可全程追踪。</div>
    </el-alert>

    <!-- 扫码区 -->
    <div class="scan-area card">
      <div class="scan-grid">
        <div class="scan-left">
          <h4>摄像头扫码</h4>
          <div v-if="!scanning" class="qr-placeholder" @click="startScan">
            <el-icon size="48" color="#94a3b8"><Camera /></el-icon>
            <p>点击开启摄像头扫码</p>
            <el-button type="primary" size="small" style="margin-top:8px">开启扫码</el-button>
          </div>
          <div v-else class="scanner-box">
            <div id="qr-reader" class="qr-reader"></div>
            <el-button size="small" type="info" plain style="margin-top:8px" @click="stopScan">关闭摄像头</el-button>
          </div>
          <p v-if="scanError" class="scan-error">{{ scanError }}</p>
          <el-divider style="margin:12px 0">或</el-divider>
          <el-upload :show-file-list="false" :before-upload="onFileUpload" accept="image/*">
            <el-button size="small"><el-icon><Upload /></el-icon> 上传二维码图片识别</el-button>
          </el-upload>
        </div>
        <div class="scan-right">
          <h4>输入房屋编码</h4>
          <p class="scan-tip">每套房拥有唯一一房一码（如 HOUSE-1302），可在物业门牌或房屋档案中查看</p>
          <el-input
            v-model="inputCode"
            placeholder="输入房屋编码（如 HOUSE-1302）"
            @keyup.enter="scanByCode"
          >
            <template #append>
              <el-button type="primary" @click="scanByCode">进入报修</el-button>
            </template>
          </el-input>
        </div>
      </div>
    </div>

    <!-- 房屋列表 + 二维码 -->
    <h3 class="subsection-title">选择房屋进入</h3>
    <p class="subsection-tip">下方为当前已建档房屋，点击「一键报修」直接进入 AI 对话；点击「查看档案」可查看完整一房一码档案</p>
    <el-row :gutter="16">
      <el-col :span="8" v-for="h in houses" :key="h.houseId">
        <el-card class="house-card" shadow="hover">
          <div class="house-qr-box">
            <canvas :ref="el => setQrCanvas(el, h.qrCode)" width="120" height="120" class="house-qr-canvas"></canvas>
          </div>
          <div class="house-info">
            <div class="house-header">
              <span class="house-name">{{ h.building }}{{ h.room }}</span>
              <el-tag size="small" type="info">{{ h.floor }}</el-tag>
            </div>
            <p class="house-detail">{{ h.layout }} | {{ h.area }}㎡</p>
            <p class="house-qr">一房一码：{{ h.qrCode }}</p>
            <div class="house-actions">
              <el-button size="small" type="primary" @click="$router.push(`/chat/${h.houseId}`)">
                AI报修
              </el-button>
              <el-button size="small" @click="$router.push(`/archive/${h.houseId}`)">
                查看档案
              </el-button>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Iphone, Camera, Upload } from '@element-plus/icons-vue'
import QRCode from 'qrcode'
import { Html5Qrcode } from 'html5-qrcode'
import api from '../api'

const router = useRouter()
const houses = ref([])
const inputCode = ref('')
const scanning = ref(false)
const scanError = ref('')
let html5Qr = null

const scanByCode = async () => {
  if (!inputCode.value.trim()) {
    ElMessage.warning('请输入房屋编码')
    return
  }
  try {
    const res = await api.getHouseByQR(inputCode.value.trim())
    if (res.data) {
      router.push(`/chat/${res.data.houseId}`)
    }
  } catch (e) {
    ElMessage.error('未找到该编码对应的房屋，请检查一房一码是否正确')
  }
}

const startScan = async () => {
  scanError.value = ''
  scanning.value = true
  await nextTick()
  try {
    html5Qr = new Html5Qrcode('qr-reader')
    await html5Qr.start(
      { facingMode: 'environment' },
      { fps: 10, qrbox: { width: 220, height: 220 } },
      (decodedText) => {
        handleDecoded(decodedText)
      },
      () => {}
    )
  } catch (e) {
    scanError.value = '无法启动摄像头：' + (e?.message || '请检查浏览器权限或使用 HTTPS')
    scanning.value = false
  }
}

const stopScan = async () => {
  try {
    if (html5Qr) {
      await html5Qr.stop()
      html5Qr.clear()
      html5Qr = null
    }
  } catch {}
  scanning.value = false
}

const handleDecoded = async (text) => {
  // 一房一码形如 HOUSE-1302，直接按编码查询
  const code = (text || '').trim()
  if (!code) return
  await stopScan()
  try {
    const res = await api.getHouseByQR(code)
    if (res.data) {
      ElMessage.success(`识别成功：${code}`)
      router.push(`/chat/${res.data.houseId}`)
    } else {
      ElMessage.warning(`识别到 ${code}，但未找到对应房屋`)
    }
  } catch {
    ElMessage.error(`识别到 ${code}，但未找到对应房屋`)
  }
}

const onFileUpload = (file) => {
  // 用 Html5Qrcode 解析图片文件
  const reader = new FileReader()
  reader.onload = async () => {
    try {
      const tempId = 'qr-file-reader'
      let tempEl = document.getElementById(tempId)
      if (!tempEl) {
        tempEl = document.createElement('div')
        tempEl.id = tempId
        tempEl.style.display = 'none'
        document.body.appendChild(tempEl)
      }
      const fileQr = new Html5Qrcode(tempId)
      const result = await fileQr.scanFile(file, true)
      handleDecoded(result)
    } catch (e) {
      ElMessage.error('图片中未识别到有效二维码')
    }
  }
  reader.readAsDataURL(file)
  return false
}

const setQrCanvas = (canvas, text) => {
  if (!canvas || !text) return
  QRCode.toCanvas(canvas, text, { width: 120, margin: 1, color: { dark: '#1e3a8a', light: '#ffffff' } }).catch(() => {})
}

onMounted(async () => {
  try {
    const res = await api.getHouses()
    houses.value = res.data.houses
    await nextTick()
    // 二维码在 setQrCanvas 回调中绘制
  } catch (e) {
    console.error('Failed to load houses:', e)
  }
})

onBeforeUnmount(() => {
  stopScan()
})
</script>

<style scoped>
.scan-page { padding-bottom: 24px; }
.section-sub { text-align: center; color: var(--text-secondary, #6b7280); font-size: 13px; margin: 4px 0 16px; }
.trigger-guide { margin-bottom: 16px; }
.guide-steps { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin: 6px 0; font-size: 13px; }
.guide-steps .step { background: #fff; border: 1px solid #dbeafe; padding: 4px 10px; border-radius: 999px; }
.guide-steps .arrow { color: #93c5fd; font-weight: 700; }
.guide-tip { font-size: 12px; color: #64748b; margin-top: 6px; }
.scan-area { padding: 20px; }
.scan-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }
.scan-left, .scan-right { text-align: center; }
.scan-left h4, .scan-right h4 { font-size: 14px; margin-bottom: 10px; }
.qr-placeholder {
  width: 220px; height: 220px; margin: 0 auto; border: 2px dashed #cbd5e1; border-radius: 12px;
  display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 6px; cursor: pointer;
}
.qr-placeholder p { font-size: 12px; color: #64748b; }
.scanner-box { display: flex; flex-direction: column; align-items: center; }
.qr-reader { width: 260px; min-height: 220px; border-radius: 12px; overflow: hidden; background: #0f172a; }
.scan-error { color: #ef4444; font-size: 12px; margin-top: 8px; }
.scan-tip { color: var(--text-secondary); font-size: 12px; margin: 8px 0 10px; line-height: 1.6; }
.subsection-title { font-size: 16px; font-weight: 600; margin: 24px 0 4px; color: var(--text-primary); }
.subsection-tip { font-size: 12px; color: var(--text-secondary, #6b7280); margin-bottom: 12px; }
.house-card { margin-bottom: 16px; display: flex; flex-direction: column; align-items: center; padding-top: 12px; }
.house-qr-box { display: flex; justify-content: center; margin-bottom: 10px; background: #f8fafc; border-radius: 10px; padding: 8px; }
.house-qr-canvas { display: block; border-radius: 6px; }
.house-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; width: 100%; }
.house-name { font-size: 15px; font-weight: 600; }
.house-detail { font-size: 13px; color: var(--text-secondary); margin: 4px 0; text-align: center; }
.house-qr { font-size: 12px; color: var(--text-secondary); font-family: monospace; text-align: center; }
.house-actions { display: flex; gap: 8px; margin-top: 12px; justify-content: center; }
@media (max-width: 900px) { .scan-grid { grid-template-columns: 1fr; } }
</style>
