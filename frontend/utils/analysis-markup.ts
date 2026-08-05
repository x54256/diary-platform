import MarkdownIt from 'markdown-it'

const markdown = new MarkdownIt({
  html: false,
  linkify: false,
  typographer: false,
})

markdown.disable(['link', 'image'])

const renderInline = (value: string) => markdown.renderInline(value)
const timeTagPattern = /<time\s+value="([^"]+)">([\s\S]*?)<\/time>/g
const timeValuePattern = /^\d{4}-\d{2}-\d{2} 周[一二三四五六日](?: (?:[01]\d|2[0-3]):[0-5]\d)?$/

const renderInlineWithTime = (value: string): string => {
  let cursor = 0
  let result = ''
  for (const match of value.matchAll(timeTagPattern)) {
    const start = match.index ?? 0
    result += renderInline(value.slice(cursor, start))
    const timeValue = match[1] || ''
    const label = match[2] || ''
    if (timeValuePattern.test(timeValue)) {
      result += `<span class="diary-time-mark" data-relative-time="true" data-time-value="${timeValue}" tabindex="0" role="button" aria-label="${timeValue}">${renderInline(label)}</span>`
    } else {
      result += renderInline(match[0])
    }
    cursor = start + match[0].length
  }
  return result + renderInline(value.slice(cursor))
}

export const renderAnalysisMarkup = (value: string | null | undefined): string => {
  const source = value || ''
  const redPattern = /<red>([\s\S]*?)<\/red>/g
  let cursor = 0
  let result = ''

  for (const match of source.matchAll(redPattern)) {
    const start = match.index ?? 0
    result += renderInlineWithTime(source.slice(cursor, start))
    result += `<span class="analysis-danger">${renderInlineWithTime(match[1] || '')}</span>`
    cursor = start + match[0].length
  }

  result += renderInlineWithTime(source.slice(cursor))
  return result
}
