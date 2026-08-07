import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const root = dirname(fileURLToPath(import.meta.url))

test('向量化用途和模型管理使用独立 embedding 类型', async () => {
  const settings = await readFile(resolve(root, '../pages/admin/model-settings.vue'), 'utf8')
  const models = await readFile(resolve(root, '../pages/admin/models.vue'), 'utf8')
  const channels = await readFile(resolve(root, '../pages/admin/channels.vue'), 'utf8')
  assert.match(settings, /key: 'embedding', label: '向量化', modelType: 'embedding'/)
  assert.match(models, /option value="embedding"/)
  assert.match(models, /文本向量化/)
  assert.match(channels, /option value="embedding"/)
})
