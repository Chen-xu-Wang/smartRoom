<template>
  <div class="chat-repair-page">
    <div class="chat-layout">
      <!-- Left: House Info -->
      <div class="house-panel card">
        <div class="house-panel-header">
          <el-icon color="#2563eb" size="20"><House /></el-icon>
          <span class="house-title">{{ house?.building }}{{ house?.room }}</span>
        </div>
        <div v-if="house" class="house-details">
          <div class="detail-row"><span>户型</span><span>{{ house.layout }}</span></div>
          <div class="detail-row"><span>面积</span><span>{{ house.area }}㎡</span></div>
          <div class="detail-row"><span>楼层</span><span>{{ house.floor }}</span></div>
          <div class="detail-row"><span>交付日期</span><span>{{ house.deliveryDate }}</span></div>
          <div class="detail-row"><span>MiC模块</span><span class="mono">{{ house.micModuleId }}</span></div>
          <div class="detail-row"><span>数字身份</span><span class="mono">{{ house.digitalId }}</span></div>
        </div>
        <el-divider />
        <div class="quick-links">
          <el-button size="small" @click="$router.push(`/archive/${houseId}`)">
            <el-icon><Document /></el-icon> 查看完整档案
          </el-button>
        </div>
      </div>

      <!-- Center: Chat -->
      <div class="chat-main card">
        <div class="chat-header">
          <h3>AI智能报修助手</h3>
          <el-tag size="small" :type="stateTagType">{{ stateLabel }}</el-tag>
        </div>

        <div class="chat-messages" ref="messagesRef">
          <ChatMessage
            v-for="(msg, i) in chatStore.messages"
            :key="i"
            :msg="msg"
            @confirm="handleConfirm"
            @modify="handleModify"
          />
          <div v-if="chatStore.loading" class="loading-msg">
            <el-icon class="is-loading"><Loading /></el-icon>
            AI正在分析...
          </div>
        </div>

        <!-- Input -->
        <div class="chat-input-area">
          <!-- 附件预览 -->
          <div v-if="chatStore.attachments.length" class="attachment-chips">
            <el-tag v-for="(a,i) in chatStore.attachments" :key="i" closable size="small" @close="chatStore.attachments.splice(i,1)">
              {{ a.file_name }} <span v-if="a.file_url" style="opacity:.6">✓</span>
            </el-tag>
          </div>
          <el-input
            v-model="inputText"
            type="textarea"
            :rows="2"
            placeholder="描述您遇到的问题，如：厨房水槽下面一直漏水（支持文字、附件、语音）"
            @keyup.enter.ctrl="send"
            :disabled="chatStore.loading"
          />
          <div class="input-actions">
            <div class="input-tools">
              <el-upload
                :show-file-list="false"
                :multiple="true"
                :before-upload="() => false"
                :on-change="handleFileChange"
                :auto-upload="false"
                accept="*/*"
              >
                <el-button size="small" :loading="uploading" :disabled="chatStore.loading">
                  <el-icon><Paperclip /></el-icon> 上传文件
                </el-button>
              </el-upload>
              <input ref="fileInputRef" type="file" multiple style="display:none" @change="onNativeFileChange" />
              <el-button size="small" :type="isRecording ? 'danger' : 'info'" plain @click="toggleVoice" :loading="transcribing">
                <el-icon><Microphone /></el-icon> {{ isRecording ? '停止录音' : '语音输入' }}
              </el-button>
              <span v-if="isRecording" class="recording-hint">正在录音...请说话，松开或点击停止</span>
            </div>
            <div class="send-actions">
              <el-button type="primary" @click="send" :disabled="!inputText.trim() || chatStore.loading">
                发送
              </el-button>
              <el-button @click="quickFill" :disabled="chatStore.loading">快捷输入</el-button>
            </div>
          </div>
          <div v-if="voiceError" class="voice-error">{{ voiceError }}</div>
          <div class="input-tip">支持任意文件（图片/视频/文档/音频等）与语音转文字，AI 会结合附件与语音内容自动建单</div>
        </div>
      </div>

      <!-- Right: Agent State -->
      <div class="agent-panel card">
        <h4>Agent状态</h4>
        <div class="state-badge" :class="`state-${chatStore.agentState}`">
          {{ stateLabel }}
        </div>

        <div v-if="Object.keys(chatStore.extractedInfo).length" class="panel-section">
          <h5>提取信息</h5>
          <div class="extracted-info">
            <div v-for="(v, k) in chatStore.extractedInfo" :key="k" class="ext-item">
              <span class="ext-key">{{ k }}：</span>{{ v }}
            </div>
          </div>
        </div>

        <div v-if="chatStore.toolCalls.length" class="panel-section">
          <h5>工具调用记录</h5>
          <div v-for="(tc, i) in chatStore.toolCalls" :key="i" class="tc-item">
            <el-icon color="#16a34a" size="12"><Check /></el-icon>
            {{ tc.description }}
          </div>
        </div>

        <div v-if="chatStore.workOrder" class="panel-section">
          <h5>当前工单</h5>
          <div class="wo-mini">
            <div>类型：{{ chatStore.workOrder.fault_type }}</div>
            <div>工种：{{ chatStore.workOrder.suggested_trade }}</div>
            <div>紧急度：{{ chatStore.workOrder.urgency }}</div>
            <div>置信度：{{ chatStore.workOrder.confidence }}%</div>
          </div>
        </div>

        <el-divider />
        <el-button size="small" type="info" plain @click="restart">
          <el-icon><RefreshLeft /></el-icon> 重新开始
        </el-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, nextTick, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { House, Document, Loading, Check, RefreshLeft, Paperclip, Microphone } from '@element-plus/icons-vue'
