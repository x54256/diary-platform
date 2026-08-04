import assert from 'node:assert/strict'
import test from 'node:test'

import { normalizeKeyQuotes } from '../utils/review-daily-material.ts'

test('normalizes daily material key quotes for display', () => {
  assert.deepEqual(normalizeKeyQuotes(['原句', '', 1, '原句', '另一句']), ['原句', '另一句'])
  assert.deepEqual(normalizeKeyQuotes('单个原句'), ['单个原句'])
  assert.deepEqual(normalizeKeyQuotes(null), [])
  assert.deepEqual(normalizeKeyQuotes({ text: '非法结构' }), [])
})
