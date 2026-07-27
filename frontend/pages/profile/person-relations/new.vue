<template>
  <div class="min-h-dvh">
    <header class="flex items-center gap-3 bg-white px-4 py-4 border-b border-neutral-100">
      <button type="button" class="text-2xl leading-none text-neutral-500" aria-label="返回" @click="navigateTo('/profile/person-relations')">‹</button>
      <h1 class="text-lg font-medium text-neutral-800">添加人物</h1>
    </header>
    <section class="bg-white px-4 py-4">
      <PersonRelationEditor :pending="pending" @save="savePerson" @cancel="navigateTo('/profile/person-relations')" />
    </section>
  </div>
</template>

<script setup lang="ts">
import type { PersonGender } from '~/types'

definePageMeta({
  layout: 'default',
  middleware: 'auth',
})

const { api } = useApi()
const pending = ref(false)

const savePerson = async (payload: { name: string; common_names: string[]; gender: PersonGender; relation: string }) => {
  pending.value = true
  try {
    await api('/person-relations', { method: 'POST', body: payload })
    await navigateTo('/profile/person-relations')
  } catch (error: any) {
    // 表单组件负责显示校验错误；接口错误通过页面提示暂时保留在控制台，避免列表页和表单页混杂。
    console.error(error?.data?.detail || '人物关系保存失败')
  } finally {
    pending.value = false
  }
}
</script>
