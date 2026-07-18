import MarkdownIt from 'markdown-it'

const markdown = new MarkdownIt({
  html: false,
  linkify: false,
  typographer: false,
})

markdown.disable(['link', 'image'])

const renderInline = (value: string) => markdown.renderInline(value)

export const renderAnalysisMarkup = (value: string | null | undefined): string => {
  const source = value || ''
  const redPattern = /<red>([\s\S]*?)<\/red>/g
  let cursor = 0
  let result = ''

  for (const match of source.matchAll(redPattern)) {
    const start = match.index ?? 0
    result += renderInline(source.slice(cursor, start))
    result += `<span class="analysis-danger">${renderInline(match[1] || '')}</span>`
    cursor = start + match[0].length
  }

  result += renderInline(source.slice(cursor))
  return result
}
