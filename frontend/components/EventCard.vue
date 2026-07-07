<template>
  <div class="border border-neutral-200 rounded-lg mb-3 overflow-hidden">
    <!-- 标题区（点击切换展开/收起） -->
    <button
      class="w-full text-left px-4 py-3 flex items-start gap-2 hover:bg-neutral-50 transition-colors"
      @click="expanded = !expanded"
    >
      <span class="text-neutral-400 text-sm mt-0.5 shrink-0">{{ expanded ? '▼' : '▶' }}</span>
      <div class="flex-1 min-w-0">
        <div class="text-sm font-medium text-neutral-800">
          {{ event.event_title || '未命名事件' }}
        </div>
        <!-- 事件级标签 -->
        <div v-if="event.tags && event.tags.length > 0" class="mt-1 flex flex-wrap">
          <TagBadge v-for="tag in event.tags" :key="tag.id" :tag="tag" />
        </div>
      </div>
    </button>

    <!-- 展开内容 -->
    <div v-if="expanded" class="px-4 pb-4 border-t border-neutral-100">
      <!-- 事件正文 -->
      <div v-if="event.body && event.body.length > 0" class="mt-3 space-y-3">
        <p
          v-for="(para, idx) in event.body"
          :key="idx"
          class="text-sm text-neutral-700 leading-relaxed"
        >
          {{ para }}
        </p>
      </div>

      <!-- 感受 -->
      <div v-if="event.feeling && event.feeling.length > 0" class="mt-4">
        <div class="text-xs font-medium text-neutral-500 mb-2">感受</div>
        <div class="space-y-2">
          <p
            v-for="(item, idx) in event.feeling"
            :key="idx"
            class="text-sm text-neutral-600 leading-relaxed"
          >
            {{ item }}
          </p>
        </div>
      </div>

      <!-- 反思与成长 -->
      <div v-if="event.reflection && event.reflection.length > 0" class="mt-4">
        <div class="text-xs font-medium text-neutral-500 mb-2">反思与成长</div>
        <div class="space-y-2">
          <p
            v-for="(item, idx) in event.reflection"
            :key="idx"
            class="text-sm text-neutral-600 leading-relaxed"
          >
            {{ item }}
          </p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
// 事件卡片组件：折叠式设计，默认收起

defineProps<{
  event: DiaryEvent
}>()

const expanded = ref(false)
</script>
