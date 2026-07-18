<template>
  <div class="space-y-5">
    <div>
      <h1 class="text-xl font-semibold text-neutral-900 sm:text-2xl">模型设置</h1>
      <p class="mt-1 text-sm leading-5 text-neutral-500">配置整理、分析、对话和语音转文字当前使用的可调用模型。</p>
    </div>

    <div class="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
      <section v-for="usage in usages" :key="usage.key" class="bg-white border border-neutral-200 rounded p-4">
        <div class="flex items-center justify-between">
          <div>
            <h2 class="text-base font-medium text-neutral-900">{{ usage.label }}</h2>
            <div class="mt-1 text-xs text-neutral-500">{{ usage.modelType }}</div>
          </div>
          <span class="text-xs" :class="selectionReady(usage.key) ? 'text-green-700' : 'text-red-600'">
            {{ selectionReady(usage.key) ? '已选择' : '未完成' }}
          </span>
        </div>

        <div class="mt-4 space-y-3">
          <select v-model="draft[usage.key].channel_id" class="w-full h-9 px-2 border border-neutral-300 rounded text-sm" @change="handleChannelChange(usage.key)">
            <option value="">选择渠道</option>
            <option v-for="channel in channels" :key="channel.id" :value="channel.id">{{ channel.name }}</option>
          </select>

          <select v-model="draft[usage.key].ability_category" class="w-full h-9 px-2 border border-neutral-300 rounded text-sm" @change="clearAfterCategory(usage.key)">
            <option value="">选择分类</option>
            <option v-for="category in categoriesFor(usage)" :key="category" :value="category">{{ category }}</option>
          </select>

          <div class="relative">
            <input
              v-model="draft[usage.key].model_keyword"
              class="w-full h-9 px-3 border border-neutral-300 rounded text-sm"
              placeholder="输入并选择模型"
              @focus="openModelPickerFor(usage.key)"
              @input="handleModelKeywordInput(usage.key)"
              @blur="closeModelPicker(usage.key)"
            >
            <div
              v-if="openModelPicker === usage.key"
              class="absolute z-20 mt-1 max-h-64 w-full overflow-y-auto bg-white border border-neutral-200 rounded shadow-sm"
            >
              <button
                v-for="item in modelsFor(usage)"
                :key="item.id"
                type="button"
                class="block w-full px-3 py-2 text-left text-sm hover:bg-neutral-50"
                @mousedown.prevent="selectModel(usage.key, item)"
              >
                <span class="block font-medium text-neutral-900">{{ item.model.model_name }}</span>
                <span class="block mt-0.5 text-xs text-neutral-500">{{ item.model.ability_tier }} / {{ item.model.score_label || item.model.score || '-' }}</span>
              </button>
              <div v-if="modelsFor(usage).length === 0" class="px-3 py-2 text-sm text-neutral-400">
                无匹配模型
              </div>
            </div>
          </div>
        </div>

        <div v-if="reasonFor(usage.key)" class="mt-3 text-xs text-red-600">{{ reasonFor(usage.key) }}</div>
        <div class="mt-4 flex items-center gap-3">
          <button class="h-8 px-3 border border-neutral-300 rounded text-sm disabled:opacity-50" :disabled="testingKeys.has(usage.key)" @click="testUsage(usage.key)">
            {{ testingKeys.has(usage.key) ? '测试中' : '测试' }}
          </button>
          <span v-if="testResults[usage.key]" class="text-xs" :class="testResults[usage.key].ok ? 'text-green-700' : 'text-red-600'">
            {{ testResults[usage.key].message }}
          </span>
        </div>
      </section>
    </div>

    <div class="flex flex-col items-stretch justify-end gap-3 sm:flex-row sm:items-center">
      <span v-if="message" class="text-sm text-neutral-500 sm:mr-auto">{{ message }}</span>
      <button class="h-10 px-5 border border-neutral-300 text-sm rounded disabled:opacity-50" :disabled="batchTesting" @click="testSelectedSettings">
        {{ batchTesting ? '批量测试中' : '批量测试' }}
      </button>
      <button class="h-10 px-5 bg-neutral-900 text-white text-sm rounded" @click="saveSettings">
        保存配置
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
definePageMeta({ layout: 'admin', middleware: 'admin' })

const { api } = useApi()

const usages = [
  { key: 'organize', label: '整理', modelType: 'language' },
  { key: 'analysis', label: '分析', modelType: 'language' },
  { key: 'chat', label: '对话', modelType: 'language' },
  { key: 'transcription', label: '语音转文字', modelType: 'asr' },
]

const channels = ref<any[]>([])
const channelModels = ref<any[]>([])
const savedSettings = ref<any[]>([])
const message = ref('')
const openModelPicker = ref('')
const batchTesting = ref(false)
const draft = reactive<any>({})
const testResults = reactive<Record<string, { ok: boolean, message: string }>>({})
const testingKeys = ref(new Set<string>())

for (const usage of usages) {
  draft[usage.key] = { channel_id: '', ability_category: '', channel_model_id: '', model_keyword: '' }
}

const loadData = async () => {
  channels.value = await api('/admin/channels')
  const rows = await Promise.all(channels.value.map(channel => api<any[]>(`/admin/channels/${channel.id}/models`)))
  channelModels.value = rows.flat().filter(item => item.enabled && item.model?.enabled && item.channel?.enabled)
  savedSettings.value = await api('/admin/model-settings')
  for (const setting of savedSettings.value) {
    const cm = setting.channel_model
    if (!cm) continue
    draft[setting.setting_key] = {
      channel_id: cm.channel_id,
      ability_category: cm.model.ability_category,
      channel_model_id: cm.id,
      model_keyword: modelOptionLabel(cm),
    }
  }
}

