/** 小型事件图谱的稳定布局和边路线计算。 */
export type GraphPosition = { x: number; y: number }
export type GraphPositions = Record<string, GraphPosition>
type Node = { event_id: string; diary_id: string; diary_date?: string }
type Edge = { id: string; source_event_id: string; target_event_id: string }
export type GraphBox = { x: number; y: number; width: number; height: number }

export const nodeBox = (p: GraphPosition, dense = false): GraphBox => {
  const width = dense ? 152 : 156
  const height = dense ? 128 : 142
  return { x: p.x - width / 2, y: p.y - (dense ? 30 : 34), width, height }
}
export const overlaps = (a: GraphBox, b: GraphBox) => a.x < b.x + b.width && a.x + a.width > b.x && a.y < b.y + b.height && a.y + a.height > b.y

const hashString = (value: string) => {
  let hash = 2166136261
  for (let i = 0; i < value.length; i++) hash = Math.imul(hash ^ value.charCodeAt(i), 16777619)
  return hash >>> 0
}
const seededAngle = (value: string) => hashString(value) / 0xffffffff * Math.PI * 2
const distance = (a: GraphPosition, b: GraphPosition) => Math.hypot(b.x - a.x, b.y - a.y)
const cross = (a: GraphPosition, b: GraphPosition, c: GraphPosition) => (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x)
const segmentsCross = (a: GraphPosition, b: GraphPosition, c: GraphPosition, d: GraphPosition) =>
  cross(a, b, c) * cross(a, b, d) < -0.01 && cross(c, d, a) * cross(c, d, b) < -0.01

const edgeCrossingCount = (edges: Edge[], positions: GraphPositions) => {
  let count = 0
  for (let i = 0; i < edges.length; i++) {
    const a = edges[i]
    const a1 = positions[a.source_event_id], a2 = positions[a.target_event_id]
    if (!a1 || !a2) continue
    for (let j = i + 1; j < edges.length; j++) {
      const b = edges[j]
      if ([a.source_event_id, a.target_event_id].some(id => id === b.source_event_id || id === b.target_event_id)) continue
      const b1 = positions[b.source_event_id], b2 = positions[b.target_event_id]
      if (b1 && b2 && segmentsCross(a1, a2, b1, b2)) count++
    }
  }
  return count
}

function resolveNodeOverlaps(nodes: Node[], positions: GraphPositions) {
  const dense = nodes.length > 20
  for (let pass = 0; pass < 48; pass++) {
    let changed = false
    for (let i = 0; i < nodes.length; i++) for (let j = i + 1; j < nodes.length; j++) {
      const a = nodes[i].event_id, b = nodes[j].event_id
      const pa = positions[a], pb = positions[b], ba = nodeBox(pa, dense), bb = nodeBox(pb, dense)
      const overlapX = Math.min(ba.x + ba.width, bb.x + bb.width) - Math.max(ba.x, bb.x)
      const overlapY = Math.min(ba.y + ba.height, bb.y + bb.height) - Math.max(ba.y, bb.y)
      if (overlapX <= 0 || overlapY <= 0) continue
      changed = true
      const direction = hashString(`${a}:${b}`) % 2 ? 1 : -1
      if (overlapX < overlapY) {
        const shift = overlapX / 2 + 12
        const sign = pb.x === pa.x ? direction : Math.sign(pb.x - pa.x)
        pa.x -= sign * shift; pb.x += sign * shift
      } else {
        const shift = overlapY / 2 + 12
        const sign = pb.y === pa.y ? direction : Math.sign(pb.y - pa.y)
        pa.y -= sign * shift; pb.y += sign * shift
      }
    }
    if (!changed) break
  }
}

function reduceCrossings(nodes: Node[], edges: Edge[], positions: GraphPositions) {
  const dense = nodes.length > 20
  const anchors = Object.fromEntries(nodes.map(node => [node.event_id, { ...positions[node.event_id] }]))
  const energy = () => {
    // 交叉线可以通过颜色和选中态辅助辨认；避免为了消除交叉，把有关联的事件拉得很远。
    let value = edgeCrossingCount(edges, positions) * 100
    for (let i = 0; i < nodes.length; i++) {
      const a = nodes[i], pa = positions[a.event_id]
      for (let j = i + 1; j < nodes.length; j++) {
        const b = nodes[j], pb = positions[b.event_id]
        if (overlaps(nodeBox(pa, dense), nodeBox(pb, dense))) value += 18000
      }
      value += (distance(pa, anchors[a.event_id]) ** 2) * 0.002
    }
    for (const edge of edges) {
      const a = positions[edge.source_event_id], b = positions[edge.target_event_id]
      if (a && b) value += Math.max(0, distance(a, b) - 190) ** 2 * 1.8
    }
    return value
  }

  for (const step of [64, 36, 20, 11]) {
    for (let pass = 0; pass < 2; pass++) {
      for (const node of nodes) {
        const current = positions[node.event_id]
        let best = current, bestEnergy = energy()
        for (let direction = 0; direction < 8; direction++) {
          const angle = direction * Math.PI / 4
          positions[node.event_id] = { x: current.x + Math.cos(angle) * step, y: current.y + Math.sin(angle) * step }
          const candidateEnergy = energy()
          if (candidateEnergy < bestEnergy) {
            bestEnergy = candidateEnergy
            best = positions[node.event_id]
          }
        }
        positions[node.event_id] = best
      }
    }
  }
}

