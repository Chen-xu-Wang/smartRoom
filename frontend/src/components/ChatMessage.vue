<template>
  <div class="chat-message" :class="`chat-message-${msg.role}`">
    <div class="chat-avatar" v-if="msg.role === 'assistant'">AI</div>
    <div class="chat-bubble">
      <div v-if="msg.attachment" class="msg-attachment">
        <el-icon><Paperclip /></el-icon>
        <span>{{ msg.attachment.file_name }}</span>
        <a v-if="msg.attachment.file_url" :href="msg.attachment.file_url" target="_blank" style="margin-left:6px;font-size:11px">查看</a>
      </div>
      <div class="markdown-content" v-html="renderedContent"></div>

      <!-- Extracted Info -->
      <div v-if="msg.extractedInfo && Object.keys(msg.extractedInfo).length" class="info-panel">
        <div class="info-title">AI提取的结构化信息</div>
        <div class="info-grid">
          <div v-for="(val, key) in msg.extractedInfo" :key="key" class="info-item">
            <span class="info-key">{{ fieldLabels[key] || key }}：</span>
            <span class="info-val">{{ val }}</span>
          </div>
        </div>
      </div>

      <!-- Tool Calls -->
      <div v-if="msg.toolCalls && msg.toolCalls.length" class="tool-calls">
        <div class="tool-title">AI工具调用</div>
        <div v-for="(tc, i) in msg.toolCalls" :key="i" class="tool-call-item">
          <el-icon color="#2563eb" size="14"><Check v-if="tc.status === 'completed'" /><Loading v-else /></el-icon>
          <span class="tool-name">{{ tc.description }}</span>
          <el-collapse>
            <el-collapse-item title="详情" name="1">
              <div class="tool-detail">
                <div>输入：{{ JSON.stringify(tc.input, null, 2) }}</div>
                <div>输出：{{ JSON.stringify(tc.output, null, 2) }}</div>
              </div>
            </el-collapse-item>
          </el-collapse>
        </div>
      </div>

      <!-- Archive Data -->
      <div v-if="msg.archiveData" class="archive-panel">
        <div class="archive-title">房屋数字档案（AI调用结果）</div>
        <div v-if="msg.archiveData.equipment && msg.archiveData.equipment.length" class="equipment-list">
          <div v-for="eq in msg.archiveData.equipment" :key="eq.id" class="equipment-item">
            <el-tag size="small" type="success">{{ eq.name }}</el-tag>
            <span class="eq-spec">{{ eq.spec }}</span>
            <span class="eq-id">{{ eq.id }}</span>
          </div>
        </div>
        <div v-if="msg.archiveData.pipeline_info && Object.keys(msg.archiveData.pipeline_info).length" class="pipeline-info">
          <div v-for="(v, k) in msg.archiveData.pipeline_info" :key="k" class="pipeline-item">
            <span class="pipe-key">{{ k }}：</span><span>{{ v }}</span>
          </div>
        </div>
        <div v-if="msg.archiveData.maintenance_history && msg.archiveData.maintenance_history.length" class="history-info">
          <el-alert type="warning" :closable="false" style="margin-top: 8px">
            该房屋已有{{ msg.archiveData.maintenance_history.length }}条维修记录
          </el-alert>
        </div>
      </div>

      <!-- RAG Results -->
      <div v-if="msg.ragResults && msg.ragResults.length" class="rag-panel">
        <div class="rag-title">运维知识库检索结果</div>
        <div v-for="(r, i) in msg.ragResults" :key="i" class="rag-item">
          <el-tag size="small" type="warning">知识</el-tag>
          <span class="rag-header">{{ r.header }}</span>
          <div class="rag-content">{{ r.content }}</div>
        </div>
      </div>

      <!-- Work Order -->
      <div v-if="msg.workOrder" class="order-panel">
        <div class="order-title">AI生成的维修工单</div>
        <div v-if="msg.autoSubmitted || msg.workOrderId" class="auto-submit-banner">
          <el-alert type="success" :closable="false" show-icon style="margin-bottom:8px">
            <template #title>✅ 已自动提交工单 {{ msg.workOrderId || msg.workOrder.id }}</template>
            <div style="font-size:12px">AI 已给出处置建议并自动建单，等待物业审核。无需手动确认。</div>
          </el-alert>
          <div style="display:flex;gap:8px">
            <el-button size="small" type="primary" @click="router.push(`/workorder/${msg.workOrderId || msg.workOrder.id}`)">查看工单</el-button>
            <el-button size="small" @click="$emit('modify')">补充信息</el-button>
          </div>
        </div>
        <WorkOrderCard v-else :order="msg.workOrder" :show-actions="true" @confirm="$emit('confirm')" @modify="$emit('modify')" />
        <WorkOrderCard v-if="msg.autoSubmitted" :order="msg.workOrder" :show-actions="false" style="margin-top:8px" />
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { marked } from 'marked'
import { Check, Loading, Paperclip } from '@element-plus/icons-vue'
import WorkOrderCard from './WorkOrderCard.vue'

