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

test('renders relative time tags as interactive safe spans', () => {
  assert.equal(
    renderAnalysisMarkup('<time value="2026-08-04 周二 20:00">昨天晚上八点</time>回家'),
    '<span class="diary-time-mark" data-relative-time="true" data-time-value="2026-08-04 周二 20:00" tabindex="0" role="button" aria-label="2026-08-04 周二 20:00">昨天晚上八点</span>回家',
  )
})

test('does not render malformed time values as html', () => {
  assert.equal(
    renderAnalysisMarkup('<time value="不确定">周一</time>'),
    '&lt;time value=&quot;不确定&quot;&gt;周一&lt;/time&gt;',
  )
})
