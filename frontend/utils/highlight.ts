/**
 * 关键词高亮工具：返回安全的 HTML 字符串，命中关键词包裹 <mark class="search-keyword">。
 *
 * 安全说明（防 XSS）：先对原始文本与关键词分别做 HTML 转义，再在转义后的字符串上做
 * 大小写不敏感、子串（中文逐字）匹配并包裹 <mark>。因为匹配与包裹都发生在转义之后，
 * 无论文本或关键词包含任何 HTML / 脚本字符，都不会被当作标签解析，从根本上杜绝注入。
 */

/** 转义 HTML 特殊字符，防止注入。 */
export function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

/**
 * 对文本做关键词高亮，返回可直接用于 v-html 的安全 HTML。
 *
 * @param text 原始文本（将先转义）
 * @param keyword 关键词（将先转义；大小写不敏感，中文按子串匹配）
 */
export function highlight(text: string, keyword: string): string {
  const source = text == null ? '' : String(text)
  const escaped = escapeHtml(source)

  const rawKeyword = keyword == null ? '' : String(keyword).trim()
  if (!rawKeyword) {
    return escaped
  }
  const escapedKeyword = escapeHtml(rawKeyword)
  if (!escapedKeyword) {
    return escaped
  }

  const lowerText = escaped.toLowerCase()
  const lowerKeyword = escapedKeyword.toLowerCase()

  const segments: string[] = []
  let cursor = 0
  let index = lowerText.indexOf(lowerKeyword, cursor)
  while (index !== -1) {
    if (index > cursor) {
      segments.push(escaped.slice(cursor, index))
    }
    segments.push(
      `<mark class="search-keyword">${escaped.slice(index, index + escapedKeyword.length)}</mark>`,
    )
    cursor = index + escapedKeyword.length
    index = lowerText.indexOf(lowerKeyword, cursor)
  }
  segments.push(escaped.slice(cursor))
  return segments.join('')
}