import { useChatStore } from '../stores/chat'
import api from '../api'
import ChatMessage from '../components/ChatMessage.vue'

const route = useRoute()
const router = useRouter()
const chatStore = useChatStore()
const houseId = route.params.houseId
const house = ref(null)
const inputText = ref('')
const messagesRef = ref(null)
const fileInputRef = ref(null)
const uploading = ref(false)
const isRecording = ref(false)
const transcribing = ref(false)
const voiceError = ref('')
let recognition = null
let mediaRecorder = null
let audioChunks = []
let mediaStream = null

const stateMap = {
  start: '初始化',
  collecting_info: '信息收集中',
  info_complete: '信息完整',
  querying_archive: '查询档案中',
  searching_kb: '知识库检索中',
  generating_order: '生成工单中',
  order_pending: '等待确认',
  complete: '已自动提交',
}

const stateLabel = computed(() => stateMap[chatStore.agentState] || '未知')
const stateTagType = computed(() => {
  const s = chatStore.agentState
  if (s === 'complete') return 'success'
  if (s === 'order_pending') return 'warning'
  if (s && s.includes('query') || s && s.includes('search')) return 'primary'
  return 'info'
})

const quickExamples = [
  '厨房水槽下面今天一直漏水',
  '卫生间排水很慢，下水堵了',
  '卧室空调不制冷了',
  '客厅插座突然没电了',
  '阳台窗户关不严，下雨渗水',
]
let exampleIdx = 0

const send = async () => {
  if (!inputText.value.trim()) return
  const text = inputText.value
  inputText.value = ''
  const data = await chatStore.sendMessage(text)
  await scrollToBottom()
  if (data?.auto_submitted && data?.work_order_id) {
    ElMessage.success(`已自动提交工单 ${data.work_order_id}，等待物业审核`)
  }
}

const quickFill = () => {
  inputText.value = quickExamples[exampleIdx % quickExamples.length]
  exampleIdx++
}

const handleFileChange = async (file) => {
  const raw = file?.raw || file
  if (!raw) return
  uploading.value = true
  try {
    await chatStore.uploadAttachments([raw])
    await scrollToBottom()
    ElMessage.success(`已上传 ${raw.name}`)
  } catch (e) {
    ElMessage.error('上传失败')
  } finally {
    uploading.value = false
  }
}

const onNativeFileChange = async (e) => {
  const files = Array.from(e.target.files || [])
  if (!files.length) return
  uploading.value = true
  try {
    await chatStore.uploadAttachments(files)
    await scrollToBottom()
    ElMessage.success(`已上传 ${files.length} 个文件`)
  } finally {
    uploading.value = false
    e.target.value = ''
  }
}

const toggleVoice = async () => {
  voiceError.value = ''
  if (isRecording.value) {
    stopVoice()
    return
  }
  // 优先尝试浏览器原生语音识别
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition
  if (SR) {
    recognition = new SR()
    recognition.lang = 'zh-CN'
    recognition.interimResults = false
    recognition.continuous = false
    recognition.onstart = () => { isRecording.value = true }
    recognition.onend = () => { isRecording.value = false }
    recognition.onerror = (e) => {
      voiceError.value = '语音识别失败：' + (e.error || '未知错误')
      isRecording.value = false
      fallbackMediaRecord()
    }
    recognition.onresult = (e) => {
      const text = e.results?.[0]?.[0]?.transcript || ''
      if (text) inputText.value = (inputText.value ? inputText.value + ' ' : '') + text
      isRecording.value = false
    }
    try { recognition.start() } catch (e) { voiceError.value = String(e); fallbackMediaRecord() }
    return
  }
  fallbackMediaRecord()
}

