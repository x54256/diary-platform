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

test('扩展图谱时复用旧布局输入，不修改调用方坐标，全部节点仍有有效位置', () => {
  const previous = layoutGraph(nodes.slice(0, 3), edges.slice(0, 2), 'current')
  const snapshot = structuredClone(previous)
  const positions = layoutGraph(nodes, edges, 'current', previous)
  assert.deepEqual(previous, snapshot)
  assert.deepEqual(positions, layoutGraph(nodes, edges, 'current', previous))
  assert.equal(Object.keys(positions).length, nodes.length)
  Object.values(positions).forEach(point => assert.ok(Number.isFinite(point.x) && Number.isFinite(point.y)))
  const boxes = Object.values(positions).map(nodeBox)
  boxes.forEach((box, index) => boxes.slice(index + 1).forEach(other => assert.equal(overlaps(box, other), false)))
})

test('直线关系边保留身份，选中边最后绘制，缺失端点的边不输出', () => {
  const positions = layoutGraph(nodes, edges, 'current')
  const drawn = graphEdges([...edges, { id: 'missing', source_event_id: 'n0', target_event_id: 'absent' }], positions, 'r2')
  assert.equal(drawn.at(-1)?.id, 'r2')
  assert.deepEqual(drawn.map(edge => edge.id).sort(), edges.map(edge => edge.id).sort())
  for (const edge of drawn) {
    assert.match(edge.path, /^M .+ L /)
    assert.doesNotMatch(edge.path, /NaN|Infinity/)
  }
})

test('双向环不会生成无效坐标', () => {
  const cycle = [{ id: 'a', source_event_id: 'n0', target_event_id: 'n1' }, { id: 'b', source_event_id: 'n1', target_event_id: 'n0' }]
  const positions = layoutGraph(nodes.slice(0, 2), cycle, 'current')
  assert.equal(graphEdges(cycle, positions).length, 2)
  Object.values(positions).forEach(point => assert.ok(Number.isFinite(point.x) && Number.isFinite(point.y)))
})

test('缺失起点、终点或双方的关系不影响有效节点布局', () => {
  const withMissingEndpoint = [
    ...edges,
    { id: 'missing-target', source_event_id: 'n0', target_event_id: 'absent' },
    { id: 'missing-source', source_event_id: 'absent', target_event_id: 'n1' },
    { id: 'missing-both', source_event_id: 'absent', target_event_id: 'also-absent' },
  ]
  const snapshot = structuredClone(withMissingEndpoint)
  const positions = layoutGraph(nodes, withMissingEndpoint, 'current')
  assert.deepEqual(positions, layoutGraph(nodes, edges, 'current'))
  assert.deepEqual(withMissingEndpoint, snapshot)
  assert.equal(Object.keys(positions).length, nodes.length)
  assert.equal(graphEdges(withMissingEndpoint, positions).length, edges.length)
  Object.values(positions).forEach(point => assert.ok(Number.isFinite(point.x) && Number.isFinite(point.y)))
})
