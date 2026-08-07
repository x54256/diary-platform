<template>
  <div class="space-y-5">
    <div>
      <h1 class="text-xl font-semibold text-neutral-900 sm:text-2xl">模型设置</h1>
      <p class="mt-1 text-sm leading-5 text-neutral-500">配置整理、分析、对话、语音转文字和语义向量化当前使用的可调用模型。</p>
    </div>

    <section class="bg-white border border-neutral-200 rounded p-4">
      <h2 class="text-base font-medium text-neutral-900">整理流程开关</h2>
      <p class="mt-1 text-sm text-neutral-500">关闭后对应环节直接透传结果，不调用模型；修改立即对新启动或恢复的任务生效。</p>
      <div class="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
        <label class="flex items-center gap-3 text-sm text-neutral-700">
          <input v-model="organizeSettings.clean_check_enabled" type="checkbox" class="h-4 w-4">
          保留清洗审核
        </label>
        <label class="flex items-center gap-3 text-sm text-neutral-700">
          <input v-model="organizeSettings.content_check_enabled" type="checkbox" class="h-4 w-4">
          保留内容审核
        </label>
      </div>
      <div class="mt-4 flex items-center gap-3">
        <button class="h-8 px-3 bg-neutral-900 text-white rounded text-sm disabled:opacity-50" :disabled="savingOrganizeSettings" @click="saveOrganizeSettings">
          {{ savingOrganizeSettings ? '保存中' : '保存流程开关' }}
        </button>
        <span v-if="organizeSettingsMessage" class="text-sm text-neutral-500">{{ organizeSettingsMessage }}</span>
      </div>
    </section>

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

          <label v-if="usage.key !== 'transcription' && usage.key !== 'embedding'" class="flex items-center gap-3 text-sm text-neutral-700">
            <input v-model="draft[usage.key].thinking_enabled" type="checkbox" class="h-4 w-4">
            启用思考
          </label>
        </div>

        <div v-if="reasonFor(usage.key)" class="mt-3 text-xs text-red-600">{{ reasonFor(usage.key) }}</div>
        <div class="mt-4 flex items-center gap-3">
          <button class="h-8 px-3 border border-neutral-300 rounded text-sm disabled:opacity-50" :disabled="testingKeys.has(usage.key)" @click="testUsage(usage.key)">
            {{ testingKeys.has(usage.key) ? '测试中' : '测试' }}
          </button>
          <span v-if="testResults[usage.key]" class="text-xs" :class="testResults[usage.key].ok ? 'text-green-700' : 'text-red-600'">
            {{ testResults[usage.key].message }}
          </span>
          <button
            v-if="usage.key === 'organize' || usage.key === 'analysis' || usage.key === 'review'"
            class="h-8 px-3 border border-neutral-300 rounded text-sm"
            @click="openStepSettings(usage)"
          >
            配置环节
          </button>
        </div>
      </section>
    </div>

    <div v-if="showStepSettings" class="fixed inset-0 z-30 bg-black/30 flex items-center justify-center p-4 sm:p-6">
      <div class="w-full max-w-[900px] max-h-[90dvh] overflow-y-auto bg-white rounded border border-neutral-200 p-4 sm:p-5">
        <div class="flex items-center justify-between">
          <div>
            <div class="text-lg font-medium text-neutral-900">{{ stepSettingUsage?.label }}环节配置</div>
            <div class="mt-1 text-sm text-neutral-500">模型和思考模式未指定时，继承{{ stepSettingUsage?.label }}阶段配置。</div>
          </div>
          <button class="h-8 px-3 border border-neutral-300 rounded text-sm" @click="showStepSettings = false">关闭</button>
        </div>

        <div class="mt-4 space-y-4">
          <section v-for="step in visibleStepSettings" :key="step.step_key" class="border border-neutral-200 rounded p-3">
            <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <div class="font-medium text-neutral-900">{{ step.step_label }}</div>
                <div v-if="step.step_key.startsWith('feedback_')" class="mt-1 text-xs text-neutral-500">仅反馈重分析时执行</div>
              </div>
              <label class="flex items-center gap-2 text-sm text-neutral-700">
                <input v-model="step.override_model" type="checkbox" class="h-4 w-4" @change="handleStepOverrideChange(step)">
                指定模型
              </label>
            </div>

            <div v-if="step.override_model" class="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-3">
              <select v-model="step.channel_id" class="w-full h-10 px-2 border border-neutral-300 rounded text-base sm:text-sm" @change="handleStepChannelChange(step)">
                <option value="">选择渠道</option>
                <option v-for="channel in channels" :key="channel.id" :value="channel.id">{{ channel.name }}</option>
              </select>

              <select v-model="step.ability_category" class="w-full h-10 px-2 border border-neutral-300 rounded text-base sm:text-sm" @change="clearStepAfterCategory(step)">
                <option value="">选择分类</option>
                <option v-for="category in categoriesForStep(step)" :key="category" :value="category">{{ category }}</option>
              </select>

              <div class="relative">
                <input
                  v-model="step.model_keyword"
                  class="w-full h-10 px-3 border border-neutral-300 rounded text-base sm:text-sm"
                  placeholder="输入并选择模型"
                  @focus="openStepModelPicker(step)"
                  @input="handleStepModelKeywordInput(step)"
                  @blur="closeStepModelPicker(step)"
                >
                <div
                  v-if="openModelPicker === `step:${step.step_key}`"
                  class="absolute z-40 mt-1 max-h-64 w-full overflow-y-auto bg-white border border-neutral-200 rounded shadow-sm"
                >
                  <button
                    v-for="item in modelsForStep(step)"
                    :key="item.id"
                    type="button"
                    class="block w-full px-3 py-2 text-left text-sm hover:bg-neutral-50"
                    @mousedown.prevent="selectStepModel(step, item)"
                  >
                    <span class="block font-medium text-neutral-900">{{ item.model.model_name }}</span>
                    <span class="block mt-0.5 text-xs text-neutral-500">{{ item.model.ability_tier }} / {{ item.model.score_label || item.model.score || '-' }}</span>
                  </button>
                  <div v-if="modelsForStep(step).length === 0" class="px-3 py-2 text-sm text-neutral-400">无匹配模型</div>
                </div>
              </div>
            </div>

            <label class="mt-3 block">
              <span class="block mb-1 text-sm text-neutral-700">思考模式</span>
              <select v-model="step.thinking_value" class="w-full h-10 px-2 border border-neutral-300 rounded text-base sm:text-sm sm:max-w-xs">
                <option value="inherit">继承阶段配置</option>
                <option value="true">开启</option>
                <option value="false">关闭</option>
              </select>
            </label>
          </section>
        </div>

        <div class="mt-5 flex justify-end">
          <button class="h-9 px-4 bg-neutral-900 text-white rounded text-sm" @click="showStepSettings = false">完成</button>
        </div>
      </div>
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
  { key: 'review', label: '回顾', modelType: 'language' },
  { key: 'chat', label: '对话', modelType: 'language' },
  { key: 'transcription', label: '语音转文字', modelType: 'asr' },
  { key: 'embedding', label: '向量化', modelType: 'embedding' },
]

