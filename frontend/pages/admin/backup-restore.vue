<template>
  <div class="space-y-6">
    <div>
      <h1 class="text-xl font-semibold text-neutral-900 sm:text-2xl">系统备份与恢复</h1>
      <p class="mt-1 text-sm text-neutral-500">导出、校验并恢复系统核心数据。</p>
    </div>

    <div class="border border-amber-200 bg-amber-50 text-amber-900 rounded px-4 py-3 text-sm">
      高敏感操作：备份包包含用户数据和加密密码字段，请仅在受控环境中操作。
    </div>

    <div class="grid grid-cols-1 gap-6 lg:grid-cols-2">
      <section class="bg-white border border-neutral-200 rounded p-5">
        <h2 class="text-base font-medium text-neutral-900">导出数据</h2>
        <div class="mt-4 space-y-3">
          <label v-for="item in scopeOptions" :key="item.value" class="flex items-center gap-2 text-sm text-neutral-700">
            <input v-model="exportForm.scope_type" type="radio" :value="item.value">
            {{ item.label }}
          </label>
        </div>

        <div v-if="exportForm.scope_type.includes('users')" class="mt-4">
          <label class="block text-sm text-neutral-700 mb-1">用户 ID，多个用英文逗号分隔</label>
          <input v-model="userIdsInput" class="w-full h-10 px-3 border border-neutral-300 rounded text-sm">
        </div>

        <div v-if="exportForm.scope_type.includes('diary_date')" class="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div>
            <label class="block text-sm text-neutral-700 mb-1">开始日期</label>
            <input v-model="exportForm.start_date" type="date" class="w-full h-10 px-3 border border-neutral-300 rounded text-sm">
          </div>
          <div>
            <label class="block text-sm text-neutral-700 mb-1">结束日期</label>
            <input v-model="exportForm.end_date" type="date" class="w-full h-10 px-3 border border-neutral-300 rounded text-sm">
          </div>
        </div>

        <div class="mt-4 text-xs text-neutral-500 leading-5">
          包含用户、日记原文、整理结果、事件、分析结果和标签关系。导出包使用系统主密钥加密，7 天内可下载。
        </div>

        <button class="mt-5 h-10 px-4 bg-neutral-900 text-white text-sm rounded" @click="createExport">
          开始导出
        </button>
      </section>

      <section class="bg-white border border-neutral-200 rounded p-5">
        <h2 class="text-base font-medium text-neutral-900">导入恢复</h2>
        <div class="mt-4 border border-dashed border-neutral-300 rounded p-6">
          <input type="file" accept=".zip" @change="handleFileChange">
          <div class="mt-2 text-xs text-neutral-500">上传加密 ZIP 备份包后先执行预检。</div>
        </div>

        <button class="mt-4 h-10 px-4 bg-neutral-900 text-white text-sm rounded disabled:opacity-60" :disabled="!selectedFile" @click="precheckImport">
          开始预检
        </button>

        <div v-if="precheckResult" class="mt-5">
          <div class="text-sm font-medium text-neutral-900 mb-2">预检结果</div>
          <div class="overflow-x-auto">
          <table class="w-full min-w-[420px] text-sm border border-neutral-200">
            <thead class="bg-neutral-50">
              <tr>
                <th class="text-left p-2 border-b">数据</th>
                <th class="text-right p-2 border-b">新增</th>
                <th class="text-right p-2 border-b">跳过</th>
                <th class="text-right p-2 border-b">失败</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in precheckResult.tables" :key="row.table">
                <td class="p-2 border-b">{{ row.table }}</td>
                <td class="p-2 text-right border-b">{{ row.created }}</td>
                <td class="p-2 text-right border-b">{{ row.skipped }}</td>
                <td class="p-2 text-right border-b">{{ row.failed }}</td>
              </tr>
            </tbody>
          </table>
          </div>
          <button class="mt-4 h-10 px-4 bg-red-600 text-white text-sm rounded" @click="createImport">
            确认导入
          </button>
        </div>
      </section>
    </div>

    <section class="bg-white border border-neutral-200 rounded overflow-hidden">
      <div class="px-5 py-4 border-b border-neutral-200 flex items-center justify-between">
        <h2 class="text-base font-medium text-neutral-900">备份恢复记录</h2>
        <button class="text-sm text-neutral-500 hover:text-neutral-900" @click="loadRecords">刷新</button>
      </div>
      <div class="overflow-x-auto">
      <table class="w-full min-w-[720px] text-sm">
        <thead class="bg-neutral-50 text-neutral-500">
          <tr>
            <th class="text-left p-3">类型</th>
            <th class="text-left p-3">状态</th>
            <th class="text-left p-3">范围</th>
            <th class="text-left p-3">阶段</th>
            <th class="text-left p-3">结果</th>
            <th class="text-left p-3">时间</th>
            <th class="text-right p-3">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="record in records" :key="record.id" class="border-t border-neutral-100">
            <td class="p-3">{{ record.operation_type }}</td>
            <td class="p-3">{{ record.status }}</td>
            <td class="p-3 max-w-xs truncate">{{ record.scope_summary }}</td>
            <td class="p-3">{{ record.current_phase }} {{ record.current_table || '' }}</td>
            <td class="p-3 max-w-sm">
              <span v-if="record.error_summary" class="text-red-600">{{ record.error_summary }}</span>
              <span v-else class="text-neutral-500">{{ summaryText(record.result_summary) }}</span>
            </td>
            <td class="p-3">{{ formatTime(record.created_at) }}</td>
            <td class="p-3 text-right space-x-3">
              <button v-if="record.operation_type === 'export' && record.status === 'success'" class="text-neutral-900 underline" @click="downloadExport(record.id, record.file_name)">
                下载
              </button>
              <button v-if="record.operation_type === 'export' && record.status === 'running'" class="text-red-600" @click="cancelExport(record.id)">
                取消
              </button>
              <button v-if="record.operation_type === 'import'" class="text-neutral-900 underline" @click="loadReport(record.id)">
                报告
              </button>
            </td>
          </tr>
        </tbody>
      </table>
      </div>
    </section>

    <section v-if="reportRows.length" class="bg-white border border-neutral-200 rounded p-5">
      <h2 class="text-base font-medium text-neutral-900 mb-3">导入报告</h2>
      <div class="overflow-x-auto">
      <table class="w-full min-w-[560px] text-sm border border-neutral-200">
        <thead class="bg-neutral-50">
          <tr>
            <th class="text-left p-2 border-b">表</th>
            <th class="text-right p-2 border-b">新增</th>
            <th class="text-right p-2 border-b">跳过</th>
            <th class="text-right p-2 border-b">失败</th>
            <th class="text-left p-2 border-b">失败摘要</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in reportRows" :key="row.table_name">
            <td class="p-2 border-b">{{ row.table_name }}</td>
            <td class="p-2 text-right border-b">{{ row.created_count }}</td>
            <td class="p-2 text-right border-b">{{ row.skipped_count }}</td>
            <td class="p-2 text-right border-b">{{ row.failed_count }}</td>
            <td class="p-2 border-b">{{ row.failure_summary }}</td>
          </tr>
        </tbody>
      </table>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
