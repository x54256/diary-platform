<template>
  <div class="space-y-5">
    <div class="flex items-start justify-between">
      <div>
        <h1 class="text-2xl font-semibold text-neutral-900">渠道管理</h1>
        <p class="mt-1 text-sm text-neutral-500">维护 API 地址、密钥和每个渠道支持的模型。</p>
      </div>
      <button class="h-9 px-4 bg-neutral-900 text-white text-sm rounded" @click="openChannel()">
        新增渠道
      </button>
    </div>

    <section class="bg-white border border-neutral-200 rounded overflow-hidden">
      <table class="w-full text-sm">
        <thead class="bg-neutral-50 text-neutral-500">
          <tr>
            <th class="text-left p-3">状态</th>
            <th class="text-left p-3">渠道名称</th>
            <th class="text-left p-3">API 地址</th>
            <th class="text-left p-3">密钥</th>
            <th class="text-right p-3">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="channel in channels" :key="channel.id" class="border-t border-neutral-100">
            <td class="p-3">{{ channel.enabled ? 'ON' : 'OFF' }}</td>
            <td class="p-3 font-medium text-neutral-900">{{ channel.name }}</td>
            <td class="p-3 max-w-xl truncate">{{ channel.api_base_url }}</td>
            <td class="p-3">{{ channel.has_api_key ? '已配置' : '未配置' }}</td>
            <td class="p-3 text-right space-x-3">
              <button class="text-neutral-900 underline" @click="openChannel(channel)">编辑</button>
              <button class="text-neutral-900 underline" @click="openModels(channel)">支持模型</button>
              <button class="text-neutral-700" @click="toggleChannel(channel)">{{ channel.enabled ? '禁用' : '启用' }}</button>
              <button class="text-red-600" @click="deleteChannel(channel)">删除</button>
            </td>
          </tr>
        </tbody>
      </table>
    </section>

    <div v-if="showChannelForm" class="fixed inset-0 bg-black/30 flex items-center justify-center p-6">
      <div class="w-[560px] bg-white rounded border border-neutral-200 p-5">
        <div class="text-lg font-medium text-neutral-900">{{ channelForm.id ? '编辑渠道' : '新增渠道' }}</div>
        <div class="mt-4 space-y-3">
          <input v-model="channelForm.name" class="w-full h-10 px-3 border border-neutral-300 rounded text-sm" placeholder="渠道名称">
          <input v-model="channelForm.api_base_url" class="w-full h-10 px-3 border border-neutral-300 rounded text-sm" placeholder="API Base URL">
          <input v-model="channelForm.api_key" class="w-full h-10 px-3 border border-neutral-300 rounded text-sm" placeholder="API Key，留空不修改">
          <label class="flex items-center gap-2 text-sm text-neutral-700">
            <input v-model="channelForm.enabled" type="checkbox">
            启用渠道
          </label>
        </div>
        <p v-if="error" class="mt-3 text-sm text-red-600">{{ error }}</p>
        <div class="mt-5 flex justify-between">
          <button v-if="channelForm.id" class="h-9 px-4 border border-red-200 text-red-600 rounded text-sm" @click="clearApiKey">清空密钥</button>
          <span v-else />
          <div class="flex gap-3">
            <button class="h-9 px-4 border border-neutral-300 rounded text-sm" @click="showChannelForm = false">取消</button>
            <button class="h-9 px-4 bg-neutral-900 text-white rounded text-sm" @click="saveChannel">保存</button>
          </div>
        </div>
      </div>
    </div>

    <div v-if="showModelsForm" class="fixed inset-0 bg-black/30 flex items-center justify-center p-6">
      <div class="w-[900px] max-h-[85dvh] overflow-y-auto bg-white rounded border border-neutral-200 p-5">
        <div class="flex items-center justify-between">
          <div class="text-lg font-medium text-neutral-900">{{ selectedChannel?.name }} · 支持模型</div>
          <div class="flex gap-2">
            <button class="h-8 px-3 border border-neutral-300 rounded text-sm" @click="addChannelModel">新增关联</button>
            <button class="h-8 px-3 bg-neutral-900 text-white rounded text-sm" @click="openBulkModels">批量添加</button>
          </div>
        </div>
        <table class="mt-4 w-full text-sm border border-neutral-200">
          <thead class="bg-neutral-50 text-neutral-500">
            <tr>
              <th class="text-left p-2">启用</th>
              <th class="text-left p-2">模型</th>
              <th class="text-right p-2">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, index) in channelModelRows" :key="index" class="border-t border-neutral-100">
              <td class="p-2"><input v-model="row.enabled" type="checkbox"></td>
              <td class="p-2">
                <select v-model="row.model_id" class="w-full h-9 px-2 border border-neutral-300 rounded">
                  <option v-for="model in models" :key="model.id" :value="model.id">
                    {{ model.model_type }} / {{ model.ability_tier }} / {{ model.ability_category }} / {{ model.model_name }}
                  </option>
                </select>
              </td>
              <td class="p-2 text-right">
                <button class="text-red-600" @click="channelModelRows.splice(index, 1)">移除</button>
              </td>
            </tr>
          </tbody>
        </table>
        <p v-if="error" class="mt-3 text-sm text-red-600">{{ error }}</p>
        <div class="mt-5 flex justify-end gap-3">
          <button class="h-9 px-4 border border-neutral-300 rounded text-sm" @click="showModelsForm = false">取消</button>
          <button class="h-9 px-4 bg-neutral-900 text-white rounded text-sm" @click="saveChannelModels">保存</button>
        </div>
      </div>
    </div>

    <div v-if="showBulkModelsForm" class="fixed inset-0 bg-black/40 flex items-center justify-center p-6">
      <div class="w-[960px] max-h-[85dvh] overflow-y-auto bg-white rounded border border-neutral-200 p-5">
        <div class="flex items-center justify-between">
          <div>
            <div class="text-lg font-medium text-neutral-900">批量添加支持模型</div>
            <div class="mt-1 text-sm text-neutral-500">{{ selectedChannel?.name }} · 已选择 {{ bulkSelectedIds.size }} 个</div>
          </div>
          <button class="h-8 px-3 border border-neutral-300 rounded text-sm" @click="showBulkModelsForm = false">关闭</button>
        </div>

        <div class="mt-4 grid grid-cols-6 gap-3">
          <select v-model="bulkFilters.model_type" class="h-9 px-2 border border-neutral-300 rounded text-sm" @change="reloadBulkModels">
            <option value="">全部类型</option>
            <option value="language">language</option>
            <option value="asr">asr</option>
          </select>
          <select v-model="bulkFilters.ability_tier" class="h-9 px-2 border border-neutral-300 rounded text-sm" @change="reloadBulkModels">
            <option value="">全部梯队</option>
            <option v-for="item in tierOptions" :key="item" :value="item">{{ item }}</option>
          </select>
          <select v-model="bulkFilters.ability_category" class="h-9 px-2 border border-neutral-300 rounded text-sm" @change="reloadBulkModels">
            <option value="">全部分类</option>
            <option v-for="item in bulkCategories" :key="item" :value="item">{{ item }}</option>
          </select>
          <input v-model="bulkFilters.keyword" class="col-span-2 h-9 px-3 border border-neutral-300 rounded text-sm" placeholder="搜索模型、特点" @keyup.enter="reloadBulkModels">
          <button class="h-9 px-3 border border-neutral-300 rounded text-sm" @click="reloadBulkModels">查询</button>
        </div>

        <div class="mt-4 flex items-center justify-between text-sm">
          <div class="text-neutral-500">共 {{ bulkTotal }} 条，第 {{ bulkPage }} / {{ bulkTotalPages }} 页</div>
          <div class="flex gap-2">
            <button class="h-8 px-3 border border-neutral-300 rounded" @click="selectAllBulkResults">全选筛选结果</button>
            <button class="h-8 px-3 border border-neutral-300 rounded" @click="clearBulkSelection">清空选择</button>
          </div>
        </div>

        <table class="mt-3 w-full text-sm border border-neutral-200">
          <thead class="bg-neutral-50 text-neutral-500">
            <tr>
              <th class="text-left p-2 w-12">选择</th>
              <th class="text-left p-2">类型</th>
              <th class="text-left p-2">梯队</th>
              <th class="text-left p-2">分类</th>
              <th class="text-left p-2">模型</th>
              <th class="text-left p-2">核心特点</th>
              <th class="text-right p-2">状态</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="model in bulkModels" :key="model.id" class="border-t border-neutral-100" :class="isModelBound(model.id) ? 'bg-neutral-50 text-neutral-400' : ''">
              <td class="p-2">
                <input :checked="bulkSelectedIds.has(model.id)" :disabled="isModelBound(model.id)" type="checkbox" @change="toggleBulkSelection(model, $event)">
              </td>
              <td class="p-2">{{ model.model_type }}</td>
              <td class="p-2">{{ model.ability_tier }}</td>
              <td class="p-2">{{ model.ability_category }}</td>
              <td class="p-2 font-medium">{{ model.model_name }}</td>
              <td class="p-2 max-w-xs">
                <div class="line-clamp-2">{{ model.core_features || '-' }}</div>
              </td>
              <td class="p-2 text-right">{{ isModelBound(model.id) ? '已绑定' : '可添加' }}</td>
            </tr>
          </tbody>
        </table>

        <div class="mt-4 flex items-center justify-between text-sm">
          <div class="flex items-center gap-2">
            <select v-model.number="bulkPageSize" class="h-8 px-2 border border-neutral-300 rounded" @change="reloadBulkModels">
              <option :value="10">10 条/页</option>
              <option :value="20">20 条/页</option>
              <option :value="50">50 条/页</option>
            </select>
            <button class="h-8 px-3 border border-neutral-300 rounded disabled:opacity-50" :disabled="bulkPage <= 1" @click="changeBulkPage(bulkPage - 1)">上一页</button>
            <button class="h-8 px-3 border border-neutral-300 rounded disabled:opacity-50" :disabled="bulkPage >= bulkTotalPages" @click="changeBulkPage(bulkPage + 1)">下一页</button>
          </div>
          <div class="flex gap-3">
            <button class="h-9 px-4 border border-neutral-300 rounded text-sm" @click="showBulkModelsForm = false">取消</button>
            <button class="h-9 px-4 bg-neutral-900 text-white rounded text-sm" @click="addBulkModels">添加已选</button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
