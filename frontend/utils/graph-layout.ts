/** 图谱几何计算：按直接关系分层，新增节点保留已有位置。 */
export type GraphPosition = { x: number; y: number }
export type GraphPositions = Record<string, GraphPosition>
type Node = { event_id: string; diary_id: string }
type Edge = { id: string; source_event_id: string; target_event_id: string }
export type GraphBox = { x: number; y: number; width: number; height: number }
export const nodeBox = (p: GraphPosition): GraphBox => ({ x: p.x - 78, y: p.y - 34, width: 156, height: 142 })
export const overlaps = (a: GraphBox, b: GraphBox) => a.x < b.x + b.width && a.x + a.width > b.x && a.y < b.y + b.height && a.y + a.height > b.y

export function layoutGraph(nodes: Node[], edges: Edge[], diaryId: string, previous: GraphPositions = {}, columns = 2): GraphPositions {
  const result: GraphPositions = {}
  const ids = new Set(nodes.map(node => node.event_id))
  const adjacency = new Map(nodes.map(node => [node.event_id, new Set<string>()]))
  for (const edge of edges) {
    if (!ids.has(edge.source_event_id) || !ids.has(edge.target_event_id)) continue
    adjacency.get(edge.source_event_id)!.add(edge.target_event_id)
    adjacency.get(edge.target_event_id)!.add(edge.source_event_id)
  }
  for (const node of nodes) if (previous[node.event_id]) result[node.event_id] = { ...previous[node.event_id] }
  const occupied = Object.values(result).map(nodeBox)
  const visited = new Set<string>()
  let componentY = 0
  const roots = [...nodes].sort((a, b) => Number(b.diary_id === diaryId) - Number(a.diary_id === diaryId) || adjacency.get(b.event_id)!.size - adjacency.get(a.event_id)!.size)
  for (const root of roots) {
    if (visited.has(root.event_id)) continue
    let level = [root.event_id], row = 0
    visited.add(root.event_id)
    while (level.length) {
      const next: string[] = []
      for (let i = 0; i < level.length; i++) {
        const id = level[i]
        if (!result[id]) {
          const rowLength = Math.min(columns, level.length - Math.floor(i / columns) * columns)
          let p = { x: (i % columns - (rowLength - 1) / 2) * 184, y: componentY + (row + Math.floor(i / columns)) * 202 }
          // 展开关联时优先靠近已存在的邻居，再避开完整的节点和标题区域。
          const anchor = [...adjacency.get(id)!].find(neighbor => result[neighbor])
          if (anchor && Object.keys(previous).length) p = { x: result[anchor].x + 184, y: result[anchor].y }
          while (occupied.some(box => overlaps(nodeBox(p), box))) p = { x: p.x, y: p.y + 202 }
          result[id] = p; occupied.push(nodeBox(p))
        }
        for (const neighbor of adjacency.get(id)!) if (!visited.has(neighbor)) { visited.add(neighbor); next.push(neighbor) }
      }
      row += Math.ceil(level.length / columns); level = next
    }
    componentY = Math.max(...Object.values(result).map(p => p.y)) + 220
  }
  return result
}

export function graphEdges(edges: Edge[], positions: GraphPositions, priorityId = '') {
  const occupied = Object.values(positions).map(nodeBox)
  return [...edges].sort((a, b) => Number(b.id === priorityId) - Number(a.id === priorityId)).flatMap(edge => {
    const a = positions[edge.source_event_id], b = positions[edge.target_event_id]
    if (!a || !b) return []
    const dx = b.x - a.x, dy = b.y - a.y, length = Math.hypot(dx, dy) || 1
    // 连线从圆点侧面进出，绕开圆点下方的标题和日期。
    const vertical = Math.abs(dy) > Math.abs(dx) * .7
    const sign = dx >= 0 ? 1 : -1
    const side = vertical ? 1 : sign
    const start = { x: a.x + side * 33, y: a.y }
    const end = { x: b.x + (vertical ? 1 : -sign) * 36, y: b.y }
    const lane = Math.max(a.x, b.x) + 148
    const c1 = vertical ? { x: lane, y: a.y } : { x: (a.x + b.x) / 2, y: a.y - 65 }
    const c2 = vertical ? { x: lane, y: b.y } : { x: (a.x + b.x) / 2, y: b.y - 65 }
    const at = (t: number) => ({ x: (1-t)**3 * start.x + 3*(1-t)**2*t*c1.x + 3*(1-t)*t*t*c2.x + t**3*end.x,
      y: (1-t)**3 * start.y + 3*(1-t)**2*t*c1.y + 3*(1-t)*t*t*c2.y + t**3*end.y })
    let label: GraphPosition | null = null
    for (const t of [.5, .35, .65, .23, .77]) {
      const p = at(t)
      for (const offset of [-18, 18, -42, 42]) {
        const candidate = { x: p.x - dy / length * offset, y: p.y + dx / length * offset }
        const box = { x: candidate.x - 52, y: candidate.y - 20, width: 104, height: 40 }
        if (!occupied.some(other => overlaps(box, other))) { label = candidate; occupied.push(box); break }
      }
      if (label) break
    }
    const minX = Math.min(start.x, end.x, c1.x, c2.x) - 14, minY = Math.min(start.y, end.y, c1.y, c2.y) - 14
    const bounds = { x: minX, y: minY, width: Math.max(start.x, end.x, c1.x, c2.x) + 14 - minX, height: Math.max(start.y, end.y, c1.y, c2.y) + 14 - minY }
    return [{ id: edge.id, bounds, path: `M ${start.x} ${start.y} C ${c1.x} ${c1.y}, ${c2.x} ${c2.y}, ${end.x} ${end.y}`, label }]
  })
}
