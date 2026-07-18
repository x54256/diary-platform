<template>
  <div class="space-y-5">
    <div class="flex items-start justify-between">
      <div>
        <h1 class="text-2xl font-semibold text-neutral-900">模型管理</h1>
        <p class="mt-1 text-sm text-neutral-500">维护模型能力清单，模型不保存 API 密钥。</p>
      </div>
      <button class="h-9 px-4 bg-neutral-900 text-white text-sm rounded" @click="openCreate">
        新增模型
      </button>
    </div>

    <section class="bg-white border border-neutral-200 rounded p-4">
      <div class="grid grid-cols-6 gap-3">
        <select v-model="filters.model_type" class="h-9 px-2 border border-neutral-300 rounded text-sm" @change="reloadModels">
          <option value="">全部类型</option>
          <option value="language">language</option>
          <option value="asr">asr</option>
        </select>
        <select v-model="filters.ability_tier" class="h-9 px-2 border border-neutral-300 rounded text-sm" @change="reloadModels">
          <option value="">全部梯队</option>
          <option v-for="item in tiers" :key="item" :value="item">{{ item }}</option>
        </select>
        <select v-model="filters.ability_category" class="h-9 px-2 border border-neutral-300 rounded text-sm" @change="reloadModels">
          <option value="">全部分类</option>
          <option v-for="item in categories" :key="item" :value="item">{{ item }}</option>
        </select>
        <select v-model="filters.enabled" class="h-9 px-2 border border-neutral-300 rounded text-sm" @change="reloadModels">
          <option value="">全部状态</option>
          <option value="true">启用</option>
          <option value="false">禁用</option>
        </select>
        <input v-model="filters.keyword" class="col-span-2 h-9 px-3 border border-neutral-300 rounded text-sm" placeholder="搜索模型、厂商、特点" @keyup.enter="reloadModels">
      </div>
    </section>

    <section class="bg-white border border-neutral-200 rounded overflow-hidden">
      <table class="w-full text-sm">
        <thead class="bg-neutral-50 text-neutral-500">
          <tr>
            <th class="text-left p-3">状态</th>
            <th class="text-left p-3">类型</th>
            <th class="text-left p-3">梯队</th>
            <th class="text-left p-3">分类</th>
            <th class="text-left p-3">模型</th>
            <th class="text-left p-3">核心特点</th>
            <th class="text-right p-3">分数</th>
            <th class="text-right p-3">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="model in models" :key="model.id" class="border-t border-neutral-100">
            <td class="p-3">
              <span :class="model.enabled ? 'text-green-700' : 'text-neutral-400'">{{ model.enabled ? 'ON' : 'OFF' }}</span>
            </td>
            <td class="p-3">{{ model.model_type }}</td>
            <td class="p-3">{{ model.ability_tier }}</td>
            <td class="p-3">{{ model.ability_category }}</td>
            <td class="p-3 font-medium text-neutral-900">{{ model.model_name }}</td>
            <td class="p-3 max-w-md text-neutral-600">
              <div class="line-clamp-2">{{ model.core_features || '-' }}</div>
            </td>
            <td class="p-3 text-right">{{ model.score_label || model.score || '-' }}</td>
            <td class="p-3 text-right space-x-3">
              <button class="text-neutral-900 underline" @click="editModel(model)">编辑</button>
              <button class="text-neutral-700" @click="toggleModel(model)">{{ model.enabled ? '禁用' : '启用' }}</button>
              <button class="text-red-600" @click="deleteModel(model)">删除</button>
            </td>
          </tr>
        </tbody>
      </table>
      <div class="px-4 py-3 border-t border-neutral-100 flex items-center justify-between text-sm">
        <div class="text-neutral-500">共 {{ total }} 条，第 {{ page }} / {{ totalPages }} 页</div>
        <div class="flex items-center gap-2">
          <select v-model.number="pageSize" class="h-8 px-2 border border-neutral-300 rounded" @change="reloadModels">
            <option :value="10">10 条/页</option>
            <option :value="20">20 条/页</option>
            <option :value="50">50 条/页</option>
          </select>
          <button class="h-8 px-3 border border-neutral-300 rounded disabled:opacity-50" :disabled="page <= 1" @click="changePage(page - 1)">上一页</button>
          <button class="h-8 px-3 border border-neutral-300 rounded disabled:opacity-50" :disabled="page >= totalPages" @click="changePage(page + 1)">下一页</button>
        </div>
      </div>
    </section>

    <div v-if="showForm" class="fixed inset-0 bg-black/30 flex items-center justify-center p-6">
      <div class="w-[640px] bg-white rounded border border-neutral-200 p-5">
        <div class="text-lg font-medium text-neutral-900">{{ editingId ? '编辑模型' : '新增模型' }}</div>
        <div class="mt-4 grid grid-cols-2 gap-3">
          <label class="block">
            <span class="block mb-1 text-sm text-neutral-700">模型类型</span>
            <select v-model="form.model_type" class="w-full h-10 px-3 border border-neutral-300 rounded text-sm" :disabled="!!editingId">
              <option value="language">language</option>
              <option value="asr">asr</option>
            </select>
          </label>
          <label class="block">
            <span class="block mb-1 text-sm text-neutral-700">厂商</span>
            <input v-model="form.provider_name" class="w-full h-10 px-3 border border-neutral-300 rounded text-sm" placeholder="厂商">
          </label>
          <label class="block">
            <span class="block mb-1 text-sm text-neutral-700">模型名称</span>
            <input v-model="form.model_name" class="w-full h-10 px-3 border border-neutral-300 rounded text-sm" placeholder="模型名称">
          </label>
          <label class="block">
            <span class="block mb-1 text-sm text-neutral-700">能力梯队</span>
            <select v-model="form.ability_tier" class="w-full h-10 px-3 border border-neutral-300 rounded text-sm">
              <option v-for="item in tierOptions" :key="item" :value="item">{{ item }}</option>
            </select>
          </label>
          <label class="block">
            <span class="block mb-1 text-sm text-neutral-700">能力分类</span>
            <select v-model="form.ability_category" class="w-full h-10 px-3 border border-neutral-300 rounded text-sm">
              <option v-for="item in formCategories" :key="item" :value="item">{{ item }}</option>
            </select>
          </label>
          <label class="block">
            <span class="block mb-1 text-sm text-neutral-700">分数</span>
            <input v-model.number="form.score" type="number" step="0.1" class="w-full h-10 px-3 border border-neutral-300 rounded text-sm" placeholder="分数">
          </label>
          <label class="block col-span-2">
            <span class="block mb-1 text-sm text-neutral-700">核心特点</span>
            <textarea v-model="form.core_features" class="w-full h-20 px-3 py-2 border border-neutral-300 rounded text-sm" placeholder="核心特点" />
          </label>
          <label class="block col-span-2">
            <span class="block mb-1 text-sm text-neutral-700">适用场景</span>
            <textarea v-model="form.scenarios" class="w-full h-20 px-3 py-2 border border-neutral-300 rounded text-sm" placeholder="适用场景" />
          </label>
        </div>
        <p v-if="error" class="mt-3 text-sm text-red-600">{{ error }}</p>
        <div class="mt-5 flex justify-end gap-3">
          <button class="h-9 px-4 border border-neutral-300 rounded text-sm" @click="showForm = false">取消</button>
          <button class="h-9 px-4 bg-neutral-900 text-white rounded text-sm" @click="saveModel">保存</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