const channels = ref<any[]>([])
const channelModels = ref<any[]>([])
const savedSettings = ref<any>({ settings: {}, steps: [] })
const message = ref('')
const openModelPicker = ref('')
const batchTesting = ref(false)
const draft = reactive<any>({})
const testResults = reactive<Record<string, { ok: boolean, message: string }>>({})
const testingKeys = ref(new Set<string>())
const organizeSettings = reactive<any>({ clean_check_enabled: false, content_check_enabled: false })
const savingOrganizeSettings = ref(false)
const organizeSettingsMessage = ref('')
const stepSettings = ref<any[]>([])
const showStepSettings = ref(false)
const stepSettingUsage = ref<any>(null)

for (const usage of usages) {
  draft[usage.key] = {
    channel_id: '',
    ability_category: '',
    channel_model_id: '',
    model_keyword: '',
    thinking_enabled: false,
  }
}

const loadData = async () => {
  channels.value = await api('/admin/channels')
  const rows = await Promise.all(channels.value.map(channel => api<any[]>(`/admin/channels/${channel.id}/models`)))
  channelModels.value = rows.flat().filter(item => item.enabled && item.model?.enabled && item.channel?.enabled)
  savedSettings.value = await api('/admin/model-settings')
  const pipelineSettings: any = await api('/admin/organize-settings')
  organizeSettings.clean_check_enabled = pipelineSettings.clean_check_enabled
  organizeSettings.content_check_enabled = pipelineSettings.content_check_enabled
  for (const setting of Object.values(savedSettings.value.settings || {}) as any[]) {
    const cm = setting.channel_model
    if (!cm) continue
    draft[setting.setting_key] = {
      channel_id: cm.channel_id,
      ability_category: cm.model.ability_category,
      channel_model_id: cm.id,
      model_keyword: modelOptionLabel(cm),
      thinking_enabled: Boolean(setting.thinking_enabled),
    }
  }
  stepSettings.value = (savedSettings.value.steps || []).map(toStepDraft)
}

