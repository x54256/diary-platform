<template>
  <header class="sticky top-0 z-40 border-b border-[#e8e1d5] bg-[#fffdf8]/95 backdrop-blur">
    <div class="mx-auto grid min-h-14 w-full max-w-7xl grid-cols-[2.75rem_minmax(0,1fr)_auto] items-center gap-3 px-4 sm:px-6 lg:px-8">
      <button
        v-if="showBack"
        type="button"
        class="flex h-11 w-11 items-center justify-center rounded-full text-xl text-neutral-700 transition hover:bg-primary-50 focus-visible:bg-primary-50"
        aria-label="返回"
        @click="router.back()"
      >
        ←
      </button>
      <span v-else aria-hidden="true" />
      <div class="min-w-0">
        <p v-if="eyebrow" class="text-[11px] font-semibold tracking-[0.16em] text-primary-700">{{ eyebrow }}</p>
        <h1 class="truncate text-base font-semibold tracking-tight text-[#26322b] sm:text-lg">{{ title }}</h1>
      </div>
      <div class="flex items-center justify-end gap-2"><slot name="right" /></div>
    </div>
  </header>
</template>

<script setup lang="ts">
withDefaults(defineProps<{
  title: string
  eyebrow?: string
  showBack?: boolean
}>(), { eyebrow: '', showBack: false })

const router = useRouter()
</script>
