<template>
  <NuxtPage v-if="route.path !== '/profile/person-relations'" />

  <div v-else class="min-h-dvh">
    <header class="flex items-center justify-between gap-3 bg-white px-4 py-4 border-b border-neutral-100">
      <div class="flex items-center gap-3">
        <button type="button" class="text-2xl leading-none text-neutral-500" aria-label="返回" @click="navigateTo('/profile')">‹</button>
        <h1 class="text-lg font-medium text-neutral-800">用户关系管理</h1>
      </div>
      <button type="button" class="text-sm text-primary-600" @click="navigateTo('/profile/person-relations/new')">添加人物</button>
    </header>

    <p v-if="errorMessage" class="px-4 pt-4 text-sm text-red-500">{{ errorMessage }}</p>

    <section class="mt-3 bg-white">
      <div class="border-b border-neutral-100 px-4 py-3 text-sm font-medium text-neutral-700">人物列表</div>
      <div v-if="loading" class="px-4 py-8 text-center text-sm text-neutral-400">加载中…</div>
      <div v-else-if="!people.length" class="px-4 py-8 text-center text-sm text-neutral-400">还没有添加人物</div>
      <div v-else>
        <article v-for="person in people" :key="person.id" class="border-b border-neutral-100 px-4 py-4 last:border-b-0">
          <div class="flex items-start justify-between gap-3">
            <div class="min-w-0">
              <h2 class="break-all text-base font-medium text-neutral-800">{{ person.name }}</h2>
              <p v-if="person.common_names.length" class="mt-1 break-all text-sm text-neutral-500">常用名：{{ person.common_names.join('、') }}</p>
              <p class="mt-1 text-sm text-neutral-500">性别：{{ genderLabel(person.gender) }}　关系：{{ person.relation }}</p>
            </div>
            <button type="button" class="shrink-0 text-sm text-primary-600" @click="navigateTo(`/profile/person-relations/${person.id}`)">编辑</button>
          </div>
        </article>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import type { PersonGender, PersonRelation } from '~/types'

definePageMeta({
  layout: 'default',
  middleware: 'auth',
})

const route = useRoute()
const { api } = useApi()
const people = ref<PersonRelation[]>([])
const loading = ref(true)
const errorMessage = ref('')

const genderOptions: Array<{ value: PersonGender; label: string }> = [
  { value: 'male', label: '男' },
  { value: 'female', label: '女' },
  { value: 'unknown', label: '未知' },
]

const genderLabel = (gender: PersonGender) => genderOptions.find(option => option.value === gender)?.label || '未知'

try {
  people.value = await api<PersonRelation[]>('/person-relations')
} catch (error: any) {
  errorMessage.value = error?.data?.detail || '人物关系加载失败'
} finally {
  loading.value = false
}
</script>
