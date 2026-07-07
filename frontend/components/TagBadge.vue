<template>
  <span
    class="inline-block px-2 py-0.5 rounded-full text-xs font-medium mr-1 mb-1"
    :class="tagColorClass"
  >
    {{ tag.name }}
  </span>
</template>

<script setup lang="ts">
// 标签徽章组件：按标签类型着色

const props = defineProps<{
  tag: Tag
}>()

const TAG_COLORS: Record<string, string> = {
  domain: 'bg-blue-100 text-blue-800',
  topic: 'bg-green-100 text-green-800',
  person_object: 'bg-orange-100 text-orange-800',
  psychological: 'bg-purple-100 text-purple-800',
  knowledge: 'bg-teal-100 text-teal-800',
}

const tagColorClass = computed(() => {
  return TAG_COLORS[props.tag.type || ''] || 'bg-neutral-100 text-neutral-800'
})
</script>
