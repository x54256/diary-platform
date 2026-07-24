import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const schedulePage = resolve(dirname(fileURLToPath(import.meta.url)), '../pages/schedule.vue')

test('周视图表格日期表头应固定在滚动区域顶部', async () => {
  const source = await readFile(schedulePage, 'utf8')
  const tableDateHeader = source.match(
    /class="([^"]*schedule-table-date-header[^"]*)"[^>]*>\{\{ d\.month \}\}月\{\{ d\.date \}\}日－周\{\{ d\.name \}\}/,
  )?.[1]

  assert.ok(tableDateHeader, '周视图日期表头应标记为 schedule-table-date-header')
  assert.match(tableDateHeader, /\bsticky\b/)
  assert.match(tableDateHeader, /\btop-0\b/)
})

test('日程页应固定在视口内，让顶部日历由内部滚动结构控制', async () => {
  const source = await readFile(schedulePage, 'utf8')

  assert.match(source, /class="schedule-page fixed inset-0 flex flex-col overflow-hidden bg-white"/)
})