const fallbackMediaRecord = async () => {
  if (isRecording.value) { stopVoice(); return }
  try {
    mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true })
    mediaRecorder = new MediaRecorder(mediaStream, { mimeType: MediaRecorder.isTypeSupported('audio/webm') ? 'audio/webm' : 'audio/mp4' })
    audioChunks = []
    mediaRecorder.ondataavailable = (e) => { if (e.data.size > 0) audioChunks.push(e.data) }
    mediaRecorder.onstop = async () => {
      const blob = new Blob(audioChunks, { type: mediaRecorder.mimeType || 'audio/webm' })
      const file = new File([blob], `voice_${Date.now()}.webm`, { type: blob.type })
      transcribing.value = true
      try {
        const res = await api.transcribeAudio(file)
        if (res.data?.success && res.data?.text) {
          inputText.value = (inputText.value ? inputText.value + ' ' : '') + res.data.text
          ElMessage.success('语音已转文字')
        } else {
          voiceError.value = res.data?.error || '转写未返回文字，请手动输入'
        }
      } catch (err) {
        voiceError.value = err.response?.data?.detail || '语音上传失败，请手动输入'
      } finally {
        transcribing.value = false
        if (mediaStream) { mediaStream.getTracks().forEach(t => t.stop()); mediaStream = null }
      }
    }
    mediaRecorder.start()
    isRecording.value = true
    voiceError.value = '正在录音...完成后点击停止'
  } catch (e) {
    voiceError.value = '无法访问麦克风：' + (e.message || '请检查权限')
  }
}

const stopVoice = () => {
  try { recognition?.stop?.(); } catch {}
  recognition = null
  if (mediaRecorder && mediaRecorder.state !== 'inactive') {
    try { mediaRecorder.stop() } catch {}
  }
  isRecording.value = false
  if (mediaStream) { mediaStream.getTracks().forEach(t => t.stop()); mediaStream = null }
}

const handleConfirm = async () => {
  try {
    await ElMessageBox.confirm('确认提交此工单？', '确认', { type: 'info' })
    const res = await chatStore.confirmOrder()
    ElMessage.success('工单已提交，等待物业审核')
    router.push(`/workorder/${res.work_order_id}`)
  } catch {
    // cancelled
  }
}

const handleModify = async () => {
  await chatStore.modifyOrder()
  await scrollToBottom()
}

const restart = async () => {
  await chatStore.init(houseId)
  await scrollToBottom()
}

const scrollToBottom = async () => {
  await nextTick()
  if (messagesRef.value) {
    messagesRef.value.scrollTop = messagesRef.value.scrollHeight
  }
}

watch(() => chatStore.messages.length, () => {
  scrollToBottom()
})

onBeforeUnmount(() => {
  stopVoice()
})

onMounted(async () => {
  try {
    const res = await api.getHouse(houseId)
    house.value = res.data
    await chatStore.init(houseId)
    await scrollToBottom()
  } catch (e) {
    ElMessage.error('加载房屋信息失败')
  }
})
</script>

<style scoped>
.chat-repair-page {
  padding: 16px;
  max-width: 1400px;
  margin: 0 auto;
}
.chat-layout {
  display: grid;
  grid-template-columns: 240px 1fr 260px;
  gap: 16px;
  height: calc(100vh - 160px);
}
.house-panel {
  overflow-y: auto;
}
.house-panel-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}
.house-title { font-size: 18px; font-weight: 700; }
.detail-row {
  display: flex;
  justify-content: space-between;
  padding: 4px 0;
  font-size: 13px;
}
.detail-row span:first-child { color: var(--text-secondary); }
.mono { font-family: monospace; font-size: 11px; color: var(--primary-color); }

.chat-main {
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.chat-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--border-color);
}
.chat-header h3 { font-size: 16px; }
.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
}
.loading-msg {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--text-secondary);
  font-size: 13px;
  padding: 8px;
}
.chat-input-area {
  padding: 12px;
  border-top: 1px solid var(--border-color);
}
.attachment-chips { display:flex; flex-wrap:wrap; gap:6px; margin-bottom:8px; }
.input-actions {
  display: flex;
  gap: 8px;
  justify-content: space-between;
  align-items: center;
  margin-top: 8px;
  flex-wrap: wrap;
}
.input-tools { display:flex; gap:8px; align-items:center; flex-wrap:wrap; }
.send-actions { display:flex; gap:8px; }
.recording-hint { font-size:12px; color:#ef4444; animation: pulse 1s infinite; }
.voice-error { font-size:12px; color:#ef4444; margin-top:6px; }
.input-tip { font-size:11px; color:var(--text-secondary, #909399); margin-top:6px; }
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.5} }

.agent-panel {
  overflow-y: auto;
}
.agent-panel h4 { font-size: 14px; margin-bottom: 12px; }
.state-badge {
  padding: 8px 12px;
  border-radius: 8px;
  background: var(--primary-light);
  color: var(--primary-color);
  font-weight: 600;
  text-align: center;
  font-size: 13px;
  margin-bottom: 12px;
}
.state-complete { background: #dcfce7; color: #16a34a; }
.state-order_pending { background: #fef3c7; color: #ca8a04; }
.panel-section { margin-top: 12px; }
.panel-section h5 {
  font-size: 12px;
  color: var(--text-secondary);
  margin-bottom: 6px;
  font-weight: 600;
}
.extracted-info {
  background: #f8fafc;
  border-radius: 6px;
  padding: 8px;
}
.ext-item {
  font-size: 12px;
  padding: 2px 0;
}
.ext-key { color: var(--text-secondary); }
.tc-item {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  padding: 4px 0;
}
.wo-mini {
  font-size: 12px;
  background: #f8fafc;
  padding: 8px;
  border-radius: 6px;
}
.wo-mini div { padding: 2px 0; }
</style>
