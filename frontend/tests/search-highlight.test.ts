import assert from 'node:assert/strict'
import test from 'node:test'
import { splitSearchSnippet } from '../utils/search-highlight.ts'

test('关键词高亮将正则特殊字符按字面量匹配', () => {
  assert.deepEqual(splitSearchSnippet('A[1] 与 A[1]', 'A[1]', true), ['', 'A[1]', ' 与 ', 'A[1]', ''])
  assert.deepEqual(splitSearchSnippet('路径 C\\tmp 与 C\\tmp', 'C\\tmp', true), ['路径 ', 'C\\tmp', ' 与 ', 'C\\tmp', ''])
  assert.deepEqual(splitSearchSnippet('50%_完成', '50%_', true), ['', '50%_', '完成'])
})

test('纯语义命中不拆分文本', () => {
  assert.deepEqual(splitSearchSnippet('语义摘要', '摘要', false), ['语义摘要'])
})
