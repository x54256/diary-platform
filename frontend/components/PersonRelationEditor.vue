<template>
  <form class="space-y-4" @submit.prevent="submitForm">
    <label class="block">
      <span class="mb-1 block text-sm text-neutral-600">姓名</span>
      <input v-model="form.name" type="text" maxlength="100" required class="w-full rounded-lg border border-neutral-200 px-3 py-2.5 text-base" placeholder="请输入姓名">
    </label>

    <div>
      <span class="mb-1 block text-sm text-neutral-600">常用名</span>
      <div class="flex gap-2">
        <input v-model="commonNameDraft" type="text" maxlength="100" class="min-w-0 flex-1 rounded-lg border border-neutral-200 px-3 py-2.5 text-base" placeholder="输入后添加" @keyup.enter.prevent="addCommonName">
        <button type="button" class="shrink-0 rounded-lg border border-neutral-200 px-4 py-2.5 text-sm text-neutral-700" @click="addCommonName">添加</button>
      </div>
      <div v-if="form.common_names.length" class="mt-2 flex flex-wrap gap-2">
        <span v-for="name in form.common_names" :key="name" class="inline-flex items-center gap-1 rounded-full bg-primary-50 px-3 py-1 text-sm text-primary-700">
          {{ name }}
          <button type="button" class="text-primary-500" :aria-label="`删除常用名${name}`" @click="removeCommonName(name)">×</button>
        </span>
      </div>
    </div>

    <fieldset>
      <legend class="mb-1 block text-sm text-neutral-600">性别</legend>
      <div class="grid grid-cols-3 gap-2">
        <button v-for="option in genderOptions" :key="option.value" type="button" class="rounded-lg border px-3 py-2.5 text-sm" :class="form.gender === option.value ? 'border-primary-500 bg-primary-50 text-primary-700' : 'border-neutral-200 text-neutral-600'" @click="form.gender = option.value">{{ option.label }}</button>
      </div>
    </fieldset>

    <label class="block">
      <span class="mb-1 block text-sm text-neutral-600">与用户关系</span>
      <input v-model="form.relation" type="text" maxlength="100" required class="w-full rounded-lg border border-neutral-200 px-3 py-2.5 text-base" placeholder="例如：朋友、同事、家人">
    </label>

    <p v-if="errorMessage" class="text-sm text-red-500">{{ errorMessage }}</p>
    <div class="flex gap-3 pt-1">
      <button type="button" class="flex-1 rounded-lg border border-neutral-200 px-4 py-2.5 text-sm text-neutral-700" @click="$emit('cancel')">取消</button>
      <button type="submit" class="flex-1 rounded-lg bg-primary-500 px-4 py-2.5 text-sm text-white disabled:opacity-50" :disabled="pending">保存</button>
    </div>
  </form>
</template>

<script setup lang="ts">
import type { PersonGender, PersonRelation } from '~/types'

const props = defineProps<{ person?: PersonRelation | null; pending?: boolean }>()
const emit = defineEmits<{ save: [payload: { name: string; common_names: string[]; gender: PersonGender; relation: string }]; cancel: [] }>()

const form = reactive({
  name: props.person?.name || '',
  common_names: [...(props.person?.common_names || [])],
  gender: props.person?.gender || 'unknown' as PersonGender,
  relation: props.person?.relation || '',
})
const commonNameDraft = ref('')
const errorMessage = ref('')
const genderOptions: Array<{ value: PersonGender; label: string }> = [
  { value: 'male', label: '男' },
  { value: 'female', label: '女' },
  { value: 'unknown', label: '未知' },
]

const addCommonName = () => {
  const value = commonNameDraft.value.trim()
  if (!value) return
  if (value.toLowerCase() === form.name.trim().toLowerCase()) {
    errorMessage.value = '常用名不能与姓名相同'
    return
  }
  if (!form.common_names.some(name => name.toLowerCase() === value.toLowerCase())) {
    form.common_names.push(value)
  }
  commonNameDraft.value = ''
  errorMessage.value = ''
}

const removeCommonName = (name: string) => {
  form.common_names = form.common_names.filter(value => value !== name)
}

const submitForm = () => {
  if (!form.name.trim() || !form.relation.trim()) return
  emit('save', {
    name: form.name.trim(),
    common_names: form.common_names,
    gender: form.gender,
    relation: form.relation.trim(),
  })
}
</script>