function compactConnectedNodes(nodes: Node[], edges: Edge[], positions: GraphPositions) {
  for (let pass = 0; pass < 48; pass++) {
    const longest = [...edges].sort((a, b) => distance(positions[b.source_event_id], positions[b.target_event_id]) - distance(positions[a.source_event_id], positions[a.target_event_id]))
    for (const edge of longest) {
      const a = positions[edge.source_event_id], b = positions[edge.target_event_id]
      if (!a || !b) continue
      const dx = b.x - a.x, dy = b.y - a.y, length = Math.hypot(dx, dy) || 1
      const shift = Math.max(0, length - 195) * 0.65
      a.x += dx / length * shift; a.y += dy / length * shift
      b.x -= dx / length * shift; b.y -= dy / length * shift
    }
    resolveNodeOverlaps(nodes, positions)
  }
}

export function layoutGraph(nodes: Node[], edges: Edge[], diaryId: string, previous: GraphPositions = {}): GraphPositions {
  const positions: GraphPositions = {}
  const anchors: GraphPositions = {}
  const dates = new Map<string, Node[]>()
  const neighbors = new Map(nodes.map(node => [node.event_id, new Set<string>()]))

  for (const edge of edges) {
    neighbors.get(edge.source_event_id)?.add(edge.target_event_id)
    neighbors.get(edge.target_event_id)?.add(edge.source_event_id)
  }

  for (const node of nodes) {
    const group = node.diary_date || node.diary_id
    dates.set(group, [...(dates.get(group) || []), node])
  }
  for (const node of nodes) if (previous[node.event_id]) positions[node.event_id] = { ...previous[node.event_id] }

  // 先把本篇事件放成紧凑的起点，再按关系邻接放置关联事件；随机散点起步会让近邻需要长时间才能靠拢。
  const roots = nodes.filter(node => node.diary_id === diaryId)
  const rootIds = new Set(roots.map(node => node.event_id))
  const pendingRoots = roots.filter(node => !positions[node.event_id])
  while (pendingRoots.length) {
    const placedRoots = roots.filter(node => positions[node.event_id])
    const node = pendingRoots.shift()!
    const linkedRoots = [...(neighbors.get(node.event_id) || [])].filter(id => rootIds.has(id) && positions[id])
    if (linkedRoots.length) {
      const center = linkedRoots.reduce((sum, id) => ({ x: sum.x + positions[id].x / linkedRoots.length, y: sum.y + positions[id].y / linkedRoots.length }), { x: 0, y: 0 })
      const angle = seededAngle(node.event_id)
      const dense = nodes.length > 20
      const radius = dense ? (linkedRoots.length > 1 ? 70 : 92) : (linkedRoots.length > 1 ? 82 : 112)
      positions[node.event_id] = { x: center.x + Math.cos(angle) * radius, y: center.y + Math.sin(angle) * radius }
    } else if (!placedRoots.length) {
      positions[node.event_id] = { x: 0, y: 0 }
    } else {
      const angle = seededAngle(node.event_id)
      const radius = 220 + Math.floor(placedRoots.length / 3) * 170
      positions[node.event_id] = { x: Math.cos(angle) * radius, y: Math.sin(angle) * radius }
    }
  }

  for (let pass = 0; pass < nodes.length; pass++) {
    let placed = false
    for (const node of nodes) {
      if (positions[node.event_id]) continue
      const linked = [...(neighbors.get(node.event_id) || [])].filter(id => positions[id])
      if (!linked.length) continue
      const center = linked.reduce((sum, id) => ({ x: sum.x + positions[id].x / linked.length, y: sum.y + positions[id].y / linked.length }), { x: 0, y: 0 })
      const angle = seededAngle(node.event_id)
      const dense = nodes.length > 20
      const radius = dense ? (linked.length > 1 ? 64 : 92) : (linked.length > 1 ? 76 : 112)
      positions[node.event_id] = { x: center.x + Math.cos(angle) * radius, y: center.y + Math.sin(angle) * radius }
      placed = true
    }
    if (!placed) break
  }

  for (const node of nodes) {
    if (!positions[node.event_id]) {
      const angle = seededAngle(node.event_id)
      positions[node.event_id] = { x: Math.cos(angle) * 180, y: Math.sin(angle) * 180 }
    }
    anchors[node.event_id] = { ...positions[node.event_id] }
  }

  const iterations = nodes.length > 35 ? 180 : 260
  for (let iteration = 0; iteration < iterations; iteration++) {
    const forces = Object.fromEntries(nodes.map(node => [node.event_id, { x: 0, y: 0 }])) as GraphPositions
    const cooling = 0.2 + 0.8 * (1 - iteration / iterations)

    // 节点互斥，给圆点、标题和日期留出空间。
    for (let i = 0; i < nodes.length; i++) {
      const a = nodes[i], pa = positions[a.event_id]
      for (let j = i + 1; j < nodes.length; j++) {
        const b = nodes[j], pb = positions[b.event_id]
        let dx = pb.x - pa.x, dy = pb.y - pa.y
        let length = Math.hypot(dx, dy)
        if (length < 0.01) { dx = 1; dy = 0; length = 1 }
        // 真实矩形碰撞检测已负责防止卡片重叠，额外间距只留少量视觉留白。
        const minimum = (nodes.length > 20 ? 152 : 156) + 16
        if (length < minimum) {
          const force = (minimum - length) * 0.022 * cooling
          const fx = dx / length * force, fy = dy / length * force
          forces[a.event_id].x -= fx; forces[a.event_id].y -= fy
          forces[b.event_id].x += fx; forces[b.event_id].y += fy
        }
      }
    }

    // 关系边提供弹簧力，避免相连事件被排得过远。
    for (const edge of edges) {
      const a = positions[edge.source_event_id], b = positions[edge.target_event_id]
      if (!a || !b) continue
      const dx = b.x - a.x, dy = b.y - a.y, length = Math.hypot(dx, dy) || 1
      const force = (length - 190) * 0.055 * cooling
      const fx = dx / length * force, fy = dy / length * force
      forces[edge.source_event_id].x += fx; forces[edge.source_event_id].y += fy
      forces[edge.target_event_id].x -= fx; forces[edge.target_event_id].y -= fy
    }

    // 同一日记的事件轻微聚拢，不规定它们的上下或左右次序。
    for (const group of dates.values()) {
      if (group.length < 2) continue
      const center = group.reduce((sum, node) => ({ x: sum.x + positions[node.event_id].x / group.length, y: sum.y + positions[node.event_id].y / group.length }), { x: 0, y: 0 })
      for (const node of group) {
        forces[node.event_id].x += (center.x - positions[node.event_id].x) * 0.003 * cooling
        forces[node.event_id].y += (center.y - positions[node.event_id].y) * 0.003 * cooling
      }
    }

    for (const node of nodes) {
      const id = node.event_id, point = positions[id], force = forces[id]
      force.x -= point.x * 0.0009
      force.y -= point.y * 0.0009
      if (previous[id]) {
        force.x += (anchors[id].x - point.x) * 0.025
        force.y += (anchors[id].y - point.y) * 0.025
      }
      const magnitude = Math.hypot(force.x, force.y)
      const limit = 12 * cooling
      const scale = magnitude > limit ? limit / magnitude : 1
      positions[id] = { x: point.x + force.x * scale, y: point.y + force.y * scale }
    }
  }

  resolveNodeOverlaps(nodes, positions)
  reduceCrossings(nodes, edges, positions)
  resolveNodeOverlaps(nodes, positions)
  compactConnectedNodes(nodes, edges, positions)
  const center = nodes.reduce((sum, node) => ({ x: sum.x + positions[node.event_id].x / nodes.length, y: sum.y + positions[node.event_id].y / nodes.length }), { x: 0, y: 0 })
  for (const node of nodes) {
    positions[node.event_id].x -= center.x
    positions[node.event_id].y -= center.y
  }
  return positions
}

export function graphEdges(edges: Edge[], positions: GraphPositions, priorityId = '') {
  return [...edges].sort((a, b) => Number(a.id === priorityId) - Number(b.id === priorityId) || a.id.localeCompare(b.id)).flatMap(edge => {
    const a = positions[edge.source_event_id], b = positions[edge.target_event_id]
    if (!a || !b) return []
    const dx = b.x - a.x, dy = b.y - a.y, length = Math.hypot(dx, dy) || 1
    const ux = dx / length, uy = dy / length
    const start = { x: a.x + ux * 34, y: a.y + uy * 34 }
    const end = { x: b.x - ux * 39, y: b.y - uy * 39 }
    const minX = Math.min(start.x, end.x) - 16, minY = Math.min(start.y, end.y) - 16
    const maxX = Math.max(start.x, end.x) + 16, maxY = Math.max(start.y, end.y) + 16
    return [{ id: edge.id, bounds: { x: minX, y: minY, width: maxX - minX, height: maxY - minY }, path: `M ${start.x} ${start.y} L ${end.x} ${end.y}` }]
  })
}