definePageMeta({ layout: 'admin', middleware: 'admin' })

const { api } = useApi()
const channels = ref<any[]>([])
const models = ref<any[]>([])
const options = ref<any>({})
const error = ref('')
const showChannelForm = ref(false)
const showModelsForm = ref(false)
const showBulkModelsForm = ref(false)
const selectedChannel = ref<any | null>(null)
const channelModelRows = ref<any[]>([])
const channelForm = reactive<any>({ id: '', name: '', api_base_url: '', api_key: '', enabled: true })
const bulkModels = ref<any[]>([])
const bulkTotal = ref(0)
const bulkPage = ref(1)
const bulkPageSize = ref(20)
const bulkSelectedModels = ref<Record<string, any>>({})
const bulkFilters = reactive({ model_type: '', ability_tier: '', ability_category: '', keyword: '' })
const tierOptions = ['T0 旗舰全能', 'T0.5 推理专项天花板', 'T1 次旗舰均衡', 'T1 专项顶级', 'T2 企业主力', 'T2 通用商用', 'T2.5 中端推理特化', 'T3 轻量通用', 'T3 轻量专项', 'T4 极速轻量']
const bulkCategories = computed(() => {
  if (bulkFilters.model_type === 'asr') return options.value.asr_categories || []
  if (bulkFilters.model_type === 'language') return options.value.language_categories || []
  return [...(options.value.language_categories || []), ...(options.value.asr_categories || [])]
})
const bulkTotalPages = computed(() => Math.max(1, Math.ceil(bulkTotal.value / bulkPageSize.value)))
const bulkSelectedIds = computed(() => new Set(Object.keys(bulkSelectedModels.value)))

