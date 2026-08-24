import { defineStore } from 'pinia'
import api from '../api'

export const useChatStore = defineStore('chat', {
  state: () => ({
    sessionId: null,
    houseId: null,
    house: null,
    messages: [],
    agentState: null,
    extractedInfo: {},
    toolCalls: [],
    workOrder: null,
    ragResults: [],
    archiveData: null,
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
        const res = await api.initChat(houseId)
        this.sessionId = res.data.session_id
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
        })
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
  },
})