definePageMeta({ layout: 'admin', middleware: 'admin' })

const { api } = useApi()

const models = ref<any[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const options = ref<any>({})
const error = ref('')
const showForm = ref(false)
const editingId = ref('')
const filters = reactive({ model_type: '', ability_tier: '', ability_category: '', enabled: '', keyword: '' })
const form = reactive<any>({
  model_type: 'language',
  provider_name: '',
  model_name: '',
  ability_tier: 'T0 旗舰全能',
  ability_category: '通用对话',
  core_features: '',
  scenarios: '',
  score: null,
})

const tierOptions = ['T0 旗舰全能', 'T0.5 推理专项天花板', 'T1 次旗舰均衡', 'T1 专项顶级', 'T2 企业主力', 'T2 通用商用', 'T2.5 中端推理特化', 'T3 轻量通用', 'T3 轻量专项', 'T4 极速轻量']
const formCategories = computed(() => form.model_type === 'asr' ? (options.value.asr_categories || []) : (options.value.language_categories || []))
const categories = computed(() => [...(options.value.language_categories || []), ...(options.value.asr_categories || [])])
const tiers = computed(() => tierOptions)
const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)))

watch(() => form.model_type, () => {
  form.ability_category = form.model_type === 'asr' ? '录音文件识别' : '通用对话'
})

const loadOptions = async () => {
  options.value = await api('/admin/model-options')
}

const loadModels = async () => {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(filters)) {
    if (value) params.set(key, value)
  }
  params.set('page', String(page.value))
  params.set('page_size', String(pageSize.value))
  const result: any = await api(`/admin/models?${params.toString()}`)
  models.value = result.items
  total.value = result.total
}

const reloadModels = async () => {
  page.value = 1
  await loadModels()
}

const changePage = async (target: number) => {
  page.value = target
  await loadModels()
}

const openCreate = () => {
  editingId.value = ''
  error.value = ''
  Object.assign(form, { model_type: 'language', provider_name: '', model_name: '', ability_tier: 'T0 旗舰全能', ability_category: '通用对话', core_features: '', scenarios: '', score: null })
  showForm.value = true
}

const editModel = (model: any) => {
  editingId.value = model.id
  error.value = ''
  Object.assign(form, model)
  showForm.value = true
}

const saveModel = async () => {
  error.value = ''
  try {
    if (editingId.value) {
      await api(`/admin/models/${editingId.value}`, { method: 'PATCH', body: form })
    } else {
      await api('/admin/models', { method: 'POST', body: form })
    }
    showForm.value = false
    await loadModels()
  } catch (err: any) {
    error.value = err?.data?.detail || '保存失败'
  }
}

const toggleModel = async (model: any) => {
  try {
    await api(`/admin/models/${model.id}`, { method: 'PATCH', body: { enabled: !model.enabled } })
    await loadModels()
  } catch (err: any) {
    window.alert(err?.data?.detail || '操作失败')
  }
}

const deleteModel = async (model: any) => {
  if (!window.confirm(`确认删除模型 ${model.model_name}？`)) return
  try {
    await api(`/admin/models/${model.id}`, { method: 'DELETE' })
    await loadModels()
  } catch (err: any) {
    window.alert(err?.data?.detail || '删除失败')
  }
}

onMounted(async () => {
  await loadOptions()
  await loadModels()
})
</script>