watch(() => bulkFilters.model_type, () => {
  const asrCategories = options.value.asr_categories || []
  const languageCategories = options.value.language_categories || []
  if (bulkFilters.model_type === 'asr' && !asrCategories.includes(bulkFilters.ability_category)) {
    bulkFilters.ability_category = ''
  } else if (bulkFilters.model_type === 'language' && !languageCategories.includes(bulkFilters.ability_category)) {
    bulkFilters.ability_category = ''
  }
})

const loadChannels = async () => {
  channels.value = await api('/admin/channels')
}

const loadOptions = async () => {
  options.value = await api('/admin/model-options')
}

const loadModels = async () => {
  const result: any = await api('/admin/models?enabled=true&page=1&page_size=200')
  models.value = result.items || result
}

const buildBulkParams = (pageNumber: number, size: number) => {
  const params = new URLSearchParams()
  params.set('enabled', 'true')
  params.set('page', String(pageNumber))
  params.set('page_size', String(size))
  for (const [key, value] of Object.entries(bulkFilters)) {
    if (value) params.set(key, value)
  }
  return params
}

const loadBulkModels = async () => {
  const result: any = await api(`/admin/models?${buildBulkParams(bulkPage.value, bulkPageSize.value).toString()}`)
  bulkModels.value = result.items || []
  bulkTotal.value = result.total || 0
}

const reloadBulkModels = async () => {
  bulkPage.value = 1
  await loadBulkModels()
}

