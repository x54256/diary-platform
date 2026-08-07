/** 将关键词摘要拆为普通/命中交替片段，供模板安全渲染，不注入 HTML。 */
export function splitSearchSnippet(text: string, keyword: string, matched: boolean): string[] {
  if (!matched || !keyword) return [text]
  const escaped = keyword.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  return text.split(new RegExp(`(${escaped})`, 'ig'))
}
