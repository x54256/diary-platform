<template>
  <div class="min-h-dvh">
    <header class="flex items-center gap-3 bg-white px-4 py-4 border-b border-neutral-100">
      <button type="button" class="text-2xl leading-none text-neutral-500" aria-label="返回" @click="navigateTo('/profile/person-relations')">‹</button>
      <h1 class="text-lg font-medium text-neutral-800">编辑人物</h1>
    </header>
    <section v-if="loading" class="bg-white px-4 py-8 text-center text-sm text-neutral-400">加载中…</section>
    <section v-else-if="person" class="bg-white px-4 py-4">
      <PersonRelationEditor :person="person" :pending="pending" @save="savePerson" @cancel="navigateTo('/profile/person-relations')" />
    </section>
    <p v-else class="px-4 py-6 text-sm text-red-500">人物关系不存在</p>
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
const person = ref<PersonRelation | null>(null)
const loading = ref(true)
const pending = ref(false)

try {
  const people = await api<PersonRelation[]>('/person-relations')
  person.value = people.find(item => item.id === String(route.params.id)) || null
} finally {
  loading.value = false
}

const savePerson = async (payload: { name: string; common_names: string[]; gender: PersonGender; relation: string }) => {
  pending.value = true
  try {
    await api(`/person-relations/${route.params.id}`, { method: 'PUT', body: payload })
    await navigateTo('/profile/person-relations')
  } finally {
    pending.value = false
  }
}
</script>
