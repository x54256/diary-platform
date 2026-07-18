import assert from 'node:assert/strict'
import test from 'node:test'

import { renderAnalysisMarkup } from '../utils/analysis-markup.ts'

test('renders bold and custom red markers', () => {
  assert.equal(
    renderAnalysisMarkup('需要**先确定功能点**，避免<red>关键逻辑失控</red>。'),
    '需要<strong>先确定功能点</strong>，避免<span class="analysis-danger">关键逻辑失控</span>。',
  )
})

test('escapes raw html while rendering supported markers', () => {
  assert.equal(
    renderAnalysisMarkup('<script>alert(1)</script> **重点** <red><img src=x></red>'),
    '&lt;script&gt;alert(1)&lt;/script&gt; <strong>重点</strong> <span class="analysis-danger">&lt;img src=x&gt;</span>',
  )
})
