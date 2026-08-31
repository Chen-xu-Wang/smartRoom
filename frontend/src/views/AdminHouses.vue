<template>
  <div class="page-container">
    <div class="page-heading">
      <div>
        <h2 class="section-title"><el-icon><House /></el-icon> 房屋档案管理</h2>
        <p>物业可新增、编辑、删除房屋档案，一房一码自动生成，支持管线与设备追溯。</p>
      </div>
      <el-button type="primary" :icon="Plus" @click="openAdd">新增房屋</el-button>
    </div>

    <div class="stats-row">
      <div class="stat-card card"><div class="stat-value">{{ houses.length }}</div><div class="stat-label">在管房屋</div></div>
      <div class="stat-card card"><div class="stat-value">{{ totalArea }}㎡</div><div class="stat-label">总面积</div></div>
      <div class="stat-card card"><div class="stat-value">{{ qrReady }}</div><div class="stat-label">已赋码</div></div>
    </div>

    <div class="card" style="margin-bottom:12px">
      <el-input v-model="keyword" placeholder="搜索：编号/楼栋/房号/户型" clearable @input="filterHouses" style="max-width:360px" />
    </div>

    <div class="card">
      <el-table :data="filtered" v-loading="loading" border stripe>
        <el-table-column prop="houseId" label="房屋编号" width="100" />
        <el-table-column label="楼栋房号" width="140">
          <template #default="{row}">{{ row.building }}{{ row.room }} <span style="color:#909399">{{ row.unit }}</span></template>
        </el-table-column>
        <el-table-column prop="floor" label="楼层" width="90" />
        <el-table-column prop="layout" label="户型" min-width="130" />
        <el-table-column prop="area" label="面积" width="90">
          <template #default="{row}">{{ row.area }}㎡</template>
        </el-table-column>
        <el-table-column prop="qrCode" label="一房一码" width="130" />
        <el-table-column prop="micModuleId" label="MiC模块" width="150" show-overflow-tooltip />
        <el-table-column label="操作" width="220" fixed="right">
          <template #default="{row}">
            <el-button size="small" @click="openEdit(row)">编辑</el-button>
            <el-button size="small" type="info" @click="$router.push(`/archive/${row.houseId}`)">档案</el-button>
            <el-popconfirm title="确认删除该房屋？" @confirm="remove(row)">
              <template #reference><el-button size="small" type="danger">删除</el-button></template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog v-model="dialogVisible" :title="isEdit ? '编辑房屋' : '新增房屋'" width="560px">
      <el-form :model="form" label-width="90px">
        <el-form-item label="房屋编号" required><el-input v-model="form.house_code" :disabled="isEdit" placeholder="如 1302 / 1201" /></el-form-item>
        <el-form-item label="楼栋" required><el-input v-model="form.building_no" placeholder="如 1栋" /></el-form-item>
        <el-form-item label="单元"><el-input v-model="form.unit_no" placeholder="如 1单元" /></el-form-item>
        <el-form-item label="房号" required><el-input v-model="form.room_no" placeholder="如 1302室" /></el-form-item>
        <el-form-item label="面积"><el-input v-model.number="form.area" type="number" placeholder="㎡" /></el-form-item>
        <el-form-item label="楼层"><el-input v-model="form.floor" placeholder="如 13层" /></el-form-item>
        <el-form-item label="户型"><el-input v-model="form.layout" placeholder="如 三室两厅" /></el-form-item>
        <el-form-item label="MiC模块"><el-input v-model="form.micModuleId" /></el-form-item>
        <el-form-item label="数字ID"><el-input v-model="form.digitalId" /></el-form-item>
        <el-form-item label="交付日期"><el-input v-model="form.deliveryDate" type="date" placeholder="YYYY-MM-DD" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible=false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { House, Plus } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import api from '../api'

const houses = ref([])
const loading = ref(false)
const keyword = ref('')
const filtered = ref([])
const dialogVisible = ref(false)
const isEdit = ref(false)
const saving = ref(false)
const form = ref({ house_code:'', building_no:'', unit_no:'', room_no:'', area:null, floor:'', layout:'', micModuleId:'', digitalId:'', deliveryDate:'' })

const totalArea = computed(()=> houses.value.reduce((s,h)=> s+(Number(h.area)||0),0).toFixed(1))
const qrReady = computed(()=> houses.value.filter(h=>h.qrCode).length)

const filterHouses = ()=>{
  const kw = keyword.value.trim().toLowerCase()
  if(!kw){ filtered.value = houses.value; return }
  filtered.value = houses.value.filter(h=> [h.houseId,h.building,h.room,h.layout,h.qrCode].join(' ').toLowerCase().includes(kw))
}

const load = async()=>{
  loading.value=true
  try{ const r=await api.adminListHouses(); houses.value=r.data.houses||[]; filterHouses() } finally{ loading.value=false }
}
const openAdd=()=>{
  isEdit.value=false
  form.value={ house_code:'', building_no:'', unit_no:'', room_no:'', area:null, floor:'', layout:'', micModuleId:'', digitalId:'', deliveryDate:''}
  dialogVisible.value=true
}
const openEdit=(row)=>{
  isEdit.value=true
  form.value={ house_code:row.houseId, building_no:row.building, unit_no:row.unit, room_no:row.room, area:row.area, floor:row.floor, layout:row.layout, micModuleId:row.micModuleId, digitalId:row.digitalId, deliveryDate:row.deliveryDate}
  dialogVisible.value=true
}
const save=async()=>{
  if(!form.value.house_code||!form.value.building_no||!form.value.room_no){ ElMessage.warning('请填写编号/楼栋/房号'); return }
  saving.value=true
  try{
    if(isEdit.value) await api.adminUpdateHouse(form.value.house_code, form.value)
    else await api.adminCreateHouse(form.value)
    ElMessage.success(isEdit.value?'已更新':'已新增')
    dialogVisible.value=false; await load()
  }catch(e){ ElMessage.error(e.response?.data?.detail||'保存失败') } finally{ saving.value=false }
}
const remove=async(row)=>{
  try{ await api.adminDeleteHouse(row.houseId); ElMessage.success('已删除'); await load() }catch(e){ ElMessage.error(e.response?.data?.detail||'删除失败') }
}
onMounted(load)
</script>

<style scoped>
.page-heading{ display:flex; justify-content:space-between; align-items:flex-start; gap:16px; margin-bottom:16px; }
.page-heading p{ color:var(--text-secondary); font-size:13px; }
.stats-row{ display:grid; grid-template-columns: repeat(3,1fr); gap:12px; margin-bottom:14px; }
.stat-card{ text-align:center; padding:14px; }
.stat-value{ font-size:22px; font-weight:700; }
.stat-label{ font-size:12px; color:#64748b; }
</style>
