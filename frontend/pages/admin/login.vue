<template>
  <div class="min-h-dvh bg-neutral-100 flex items-center justify-center px-4">
    <div class="w-full max-w-sm bg-white border border-neutral-200 rounded p-8">
      <div class="mb-6">
        <div class="text-xl font-semibold text-neutral-900">管理端登录</div>
        <div class="mt-1 text-sm text-neutral-500">仅 admin 账号可进入系统备份与恢复。</div>
      </div>

      <form class="space-y-4" @submit.prevent="handleLogin">
        <div>
          <label class="block text-sm text-neutral-700 mb-1">用户名</label>
          <input
            v-model="username"
            class="w-full h-10 px-3 border border-neutral-300 rounded text-sm outline-none focus:border-neutral-900"
            autocomplete="username"
          >
        </div>
        <div>
          <label class="block text-sm text-neutral-700 mb-1">密码</label>
          <input
            v-model="password"
            type="password"
            class="w-full h-10 px-3 border border-neutral-300 rounded text-sm outline-none focus:border-neutral-900"
            autocomplete="current-password"
          >
        </div>
        <div v-if="error" class="text-sm text-red-500">{{ error }}</div>
        <button
          type="submit"
          class="w-full h-10 bg-neutral-900 text-white text-sm rounded disabled:opacity-60"
          :disabled="loading"
        >
          {{ loading ? '登录中...' : '登录管理端' }}
        </button>
      </form>
    </div>
  </div>
</template>

<script setup lang="ts">
definePageMeta({
  layout: false,
})

const route = useRoute()
const router = useRouter()
const { login, user } = useAuth()

const username = ref('')
const password = ref('')
const loading = ref(false)
const error = ref('')

const handleLogin = async () => {
  error.value = ''
  loading.value = true
  try {
    await login(username.value, password.value)
    if (user.value?.username !== 'admin') {
      error.value = '当前账号不是超级管理员'
      return
    }
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/admin/backup-restore'
    router.push(redirect)
  } catch (err: any) {
    error.value = err.message || '登录失败'
  } finally {
    loading.value = false
  }
}
</script>
