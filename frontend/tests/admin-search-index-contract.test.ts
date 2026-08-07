import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const root = dirname(fileURLToPath(import.meta.url))

test('管理端索引重建页提供日期范围、进度和失败详情', async () => {
  const source = await readFile(resolve(root, '../pages/admin/search-index.vue'), 'utf8')
  assert.match(source, /type="date"/)
  assert.match(source, /text-base sm:text-sm/)
  assert.match(source, /\/admin\/search-index\/rebuild/)
  assert.match(source, /processed_events/)
  assert.match(source, /failure_details/)
  assert.match(source, /setInterval\(loadJobs, 3000\)/)
})