const candidatesFor = (usage: any) => channelModels.value.filter(item =>
  item.channel_id === draft[usage.key].channel_id &&
  item.model?.model_type === usage.modelType
)

const categoriesFor = (usage: any) => Array.from(new Set(candidatesFor(usage).map(item => item.model.ability_category)))
const scoreOf = (item: any) => Number(item.model?.score ?? -1)
const modelsFor = (usage: any) => {
  const keyword = String(draft[usage.key].model_keyword || '').trim().toLowerCase()
  return candidatesFor(usage)
    .filter(item => !draft[usage.key].ability_category || item.model.ability_category === draft[usage.key].ability_category)
    .filter(item => {
      if (!keyword) return true
      return [
        item.model?.model_name,
        item.model?.ability_tier,
        item.model?.score_label,
        item.model?.score,
      ].some(value => String(value || '').toLowerCase().includes(keyword))
    })
    .sort((a, b) => scoreOf(b) - scoreOf(a) || String(a.model?.model_name || '').localeCompare(String(b.model?.model_name || '')))
}

const modelOptionLabel = (item: any) => `${item.model?.model_name || ''} / ${item.model?.ability_tier || ''} / ${item.model?.score_label || item.model?.score || '-'}`
const selectedModelFor = (key: string) => channelModels.value.find(item => item.id === draft[key].channel_model_id)
const selectionReady = (key: string) => Boolean(draft[key].channel_model_id)

const handleChannelChange = (key: string) => {
  draft[key].ability_category = ''
  draft[key].channel_model_id = ''
  draft[key].model_keyword = ''
  delete testResults[key]
}

const clearAfterCategory = (key: string) => {
  draft[key].channel_model_id = ''
  draft[key].model_keyword = ''
  delete testResults[key]
}

const openModelPickerFor = (key: string) => {
  openModelPicker.value = key
  if (draft[key].channel_model_id) {
    draft[key].model_keyword = ''
  }
}

const handleModelKeywordInput = (key: string) => {
  draft[key].channel_model_id = ''
  openModelPicker.value = key
  delete testResults[key]
}

const selectModel = (key: string, item: any) => {
  draft[key].channel_model_id = item.id
  draft[key].model_keyword = modelOptionLabel(item)
  openModelPicker.value = ''
  delete testResults[key]
}

const closeModelPicker = (key: string) => {
  window.setTimeout(() => {
    if (openModelPicker.value === key) {
      openModelPicker.value = ''
    }
    const selected = selectedModelFor(key)
    if (selected && !draft[key].model_keyword) {
      draft[key].model_keyword = modelOptionLabel(selected)
    }
  }, 120)
}

const reasonFor = (key: string) => {
  const setting = savedSettings.value.find(item => item.setting_key === key)
  return setting?.unavailable_reason || ''
}

const saveSettings = async () => {
  message.value = ''
  const body: Record<string, string> = {}
  for (const usage of usages) {
    if (draft[usage.key].channel_model_id) {
      body[usage.key] = draft[usage.key].channel_model_id
    }
  }
  if (Object.keys(body).length === 0) {
    message.value = '未选择任何模型'
    return
  }
  try {
    savedSettings.value = await api('/admin/model-settings', { method: 'PUT', body: { settings: body } })
    message.value = '已保存'
  } catch (err: any) {
    message.value = err?.data?.detail || '保存失败'
  }
}

const testUsage = async (key: string) => {
  if (!draft[key].channel_model_id) {
    testResults[key] = { ok: false, message: '请先选择模型' }
    return
  }
  testingKeys.value = new Set([...testingKeys.value, key])
  try {
    const result: any = await api('/admin/model-settings/test', {
      method: 'POST',
      body: {
        setting_key: key,
        channel_model_id: draft[key].channel_model_id,
      },
    })
    testResults[key] = {
      ok: result.status === 'ok' || result.status === 'skipped',
      message: result.status === 'ok' ? '测试通过' : (result.message || '测试完成'),
    }
  } catch (err: any) {
    testResults[key] = { ok: false, message: err?.data?.detail || '测试失败' }
  } finally {
    const next = new Set(testingKeys.value)
    next.delete(key)
    testingKeys.value = next
  }
}

const testSelectedSettings = async () => {
  message.value = ''
  const selectedUsages = usages.filter(usage => draft[usage.key].channel_model_id)
  if (selectedUsages.length === 0) {
    message.value = '未选择任何模型'
    return
  }
  batchTesting.value = true
  try {
    const groups = new Map<string, any[]>()
    for (const usage of selectedUsages) {
      const channelModelId = draft[usage.key].channel_model_id
      groups.set(channelModelId, [...(groups.get(channelModelId) || []), usage])
    }
    for (const group of groups.values()) {
      const usage = group[0]
      try {
        const result: any = await api('/admin/model-settings/test', {
          method: 'POST',
          body: {
            setting_key: usage.key,
            channel_model_id: draft[usage.key].channel_model_id,
          },
        })
        const payload = {
          ok: result.status === 'ok' || result.status === 'skipped',
          message: result.status === 'ok' ? '测试通过' : (result.message || '测试完成'),
        }
        for (const item of group) {
          testResults[item.key] = payload
        }
      } catch (err: any) {
        const payload = { ok: false, message: err?.data?.detail || '测试失败' }
        for (const item of group) {
          testResults[item.key] = payload
        }
      }
    }
  } finally {
    batchTesting.value = false
  }
}

onMounted(loadData)
</script>
