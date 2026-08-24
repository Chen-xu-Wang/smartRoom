<template>
  <div class="page-container">
    <h2 class="section-title"><el-icon><Iphone /></el-icon> 扫码进入房屋数字档案</h2>

    <!-- QR Scan Area -->
    <div class="scan-area card">
      <div class="qr-placeholder">
        <el-icon size="64" color="#94a3b8"><Search /></el-icon>
        <p>模拟扫码入口</p>
      </div>
      <p class="scan-tip">选择下方房屋或输入房屋编码进入</p>
      <el-input
        v-model="inputCode"
        placeholder="输入房屋编码（如 HOUSE-1302）"
        style="max-width: 300px; margin: 8px 0"
        @keyup.enter="scanByCode"
      >
        <template #append>
          <el-button @click="scanByCode">进入</el-button>
        </template>
      </el-input>
    </div>

    <!-- House List -->
    <h3 class="subsection-title">或选择已有房屋</h3>
    <el-row :gutter="16">
      <el-col :span="8" v-for="h in houses" :key="h.houseId">
        <el-card class="house-card" shadow="hover">
          <div class="house-info">
            <div class="house-header">
              <span class="house-name">{{ h.building }}{{ h.room }}</span>
              <el-tag size="small" type="info">{{ h.floor }}</el-tag>
            </div>
            <p class="house-detail">{{ h.layout }} | {{ h.area }}㎡</p>
            <p class="house-qr">编码：{{ h.qrCode }}</p>
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
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Iphone, Search } from '@element-plus/icons-vue'
import api from '../api'

const router = useRouter()
const houses = ref([])
const inputCode = ref('')

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
    ElMessage.error('未找到该编码对应的房屋')
  }
}

onMounted(async () => {
  try {
    const res = await api.getHouses()
    houses.value = res.data.houses
  } catch (e) {
    console.error('Failed to load houses:', e)
  }
})
</script>

<style scoped>
.scan-area {
  text-align: center;
  padding: 40px 20px;
}
.qr-placeholder {
  width: 160px;
  height: 160px;
  margin: 0 auto 16px;
  border: 2px dashed #cbd5e1;
  border-radius: 12px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
}
.scan-tip {
  color: var(--text-secondary);
  font-size: 13px;
  margin: 12px 0;
}
.subsection-title {
  font-size: 16px;
  font-weight: 600;
  margin: 24px 0 12px;
  color: var(--text-primary);
}
.house-card { margin-bottom: 16px; }
.house-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.house-name { font-size: 16px; font-weight: 600; }
.house-detail { font-size: 13px; color: var(--text-secondary); margin: 4px 0; }
.house-qr { font-size: 12px; color: var(--text-secondary); font-family: monospace; }
.house-actions {
  display: flex;
  gap: 8px;
  margin-top: 12px;
}
</style>
