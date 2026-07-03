/** @type {import('tailwindcss').Config} */
export default {
  // 手机优先设计：默认断点以移动端为基准
  content: [
    './components/**/*.{vue,js,ts}',
    './layouts/**/*.vue',
    './pages/**/*.vue',
    './composables/**/*.{js,ts}',
    './app.vue',
    './nuxt.config.{js,ts}'
  ],
  theme: {
    // 移动端优先的响应式断点
    screens: {
      sm: '640px',   // 大屏手机
      md: '768px',   // 平板
      lg: '1024px',  // 小屏笔记本
      xl: '1280px',  // 桌面
    },
    extend: {
      colors: {
        // 主色调 - 温暖的日记风格
        primary: {
          50: '#fdf8f3',
          100: '#fbeede',
          200: '#f6d9b8',
          300: '#efbc88',
          400: '#e8995f',
          500: '#e07a3c',
          600: '#cc6230',
          700: '#a84d28',
          800: '#853e27',
          900: '#6b3522',
        },
        // 中性灰
        neutral: {
          50: '#f9fafb',
          100: '#f3f4f6',
          200: '#e5e7eb',
          300: '#d1d5db',
          400: '#9ca3af',
          500: '#6b7280',
          600: '#4b5563',
          700: '#374151',
          800: '#1f2937',
          900: '#111827',
        }
      },
      spacing: {
        // 底部 Tab 栏高度
        'tab': '52px',
        // 顶部导航栏高度
        'nav': '44px',
      }
    },
  },
  plugins: [],
}
