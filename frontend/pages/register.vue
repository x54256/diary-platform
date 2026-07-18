<template>
  <div class="min-h-dvh flex items-center justify-center bg-neutral-50 px-6">
    <div class="w-full max-w-sm">
      <div class="text-center mb-8">
        <h1 class="text-2xl font-bold text-neutral-800">创建账号</h1>
        <p class="text-sm text-neutral-500 mt-2">开始记录生活，认知自我</p>
      </div>

      <form class="space-y-4" @submit.prevent="handleRegister">
        <div>
          <label class="block text-sm text-neutral-600 mb-1">用户名</label>
          <input
            v-model.trim="form.username"
            type="text"
            maxlength="50"
            autocomplete="username"
            placeholder="请输入用户名"
            class="w-full px-4 py-3 rounded-lg border border-neutral-300 bg-white text-neutral-800 placeholder-neutral-400 focus:border-primary-500"
          />
        </div>

        <div>
          <label class="block text-sm text-neutral-600 mb-1">密码</label>
          <input
            v-model="form.password"
            type="password"
            minlength="6"
            autocomplete="new-password"
            placeholder="至少 6 位"
            class="w-full px-4 py-3 rounded-lg border border-neutral-300 bg-white text-neutral-800 placeholder-neutral-400 focus:border-primary-500"
          />
        </div>

        <div>
          <label class="block text-sm text-neutral-600 mb-1">确认密码</label>
          <input
            v-model="form.confirmPassword"
            type="password"
            minlength="6"
            autocomplete="new-password"
            placeholder="请再次输入密码"
            class="w-full px-4 py-3 rounded-lg border border-neutral-300 bg-white text-neutral-800 placeholder-neutral-400 focus:border-primary-500"
          />
        </div>

        <button
          type="submit"
          :disabled="loading"
          class="w-full py-3 rounded-lg bg-primary-600 text-white font-medium hover:bg-primary-700 disabled:opacity-50 transition-colors"
        >
          {{ loading ? '注册中...' : '注册并登录' }}
        </button>

        <p v-if="errorMsg" class="text-sm text-red-500 text-center">{{ errorMsg }}</p>
      </form>

      <p class="mt-6 text-center text-sm text-neutral-500">
        已有账号？
        <NuxtLink to="/login" class="text-primary-600 hover:text-primary-700">去登录</NuxtLink>
      </p>
    </div>
  </div>
</template>

<script setup lang="ts">
definePageMeta({
  layout: 'auth',
})

const { register } = useAuth()
const router = useRouter()

const form = reactive({
  username: '',
  password: '',
  confirmPassword: '',
})
const loading = ref(false)
const errorMsg = ref('')

const handleRegister = async () => {
  if (!form.username) {
    errorMsg.value = '请输入用户名'
    return
  }
  if (form.password.length < 6) {
    errorMsg.value = '密码至少 6 位'
    return
  }
  if (form.password !== form.confirmPassword) {
    errorMsg.value = '两次输入的密码不一致'
    return
  }

  errorMsg.value = ''
  loading.value = true
  try {
    await register(form.username, form.password)
    await router.push('/')
  } catch (err: any) {
    errorMsg.value = err?.message || '注册失败，请稍后重试'
  } finally {
    loading.value = false
  }
}
</script>