definePageMeta({
  layout: 'admin',
  middleware: 'admin',
})

const { api } = useApi()

const scopeOptions = [
  { value: 'all', label: '全量导出' },
  { value: 'users', label: '按用户筛选' },
  { value: 'diary_date', label: '按日记日期筛选' },
  { value: 'users_and_diary_date', label: '用户 + 日期交集' },
]

const exportForm = reactive({
  scope_type: 'all',
  start_date: '',
  end_date: '',
})
const userIdsInput = ref('')
const selectedFile = ref<File | null>(null)
const precheckResult = ref<any | null>(null)
const precheckRecordId = ref('')
const records = ref<any[]>([])
const reportRows = ref<any[]>([])

const userIds = computed(() => userIdsInput.value.split(',').map((item) => item.trim()).filter(Boolean))

const createExport = async () => {
  const confirmed = window.confirm('确认导出系统备份？备份包包含用户数据和加密密码字段，操作会写入审计记录。')
  if (!confirmed) return
  await api('/admin/backup-restore/exports', {
    method: 'POST',
    body: {
      scope_type: exportForm.scope_type,
      user_ids: userIds.value,
      start_date: exportForm.start_date || null,
      end_date: exportForm.end_date || null,
    },
  })
  await loadRecords()
}

const handleFileChange = (event: Event) => {
  const input = event.target as HTMLInputElement
  selectedFile.value = input.files?.[0] || null
}

const precheckImport = async () => {
  if (!selectedFile.value) return
  const formData = new FormData()
  formData.append('file', selectedFile.value)
  const result: any = await api('/admin/backup-restore/imports/precheck', {
    method: 'POST',
    body: formData,
  })
  precheckResult.value = result.precheck
  precheckRecordId.value = result.record.id
  await loadRecords()
}

const createImport = async () => {
  const confirmed = window.confirm('确认导入备份包？已有 ID 一律跳过，不覆盖。正式导入开始后不可取消。')
  if (!confirmed) return
  await api('/admin/backup-restore/imports', {
    method: 'POST',
    body: { record_id: precheckRecordId.value },
  })
  await loadRecords()
}

const loadRecords = async () => {
  records.value = await api('/admin/backup-restore/records')
}

const cancelExport = async (id: string) => {
  await api(`/admin/backup-restore/exports/${id}/cancel`, { method: 'POST' })
  await loadRecords()
}

const loadReport = async (id: string) => {
  reportRows.value = await api(`/admin/backup-restore/imports/${id}/report`)
}

const downloadExport = async (id: string, fileName?: string) => {
  const blob = await api<Blob>(`/admin/backup-restore/exports/${id}/download`, {
    responseType: 'blob',
  } as any)
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = fileName || 'diary-platform-backup.zip'
  link.click()
  URL.revokeObjectURL(url)
}

const formatTime = (value?: string) => {
  if (!value) return '-'
  return new Date(value).toLocaleString()
}

const summaryText = (value?: string) => {
  if (!value) return '-'
  return value.length > 80 ? `${value.slice(0, 80)}...` : value
}

onMounted(loadRecords)
</script>
