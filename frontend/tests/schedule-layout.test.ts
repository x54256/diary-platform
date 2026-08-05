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

test('日程页的一周应从周一开始，且不改变星期值编码', async () => {
  const source = await readFile(schedulePage, 'utf8')

  assert.match(source, /now\.getDate\(\) - \(\(now\.getDay\(\) \+ 6\) % 7\)/)
  assert.match(source, /d\.setDate\(d\.getDate\(\)-\(\(d\.getDay\(\)\+6\)%7\)\)/)
  assert.match(source, /const weekdayOptions = \[\{value:1,label:'一'\}.*\{value:0,label:'日'\}\]/)
  assert.ok(source.includes('const monday=new Date(jan4);monday.setDate(jan4.getDate()-((jan4.getDay()+6)%7)+(week-1)*7);weekStart.value=monday'))
})

test('编辑和新建日程应提供日期，并使用与同步日程一致的横向字段布局', async () => {
  const source = await readFile(schedulePage, 'utf8')

  assert.match(source, /v-model="editForm\.start_date" type="date"/)
  assert.match(source, /v-model="form\.start_date" :min="todayKey" type="date"/)
  assert.match(source, /名称：<\/span>[\s\S]*v-model="editForm\.title"/)
  assert.match(source, /日期：<\/span>[\s\S]*v-model="editForm\.start_date"[\s\S]*全天/)
  assert.match(source, /editScope='single'/)
  assert.match(source, /editScope='following'/)
})

test('过期日程弹层应固定高度，编辑操作按关闭、删除、保存排列', async () => {
  const source = await readFile(schedulePage, 'utf8')

  assert.match(source, /class="flex h-\[70dvh\] w-full flex-col overflow-hidden rounded-t-2xl/)
  const editHeader = source.match(/<h2 class="text-lg font-semibold">编辑日程<\/h2>([\s\S]*?)<\/div>\n<\/div>/)?.[1]
  assert.ok(editHeader)
  assert.ok(editHeader.indexOf('>关闭</button>') < editHeader.indexOf('>删除</button>'))
  assert.ok(editHeader.indexOf('>删除</button>') < editHeader.indexOf('>保存</button>'))
})
