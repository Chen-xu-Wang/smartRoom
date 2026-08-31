<template>
  <div class="page-container">
    <div class="page-heading">
      <div>
        <h2 class="section-title"><el-icon><User /></el-icon> 人员管理</h2>
        <p>管理维修工、物业与住户账号，维修工可配置技能、负荷与在岗状态。</p>
      </div>
      <el-button type="primary" :icon="Plus" @click="openAdd">新增人员</el-button>
    </div>

    <div class="card" style="margin-bottom:12px; display:flex; gap:12px; align-items:center; flex-wrap:wrap">
      <el-radio-group v-model="filterRole" @change="load">
        <el-radio-button label="">全部</el-radio-button>
        <el-radio-button label="REPAIRER">维修工</el-radio-button>
        <el-radio-button label="PROPERTY">物业</el-radio-button>
        <el-radio-button label="RESIDENT">住户</el-radio-button>
      </el-radio-group>
      <el-input v-model="keyword" placeholder="搜索：用户名/姓名/手机" clearable @input="applyFilter" style="max-width:280px" />
      <span style="margin-left:auto; font-size:12px; color:#64748b">共 {{ filtered.length }} 人</span>
    </div>

    <div class="card">
      <el-table :data="filtered" v-loading="loading" border stripe>
        <el-table-column prop="username" label="用户名" width="130" />
        <el-table-column prop="real_name" label="姓名" width="110" />
        <el-table-column prop="role" label="角色" width="100">
          <template #default="{row}"><el-tag :type="roleTag(row.role)" size="small">{{ roleLabel(row.role) }}</el-tag></template>
        </el-table-column>
        <el-table-column prop="phone" label="手机" width="130" />
        <el-table-column label="技能/状态" min-width="200">
          <template #default="{row}">
            <template v-if="row.role==='REPAIRER'">
              <el-tag v-for="s in row.skills" :key="s" size="small" effect="plain" style="margin-right:4px">{{ s }}</el-tag>
              <el-tag size="small" :type="row.on_duty? 'success':'info'">{{ row.on_duty? '在岗':'休息' }}</el-tag>
              <span style="margin-left:6px; font-size:11px; color:#64748b">{{ row.active_orders ?? row.max_active_orders }}/{{ row.max_active_orders }} · 今日{{ row.daily_capacity }}</span>
            </template>
            <span v-else style="font-size:12px; color:#64748b">—</span>
          </template>
        </el-table-column>
        <el-table-column prop="status" label="启用" width="80">
          <template #default="{row}"><el-tag :type="row.status? 'success':'danger'" size="small">{{ row.status? '正常':'禁用' }}</el-tag></template>
        </el-table-column>
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{row}">
            <el-button size="small" @click="openEdit(row)">编辑</el-button>
            <el-popconfirm title="确认删除该人员？" @confirm="remove(row)"><template #reference><el-button size="small" type="danger">删除</el-button></template></el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog v-model="dialogVisible" :title="isEdit?'编辑人员':'新增人员'" width="560px">
      <el-form :model="form" label-width="90px">
        <el-form-item label="用户名" required><el-input v-model="form.username" :disabled="isEdit" /></el-form-item>
        <el-form-item label="姓名" required><el-input v-model="form.real_name" /></el-form-item>
        <el-form-item label="手机"><el-input v-model="form.phone" /></el-form-item>
        <el-form-item label="角色" required>
          <el-select v-model="form.role" style="width:100%">
            <el-option label="维修工 REPAIRER" value="REPAIRER" />
            <el-option label="物业 PROPERTY" value="PROPERTY" />
            <el-option label="住户 RESIDENT" value="RESIDENT" />
            <el-option label="管理员 ADMIN" value="ADMIN" />
          </el-select>
        </el-form-item>
        <el-form-item :label="isEdit?'新密码':'密码'" :required="!isEdit"><el-input v-model="form.password" type="password" placeholder="默认 123456" /></el-form-item>
        <template v-if="form.role==='REPAIRER'">
          <el-form-item label="技能">
            <el-select v-model="form.skills" multiple filterable allow-create placeholder="如 水电维修">
              <el-option label="水电维修" value="水电维修" /><el-option label="电工维修" value="电工维修" /><el-option label="空调维修" value="空调维修" /><el-option label="门窗维修" value="门窗维修" /><el-option label="综合维修" value="综合维修" />
            </el-select>
          </el-form-item>
          <el-form-item label="并发上限"><el-input-number v-model="form.max_active_orders" :min="1" :max="10" /></el-form-item>
          <el-form-item label="日容量"><el-input-number v-model="form.daily_capacity" :min="1" :max="20" /></el-form-item>
          <el-form-item label="在岗"><el-switch v-model="form.on_duty" :active-value="1" :inactive-value="0" /></el-form-item>
        </template>
        <el-form-item v-if="isEdit" label="启用"><el-switch v-model="form.status" :active-value="1" :inactive-value="0" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible=false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { User, Plus } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import api from '../api'

