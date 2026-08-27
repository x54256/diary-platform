import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const read = (path: string) => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8')

test('知识页使用默认布局并保持全宽响应式内容区', () => {
  const list = read('pages/knowledge/index.vue')
  const detail = read('pages/knowledge/events/[id].vue')
  assert.match(list, /class="w-full px-4/)
  assert.match(detail, /class="w-full px-4/)
  assert.doesNotMatch(list, /layout:\s*'auth'/)
  assert.doesNotMatch(detail, /layout:\s*'auth'/)
})

test('知识事件内容不使用 v-html，且不再展示来源片段', () => {
  const list = read('pages/knowledge/index.vue')
  const detail = read('pages/knowledge/events/[id].vue')
  assert.doesNotMatch(list + detail, /v-html/)
  assert.match(list + detail, /knowledgePlainText/)
  assert.doesNotMatch(detail, /source_fragments|来源片段/)
})

test('知识事件内容使用段落数组', () => {
  const types = read('types/knowledge.ts')
  const utility = read('utils/knowledgeText.ts')
  assert.match(types, /content: string\[\]/)
  assert.match(utility, /Array\.isArray\(value\)/)
  assert.match(utility, /join\('\\n\\n'\)/)
})

test('知识列表和详情展示来源日记日期与事件标题', () => {
  const pages = read('pages/knowledge/index.vue') + read('pages/knowledge/events/[id].vue')
  const types = read('types/knowledge.ts')
  assert.equal((pages.match(/event\.source_diary_date/g) || []).length, 2)
  assert.equal((pages.match(/event\.source_event_title/g) || []).length, 2)
  assert.match(types, /source_diary_date: string/)
  assert.match(types, /source_event_title\?: string \| null/)
})

test('知识事件来源链接携带原日记事件 ID', () => {
  const detail = read('pages/knowledge/events/[id].vue')
  assert.match(detail, /`\/diary\/\$\{event\.diary_id\}#event-\$\{event\.source_diary_event_id\}`/)
})

test('知识列表按日记和原结构化事件分组展示', () => {
  const list = read('pages/knowledge/index.vue')
  const types = read('types/knowledge.ts')
  assert.match(list, /v-for="diaryGroup in groupedEvents"/)
  assert.match(list, /v-for="eventGroup in diaryGroup\.eventGroups"/)
  assert.match(list, /source_diary_event_id/)
  assert.match(types, /source_event_order: number/)
  assert.match(types, /source_order: number/)
})

test('底部导航包含知识并按知识路由高亮', () => {
  assert.match(read('components/BottomTabBar.vue'), /key: 'knowledge'.*path: '\/knowledge'/)
  assert.match(read('layouts/default.vue'), /startsWith\('\/knowledge'\).*'knowledge'/)
})

test('日记详情保持无底栏布局并提供知识沉淀入口', () => {
  const diary = read('pages/diary/[id].vue')
  assert.match(diary, /layout:\s*'auth'/)
  assert.match(diary, /<KnowledgeDepositCard/)
})

test('知识沉淀入口展示后端返回的具体不可用原因', () => {
  const card = read('components/KnowledgeDepositCard.vue')
  const types = read('types/knowledge.ts')
  assert.match(card, /status\.unavailable_reason/)
  assert.doesNotMatch(card, /当前结构化来源不满足沉淀条件/)
  assert.match(types, /unavailable_reason\?: string \| null/)
})

test('知识事件日记分组提供事项整理入口并轮询升级任务', () => {
  const list = read('pages/knowledge/index.vue')
  assert.match(list, /\/knowledge\/matters\/upgrade-status/)
  assert.match(list, /\/knowledge\/matters\/upgrade'/)
  assert.match(list, /\/knowledge-tasks\/\$\{task\.id\}/)
  assert.match(list, /upgradePendingDiaryIds\.has\(diaryGroup\.diaryId\)/)
  assert.match(list, /整理事项/)
  assert.match(list, /setInterval\(\(\) => \{ void pollMatterUpgrade\(\) \}, 2000\)/)
})
