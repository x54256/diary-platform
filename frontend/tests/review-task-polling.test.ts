import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const tasksPage = resolve(dirname(fileURLToPath(import.meta.url)), '../pages/review/tasks.vue')
const taskCard = resolve(dirname(fileURLToPath(import.meta.url)), '../components/review/ReviewTaskCard.vue')

test('任务轮询静默合并任务状态，不重新加载整个页面', async () => {
  const source = await readFile(tasksPage, 'utf8')

  assert.match(source, /const mergeTasks =/)
  assert.match(source, /Object\.assign\(tasks\.value\[index\], task\)/)
  assert.match(source, /void refreshTasks\(\)/)
  assert.doesNotMatch(source, /void load\(\) }, 7000/)
})

test('待启动任务独立分组，只有运行中任务显示进度', async () => {
  const [pageSource, cardSource] = await Promise.all([readFile(tasksPage, 'utf8'), readFile(taskCard, 'utf8')])

  assert.match(pageSource, /待启动 \{\{ pendingStartTasks\.length \}\} 项/)
  assert.match(pageSource, /\['QUEUED', 'RUNNING'\]/)
  assert.match(cardSource, /v-if="isRunning"/)
  assert.match(cardSource, /const isRunning = computed\(\(\) => props\.task\.status === 'RUNNING'\)/)
})