const loading = ref(false)
const saving = ref(false)
const dialogVisible = ref(false)
const isEdit = ref(false)
const filterRole = ref('REPAIRER')
const keyword = ref('')
const users = ref([])
const filtered = ref([])
const form = ref({ username:'', real_name:'', phone:'', role:'REPAIRER', password:'', skills:['综合维修'], max_active_orders:3, daily_capacity:5, on_duty:1, status:1 })
const editingId = ref(null)

const roleLabel = r=> ({REPAIRER:'维修工',PROPERTY:'物业',RESIDENT:'住户',ADMIN:'管理员'}[r]||r)
const roleTag = r=> ({REPAIRER:'info',PROPERTY:'warning',RESIDENT:'success',ADMIN:'danger'}[r]||'info')

const applyFilter=()=>{
  let list = users.value
  const kw = keyword.value.trim().toLowerCase()
  if(kw) list = list.filter(u=> [u.username,u.real_name,u.phone].join(' ').toLowerCase().includes(kw))
  filtered.value = list
}
const load=async()=>{
  loading.value=true
  try{ const r=await api.adminListUsers(filterRole.value||undefined); users.value=r.data.users||[]; applyFilter() } finally{ loading.value=false }
}
const openAdd=()=>{
  isEdit.value=false; editingId.value=null
  form.value={ username:'', real_name:'', phone:'', role:'REPAIRER', password:'123456', skills:['综合维修'], max_active_orders:3, daily_capacity:5, on_duty:1, status:1 }
  dialogVisible.value=true
}
const openEdit=(row)=>{
  isEdit.value=true; editingId.value=row.id
  form.value={ username:row.username, real_name:row.real_name, phone:row.phone, role:row.role, password:'', skills:row.skills||['综合维修'], max_active_orders:row.max_active_orders||3, daily_capacity:row.daily_capacity||5, on_duty:row.on_duty??1, status:row.status??1 }
  dialogVisible.value=true
}
const save=async()=>{
  if(!form.value.username||!form.value.real_name){ ElMessage.warning('请填写用户名/姓名'); return }
  if(!isEdit.value && !form.value.password){ ElMessage.warning('请填写密码'); return }
  saving.value=true
  try{
    if(isEdit.value){
      const payload={ real_name:form.value.real_name, phone:form.value.phone, role:form.value.role, status:form.value.status }
      if(form.value.password) payload.password=form.value.password
      if(form.value.role==='REPAIRER'){ payload.skills=form.value.skills; payload.max_active_orders=form.value.max_active_orders; payload.daily_capacity=form.value.daily_capacity; payload.on_duty=form.value.on_duty }
      await api.adminUpdateUser(editingId.value, payload)
    } else {
      await api.adminCreateUser(form.value)
    }
    ElMessage.success(isEdit.value?'已更新':'已新增'); dialogVisible.value=false; await load()
  }catch(e){ ElMessage.error(e.response?.data?.detail||'保存失败') } finally{ saving.value=false }
}
const remove=async(row)=>{
  try{ await api.adminDeleteUser(row.id); ElMessage.success('已删除'); await load() }catch(e){ ElMessage.error(e.response?.data?.detail||'删除失败') }
}
onMounted(load)
</script>

<style scoped>
.page-heading{ display:flex; justify-content:space-between; align-items:flex-start; gap:16px; margin-bottom:16px; }
.page-heading p{ color:var(--text-secondary); font-size:13px; }
</style>