const router = useRouter()

const props = defineProps({
  msg: { type: Object, required: true }
})

defineEmits(['confirm', 'modify'])

const fieldLabels = {
  location: '位置',
  device: '设备',
  symptom: '故障现象',
  severity: '严重程度',
  occurrence_time: '发生时间',
  leak_after_close: '关阀后仍漏水',
  other_devices_affected: '其他设备影响',
  ac_detail: '空调详情',
  raw_description: '原始描述',
}

const renderedContent = computed(() => {
  try {
    return marked(props.msg.content || '')
  } catch {
    return props.msg.content || ''
  }
})
</script>

<style scoped>
.chat-avatar {
  width: 32px; height: 32px;
  border-radius: 50%;
  background: var(--primary-color);
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 700;
  flex-shrink: 0;
  margin-right: 8px;
}
.chat-message-ai {
  display: flex;
  justify-content: flex-start;
  margin-bottom: 16px;
}
.chat-message-ai .chat-bubble {
  background: white;
  border: 1px solid var(--border-color);
  border-radius: 4px 16px 16px 16px;
  padding: 12px 16px;
  max-width: 90%;
  flex: 1;
}
.chat-message-user {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 12px;
}
.chat-message-user .chat-bubble {
  background: var(--primary-color);
  color: white;
  border-radius: 16px 4px 16px 16px;
  padding: 10px 16px;
  max-width: 70%;
}

.info-panel, .tool-calls, .archive-panel, .rag-panel, .order-panel {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid #e8e8e8;
}
.info-title, .tool-title, .archive-title, .rag-title, .order-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 8px;
}
.info-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.info-item {
  background: #f0f9ff;
  padding: 4px 10px;
  border-radius: 6px;
  font-size: 12px;
}
.info-key { color: var(--text-secondary); }
.info-val { color: var(--primary-color); font-weight: 500; }

.tool-call-item {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  padding: 6px 0;
  font-size: 12px;
}
.tool-detail {
  font-size: 11px;
  color: var(--text-secondary);
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 200px;
  overflow-y: auto;
}

.equipment-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 0;
  font-size: 12px;
}
.eq-spec { color: var(--text-secondary); }
.eq-id { color: #94a3b8; font-family: monospace; font-size: 11px; }

.pipeline-item { font-size: 12px; padding: 2px 0; }
.pipe-key { color: var(--text-secondary); font-weight: 500; }

.rag-item {
  padding: 8px;
  background: #fffbeb;
  border-radius: 6px;
  margin-bottom: 6px;
  font-size: 12px;
}
.msg-attachment { display:flex; align-items:center; gap:6px; background:#f0f9ff; border:1px solid #dbeafe; padding:6px 10px; border-radius:6px; font-size:12px; margin-bottom:6px; }
.rag-header { font-weight: 600; margin-left: 4px; }
.rag-content { color: var(--text-secondary); font-size: 11px; margin-top: 4px; }
</style>