const changeBulkPage = async (target: number) => {
  bulkPage.value = target
  await loadBulkModels()
}

const openChannel = (channel?: any) => {
  error.value = ''
  Object.assign(channelForm, channel ? { ...channel, api_key: '' } : { id: '', name: '', api_base_url: '', api_key: '', enabled: true })
  showChannelForm.value = true
}

const saveChannel = async () => {
  error.value = ''
  try {
    const body = { ...channelForm }
    if (!body.api_key) delete body.api_key
    if (channelForm.id) {
      await api(`/admin/channels/${channelForm.id}`, { method: 'PATCH', body })
    } else {
      await api('/admin/channels', { method: 'POST', body })
    }
    showChannelForm.value = false
    await loadChannels()
  } catch (err: any) {
    error.value = err?.data?.detail || '保存失败'
  }
}

const clearApiKey = async () => {
  if (!window.confirm('确认清空该渠道密钥？')) return
  try {
    await api(`/admin/channels/${channelForm.id}/clear-api-key`, { method: 'POST' })
    showChannelForm.value = false
    await loadChannels()
  } catch (err: any) {
    error.value = err?.data?.detail || '清空失败'
  }
}

const toggleChannel = async (channel: any) => {
  try {
    await api(`/admin/channels/${channel.id}`, { method: 'PATCH', body: { enabled: !channel.enabled } })
    await loadChannels()
  } catch (err: any) {
    window.alert(err?.data?.detail || '操作失败')
  }
}

const deleteChannel = async (channel: any) => {
  if (!window.confirm(`确认删除渠道 ${channel.name}？模型清单不会被删除。`)) return
  try {
    await api(`/admin/channels/${channel.id}`, { method: 'DELETE' })
    await loadChannels()
  } catch (err: any) {
    window.alert(err?.data?.detail || '删除失败')
  }
}

const openModels = async (channel: any) => {
  error.value = ''
  selectedChannel.value = channel
  await loadModels()
  const rows: any[] = await api(`/admin/channels/${channel.id}/models`)
  channelModelRows.value = rows.map(row => ({
    model_id: row.model_id,
    enabled: row.enabled,
  }))
  showModelsForm.value = true
}

const addChannelModel = () => {
  const model = models.value[0]
  if (!model) return
  channelModelRows.value.push({
    model_id: model.id,
    enabled: true,
  })
}

const isModelBound = (modelId: string) => channelModelRows.value.some(row => row.model_id === modelId)

const openBulkModels = async () => {
  bulkSelectedModels.value = {}
  bulkPage.value = 1
  await loadBulkModels()
  showBulkModelsForm.value = true
}

const toggleBulkSelection = (model: any, event: Event) => {
  const checked = (event.target as HTMLInputElement).checked
  const next = { ...bulkSelectedModels.value }
  if (checked) {
    next[model.id] = model
  } else {
    delete next[model.id]
  }
  bulkSelectedModels.value = next
}

const fetchAllBulkModels = async () => {
  const first: any = await api(`/admin/models?${buildBulkParams(1, 200).toString()}`)
  const items = [...(first.items || [])]
  const total = first.total || items.length
  const pageCount = Math.ceil(total / 200)
  for (let pageNumber = 2; pageNumber <= pageCount; pageNumber += 1) {
    const result: any = await api(`/admin/models?${buildBulkParams(pageNumber, 200).toString()}`)
    items.push(...(result.items || []))
  }
  return items
}

const selectAllBulkResults = async () => {
  const next = { ...bulkSelectedModels.value }
  const items = await fetchAllBulkModels()
  for (const model of items) {
    if (!isModelBound(model.id)) {
      next[model.id] = model
    }
  }
  bulkSelectedModels.value = next
}

const clearBulkSelection = () => {
  bulkSelectedModels.value = {}
}

const addBulkModels = () => {
  const rows = Object.values(bulkSelectedModels.value)
    .filter(model => !isModelBound(model.id))
    .map(model => ({
      model_id: model.id,
      enabled: true,
    }))
  channelModelRows.value.push(...rows)
  bulkSelectedModels.value = {}
  showBulkModelsForm.value = false
}

const saveChannelModels = async () => {
  if (!selectedChannel.value) return
  error.value = ''
  try {
    await api(`/admin/channels/${selectedChannel.value.id}/models`, {
      method: 'PUT',
      body: channelModelRows.value,
    })
    showModelsForm.value = false
  } catch (err: any) {
    error.value = err?.data?.detail || '保存失败'
  }
}

onMounted(async () => {
  await loadOptions()
  await loadChannels()
  await loadModels()
})
</script>
