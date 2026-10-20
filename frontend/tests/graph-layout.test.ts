import test from 'node:test'
import assert from 'node:assert/strict'
import { layoutGraph, graphEdges, nodeBox, overlaps } from '../utils/graph-layout.ts'

const nodes = Array.from({ length: 9 }, (_, i) => ({ event_id: `n${i}`, diary_id: i === 0 ? 'current' : 'history' }))
const edges = nodes.slice(1, 7).map((node, i) => ({ id: `r${i}`, source_event_id: 'n0', target_event_id: node.event_id }))

test('按关系组织分支，完整节点及标题区域互不覆盖，孤立事件仍展示', () => {
  const positions = layoutGraph(nodes, edges, 'current')
  assert.equal(Object.keys(positions).length, nodes.length)
  const boxes = Object.values(positions).map(nodeBox)
  boxes.forEach((box, index) => boxes.slice(index + 1).forEach(other => assert.equal(overlaps(box, other), false)))
  assert.deepEqual(positions, layoutGraph(nodes, edges, 'current'))
})

test('新增关系节点时保留已浏览节点的位置', () => {
  const previous = layoutGraph(nodes.slice(0, 3), edges.slice(0, 2), 'current')
  const positions = layoutGraph(nodes, edges, 'current', previous)
  for (const [id, position] of Object.entries(previous)) assert.deepEqual(positions[id], position)
})

test('关系标签避开节点与其他标签，保留原始边身份和路径', () => {
  const positions = layoutGraph(nodes, edges, 'current')
  const drawn = graphEdges(edges, positions, 'r2')
  assert.equal(drawn[0].id, 'r2')
  const occupied = Object.values(positions).map(nodeBox)
  for (const edge of drawn) {
    assert.match(edge.path, /^M .+ C /)
    if (!edge.label) continue
    const box = { x: edge.label.x - 52, y: edge.label.y - 20, width: 104, height: 40 }
    occupied.forEach(other => assert.equal(overlaps(box, other), false))
    occupied.push(box)
  }
})

test('双向环与缺失端点不会生成无效坐标', () => {
  const cycle = [{ id: 'a', source_event_id: 'n0', target_event_id: 'n1' }, { id: 'b', source_event_id: 'n1', target_event_id: 'n0' }, { id: 'missing', source_event_id: 'n0', target_event_id: 'absent' }]
  const positions = layoutGraph(nodes.slice(0, 2), cycle, 'current')
  assert.equal(graphEdges(cycle, positions).length, 2)
  Object.values(positions).forEach(point => assert.ok(Number.isFinite(point.x) && Number.isFinite(point.y)))
})