const saveOrganizeSettings = async () => {
  savingOrganizeSettings.value = true
  organizeSettingsMessage.value = ''
  try {
    await api('/admin/organize-settings', {
      method: 'PUT',
      body: { ...organizeSettings },
    })
    organizeSettingsMessage.value = '已保存并立即生效'
  } catch (err: any) {
    organizeSettingsMessage.value = err?.data?.detail || '保存失败'
  } finally {
    savingOrganizeSettings.value = false
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
  const setting = savedSettings.value.settings?.[key]
  return setting?.unavailable_reason || ''
}

const saveSettings = async () => {
  message.value = ''
  const body: Record<string, any> = {}
  for (const usage of usages) {
    if (draft[usage.key].channel_model_id) {
      body[usage.key] = {
        channel_model_id: draft[usage.key].channel_model_id,
        thinking_enabled: ['transcription', 'embedding'].includes(usage.key) ? null : draft[usage.key].thinking_enabled,
      }
    }
  }
  if (Object.keys(body).length === 0) {
    message.value = '未选择任何模型'
    return
  }
  try {
    const steps = stepSettings.value.map(step => ({
      step_key: step.step_key,
      channel_model_id: step.override_model ? (step.channel_model_id || null) : null,
      thinking_enabled: step.thinking_value === 'inherit' ? null : step.thinking_value === 'true',
    }))
    savedSettings.value = await api('/admin/model-settings', { method: 'PUT', body: { settings: body, steps } })
    stepSettings.value = (savedSettings.value.steps || []).map(toStepDraft)
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
        thinking_enabled: ['transcription', 'embedding'].includes(key) ? null : draft[key].thinking_enabled,
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
      const thinkingEnabled = ['transcription', 'embedding'].includes(usage.key) ? 'none' : String(draft[usage.key].thinking_enabled)
      const groupKey = `${channelModelId}:${thinkingEnabled}`
      groups.set(groupKey, [...(groups.get(groupKey) || []), usage])
    }
    for (const group of groups.values()) {
      const usage = group[0]
      try {
        const result: any = await api('/admin/model-settings/test', {
          method: 'POST',
          body: {
            setting_key: usage.key,
            channel_model_id: draft[usage.key].channel_model_id,
            thinking_enabled: ['transcription', 'embedding'].includes(usage.key) ? null : draft[usage.key].thinking_enabled,
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

const toStepDraft = (step: any) => {
  const cm = step.channel_model
  return {
    ...step,
    override_model: Boolean(step.channel_model_id),
    channel_id: cm?.channel_id || '',
    ability_category: cm?.model?.ability_category || '',
    channel_model_id: step.channel_model_id || '',
    model_keyword: cm ? modelOptionLabel(cm) : '',
    thinking_value: step.thinking_enabled === null ? 'inherit' : String(step.thinking_enabled),
  }
}

const visibleStepSettings = computed(() =>
  stepSettings.value.filter(step => step.setting_key === stepSettingUsage.value?.key)
)

const openStepSettings = (usage: any) => {
  stepSettingUsage.value = usage
  showStepSettings.value = true
}

const handleStepOverrideChange = (step: any) => {
  if (step.override_model) return
  step.channel_id = ''
  step.ability_category = ''
  step.channel_model_id = ''
  step.model_keyword = ''
  openModelPicker.value = ''
}

const candidatesForStep = (step: any) => channelModels.value.filter(item =>
  item.channel_id === step.channel_id &&
  item.model?.model_type === 'language'
)

const categoriesForStep = (step: any) =>
  Array.from(new Set(candidatesForStep(step).map(item => item.model.ability_category)))

const modelsForStep = (step: any) => {
  const keyword = String(step.model_keyword || '').trim().toLowerCase()
  return candidatesForStep(step)
    .filter(item => !step.ability_category || item.model.ability_category === step.ability_category)
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

const handleStepChannelChange = (step: any) => {
  step.ability_category = ''
  step.channel_model_id = ''
  step.model_keyword = ''
}

const clearStepAfterCategory = (step: any) => {
  step.channel_model_id = ''
  step.model_keyword = ''
}

const openStepModelPicker = (step: any) => {
  openModelPicker.value = `step:${step.step_key}`
  if (step.channel_model_id) step.model_keyword = ''
}

const handleStepModelKeywordInput = (step: any) => {
  step.channel_model_id = ''
  openModelPicker.value = `step:${step.step_key}`
}

const selectStepModel = (step: any, item: any) => {
  step.channel_model_id = item.id
  step.model_keyword = modelOptionLabel(item)
  openModelPicker.value = ''
}

const closeStepModelPicker = (step: any) => {
  window.setTimeout(() => {
    if (openModelPicker.value === `step:${step.step_key}`) openModelPicker.value = ''
    const selected = channelModels.value.find(item => item.id === step.channel_model_id)
    if (selected && !step.model_keyword) step.model_keyword = modelOptionLabel(selected)
  }, 120)
}

onMounted(loadData)
</script>
