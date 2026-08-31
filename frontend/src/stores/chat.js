import { defineStore } from 'pinia'
import api from '../api'

export const useChatStore = defineStore('chat', {
  state: () => ({
    sessionId: null,
    orderNo: null,
    houseId: null,
    house: null,
    messages: [],
    agentState: null,
    extractedInfo: {},
    toolCalls: [],
    workOrder: null,
    ragResults: [],
    archiveData: null,
    attachments: [],
    loading: false,
  }),
  actions: {
    async init(houseId) {
      this.loading = true
      this.messages = []
      this.toolCalls = []
      this.workOrder = null
      this.ragResults = []
      this.archiveData = null
      this.extractedInfo = {}

      try {
        // 携带当前登录用户 ID，确保工单真实归属到报修人（审计与「我的工单」可用）
        let reporterId = null
        try {
          const saved = JSON.parse(localStorage.getItem('zw_auth') || 'null')
          reporterId = saved?.id || null
        } catch { reporterId = null }
        const res = await api.initChat(houseId, reporterId)
        this.sessionId = res.data.session_id
        this.orderNo = res.data.order_no
        this.houseId = houseId
        this.agentState = res.data.agent_state
        if (res.data.message) {
          this.messages.push({
            role: 'assistant',
            content: res.data.message.content,
            timestamp: res.data.message.timestamp,
          })
        }
      } finally {
        this.loading = false
      }
    },

    async sendMessage(text) {
      if (!this.sessionId || !text.trim()) return
      this.loading = true
      this.messages.push({
        role: 'user',
        content: text,
        timestamp: new Date().toISOString(),
      })

      try {
        const res = await api.sendMessage(this.sessionId, text)
        const data = res.data

        this.agentState = data.agent_state
        this.extractedInfo = data.extracted_info || {}
        this.toolCalls = data.tool_calls || this.toolCalls
        this.workOrder = data.work_order || this.workOrder
        this.ragResults = data.rag_results || this.ragResults
        this.archiveData = data.archive_data || this.archiveData

        this.messages.push({
          role: 'assistant',
          content: data.content,
          timestamp: data.timestamp,
          agentState: data.agent_state,
          extractedInfo: data.extracted_info,
          toolCalls: data.tool_calls,
          workOrder: data.work_order,
          ragResults: data.rag_results,
          archiveData: data.archive_data,
          autoSubmitted: data.auto_submitted || false,
          workOrderId: data.work_order_id || null,
          solution: data.solution || data.work_order?.solution || null,
        })
        // 自动提交后，输入框自动禁用，提示用户查看工单
        if (data.auto_submitted && data.work_order_id) {
          this.workOrder = data.work_order
        }
        return data
      } finally {
        this.loading = false
      }
    },

    async confirmOrder() {
      if (!this.sessionId) return
      const res = await api.chatAction(this.sessionId, 'confirm_order')
      return res.data
    },

    async modifyOrder() {
      if (!this.sessionId) return
      const res = await api.chatAction(this.sessionId, 'modify_order')
      this.agentState = res.data.agent_state
      this.messages.push({
        role: 'assistant',
        content: '请补充或修改信息。',
        timestamp: new Date().toISOString(),
      })
    },

    async uploadAttachments(files) {
      if (!this.orderNo) return []
      const results = []
      for (const file of files) {
        const ext = (file.name.split('.').pop() || '').toLowerCase()
        let atype = 'file'
        if (['jpg','jpeg','png','gif','webp','bmp'].includes(ext)) atype = 'photo'
        else if (['mp4','mov','avi','webm'].includes(ext)) atype = 'video'
        else if (['mp3','wav','m4a','webm','ogg'].includes(ext)) atype = 'audio'
        else if (['pdf','doc','docx','xls','xlsx','txt'].includes(ext)) atype = 'doc'
        try {
          const res = await api.uploadAttachment(this.orderNo, file, atype, '')
          results.push(res.data)
          this.attachments.push(res.data)
          this.messages.push({
            role: 'user',
            content: `【附件】已上传 ${file.name}（${atype}）`,
            timestamp: new Date().toISOString(),
            attachment: res.data,
          })
          // 将附件信息以文本形式喂给 AI，便于分析时引用
          await this.sendMessage(`【附件说明】我上传了文件 ${file.name}，类型 ${atype}，请结合该附件分析故障。`)
        } catch (e) {
          this.messages.push({
            role: 'assistant',
            content: `附件 ${file.name} 上传失败：${e.response?.data?.detail || e.message}`,
            timestamp: new Date().toISOString(),
          })
        }
      }
      return results
    },
  },
})
