<template>
  <div class="min-h-dvh flex items-center justify-center bg-neutral-50 px-6">
    <div class="w-full max-w-sm">
      <!-- 标题 -->
      <div class="text-center mb-8">
        <h1 class="text-2xl font-bold text-neutral-800">日记平台</h1>
        <p class="text-sm text-neutral-500 mt-2">记录生活，认知自我</p>
      </div>

      <!-- 登录表单 -->
      <form @submit.prevent="handleLogin" class="space-y-4">
        <!-- 用户名 -->
        <div>
          <label class="block text-sm text-neutral-600 mb-1">用户名</label>
          <input
            v-model="form.username"
            type="text"
            placeholder="请输入用户名"
            class="w-full px-4 py-3 rounded-lg border border-neutral-300 bg-white text-neutral-800 placeholder-neutral-400 focus:border-primary-500"
          />
        </div>

        <!-- 密码 -->
        <div>
          <label class="block text-sm text-neutral-600 mb-1">密码</label>
          <input
            v-model="form.password"
            type="password"
            placeholder="请输入密码"
            class="w-full px-4 py-3 rounded-lg border border-neutral-300 bg-white text-neutral-800 placeholder-neutral-400 focus:border-primary-500"
          />
        </div>

        <!-- 记住密码 -->
        <div class="flex items-center">
          <input
            v-model="form.remember"
            type="checkbox"
            id="remember"
            class="w-4 h-4 rounded border-neutral-300 text-primary-600"
          />
          <label for="remember" class="ml-2 text-sm text-neutral-600">记住密码</label>
        </div>

        <!-- 登录按钮 -->
        <button
          type="submit"
          :disabled="loading"
          class="w-full py-3 rounded-lg bg-primary-600 text-white font-medium hover:bg-primary-700 disabled:opacity-50 transition-colors"
        >
          {{ loading ? '登录中...' : '登录' }}
        </button>

        <!-- 错误提示 -->
        <p v-if="errorMsg" class="text-sm text-red-500 text-center">{{ errorMsg }}</p>
      </form>

      <!-- 默认账号提示 -->
      <div class="mt-6 p-3 rounded-lg bg-neutral-100 text-center space-y-1">
        <p class="text-xs text-neutral-400">默认账号：admin</p>
        <p class="text-xs text-neutral-400">默认密码：admin123</p>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
// 登录页：使用 auth 布局（无 Tab 栏）
definePageMeta({
  layout: 'auth',
})

const { login } = useAuth()
const router = useRouter()

// 表单数据
const form = reactive({
  username: 'admin',
  password: 'admin123',
  remember: false,
})

// 加载状态
const loading = ref(false)

// 错误提示
const errorMsg = ref('')

// 处理登录
const handleLogin = async () => {
  if (!form.username || !form.password) return

  errorMsg.value = ''
  loading.value = true
  try {
    await login(form.username, form.password)
    router.push('/')
  } catch (err: any) {
    errorMsg.value = err?.message || '登录失败，请稍后重试'
  } finally {
    loading.value = false
  }
}
</script>
