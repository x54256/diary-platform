import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const root = dirname(fileURLToPath(import.meta.url))
const page = resolve(root, '../pages/index.vue')
const types = resolve(root, '../types/index.ts')

test('搜索页使用日记级结果卡、三条折叠和语义状态提示', async () => {
  const source = await readFile(page, 'utf8')
  assert.match(source, /visibleSearchMatches\(item\)/)
  assert.match(source, /item\.matches\.slice\(0, 3\)/)
  assert.match(source, /semanticStatus === 'PARTIAL'/)
  assert.match(source, /semanticStatus === 'UNAVAILABLE'/)
  assert.match(source, /text-red-600/)
  assert.match(source, /\/diary\/\$\{item\.diary_id\}/)
  assert.doesNotMatch(source, /<EventCard\s+v-for="item in searchResults"/)
})

test('前端契约包含日记级排名与命中来源', async () => {
  const source = await readFile(types, 'utf8')
  const pageSource = await readFile(page, 'utf8')
  assert.match(source, /interface SearchRanking/)
  assert.match(source, /keyword_rank/)
  assert.match(source, /semantic_rank/)
  assert.match(source, /rrf_score/)
  assert.match(source, /interface DiarySearchMatch/)
  assert.match(source, /analysis_run_id/)
  assert.match(source, /semantic_layer/)
  assert.match(pageSource, /认知整理/)
})
