<template>
  <div
    ref="rootRef"
    :class="containerClass"
    data-annotation-root
    @mouseup="handleSelection"
    @touchend="handleSelection"
    @click="handleClick"
  >
    <p
      v-for="(paragraph, index) in paragraphs"
      :key="index"
      :data-paragraph-index="index"
      :class="paragraphClass"
    >
      <span v-if="showIndex && paragraphs.length > 1" class="annotation-prefix mr-1">{{ index + 1 }}. </span>
      <span
        class="annotation-text"
        data-paragraph-content
        v-html="renderAnalysisMarkup(paragraph)"
      />
    </p>
  </div>
</template>

<script setup lang="ts">
import { nextTick, onMounted, ref, watch } from 'vue'
import type { DiaryAnnotation, DiaryAnnotationClick, DiaryAnnotationSelection } from '~/types'
import { renderAnalysisMarkup } from '~/utils/analysis-markup'

const props = withDefaults(defineProps<{
  paragraphs: string[]
  targetType: DiaryAnnotation['target_type']
  eventId?: string
  analysisItemId?: string
  annotations?: DiaryAnnotation[]
  containerClass?: string
  paragraphClass?: string
  showIndex?: boolean
}>(), {
  annotations: () => [],
  containerClass: '',
  paragraphClass: '',
  showIndex: false,
})

const emit = defineEmits<{
  (event: 'select', selection: DiaryAnnotationSelection): void
  (event: 'annotation-clicked', payload: DiaryAnnotationClick): void
}>()

const rootRef = ref<HTMLElement | null>(null)

const matchingAnnotations = () => props.annotations.filter(annotation => {
  if (annotation.deleted_at) return false
  if (annotation.target_type !== props.targetType) return false
  if (props.targetType === 'ANALYSIS_ITEM') {
    return annotation.analysis_item_id === props.analysisItemId
  }
  return annotation.event_id === props.eventId
})

const textLength = (node: Node): number => node.textContent?.length || 0

const textNodes = (container: HTMLElement): Text[] => {
  const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT)
  const nodes: Text[] = []
  let current = walker.nextNode()
  while (current) {
    nodes.push(current as Text)
    current = walker.nextNode()
  }
  return nodes
}

const wrapTextRange = (container: HTMLElement, start: number, end: number, annotation: DiaryAnnotation) => {
  if (end <= start) return
  let cursor = 0
  for (const node of textNodes(container)) {
    const length = textLength(node)
    const nodeStart = cursor
    const nodeEnd = cursor + length
    cursor = nodeEnd
    const localStart = Math.max(start, nodeStart) - nodeStart
    const localEnd = Math.min(end, nodeEnd) - nodeStart
    if (localEnd <= localStart) continue

    const range = document.createRange()
    range.setStart(node, localStart)
    range.setEnd(node, localEnd)
    const mark = document.createElement('mark')
    mark.className = annotation.comments.length
      ? 'diary-annotation-mark diary-annotation-mark--commented'
      : 'diary-annotation-mark'
    mark.dataset.annotationId = annotation.id
    range.surroundContents(mark)
  }
}

const applyMarks = async () => {
  await nextTick()
  const root = rootRef.value
  if (!root) return

  const paragraphs = Array.from(root.querySelectorAll<HTMLElement>('[data-paragraph-index]'))
  paragraphs.forEach((paragraph) => {
    const index = Number(paragraph.dataset.paragraphIndex)
    const content = paragraph.querySelector<HTMLElement>('[data-paragraph-content]')
    if (!content) return
    content.innerHTML = renderAnalysisMarkup(props.paragraphs[index] || '')
  })

  for (const annotation of matchingAnnotations()) {
    for (const paragraph of paragraphs) {
      const index = Number(paragraph.dataset.paragraphIndex)
      const content = paragraph.querySelector<HTMLElement>('[data-paragraph-content]')
      if (!content) continue
      const start = index === annotation.start_paragraph ? annotation.start_offset : index > annotation.start_paragraph ? 0 : -1
      const end = index === annotation.end_paragraph ? annotation.end_offset : index < annotation.end_paragraph ? content.textContent?.length || 0 : -1
      if (start >= 0 && end > start) {
        wrapTextRange(content, start, end, annotation)
      }
    }
  }
}

const findParagraph = (node: Node | null): HTMLElement | null => {
  if (!node) return null
  const element = node.nodeType === Node.ELEMENT_NODE ? node as Element : node.parentElement
  return element?.closest('[data-paragraph-index]') as HTMLElement | null
}

const findContent = (paragraph: HTMLElement): HTMLElement | null =>
  paragraph.querySelector<HTMLElement>('[data-paragraph-content]')

const offsetInsideContent = (content: HTMLElement, node: Node, offset: number): number => {
  if (node === content) {
    const range = document.createRange()
    range.setStart(content, 0)
    range.setEnd(content, offset)
    return range.toString().length
  }
  if (content.contains(node)) {
    const range = document.createRange()
    range.selectNodeContents(content)
    range.setEnd(node, offset)
    return range.toString().length
  }
  const prefix = content.parentElement?.querySelector<HTMLElement>(':scope > .annotation-prefix')
  return prefix?.contains(node) ? 0 : (content.textContent?.length || 0)
}

const resolveBoundary = (node: Node | null, offset: number) => {
  const paragraph = findParagraph(node)
  if (!paragraph) return null
  const content = findContent(paragraph)
  if (!content) return null
  return {
    paragraph: Number(paragraph.dataset.paragraphIndex),
    offset: offsetInsideContent(content, node as Node, offset),
  }
}

const sourceText = () => props.paragraphs.map(value => {
  const wrapper = document.createElement('div')
  wrapper.innerHTML = renderAnalysisMarkup(value || '')
  return wrapper.textContent || ''
}).join('\n')

const sliceSource = (start: { paragraph: number; offset: number }, end: { paragraph: number; offset: number }) => {
  const values = props.paragraphs.map(value => {
    const wrapper = document.createElement('div')
    wrapper.innerHTML = renderAnalysisMarkup(value || '')
    return wrapper.textContent || ''
  })
  if (start.paragraph === end.paragraph) {
    return values[start.paragraph]?.slice(start.offset, end.offset) || ''
  }
  const parts = [values[start.paragraph]?.slice(start.offset) || '']
  for (let index = start.paragraph + 1; index < end.paragraph; index += 1) {
    parts.push(values[index] || '')
  }
  parts.push(values[end.paragraph]?.slice(0, end.offset) || '')
  return parts.join('\n')
}

const handleSelection = () => {
  window.setTimeout(() => {
    const root = rootRef.value
    const selection = window.getSelection()
    if (!root || !selection || selection.isCollapsed || !selection.anchorNode || !selection.focusNode) return
    if (!root.contains(selection.anchorNode) || !root.contains(selection.focusNode)) return

    let start = resolveBoundary(selection.anchorNode, selection.anchorOffset)
    let end = resolveBoundary(selection.focusNode, selection.focusOffset)
    if (!start || !end) return
    if (start.paragraph > end.paragraph || (start.paragraph === end.paragraph && start.offset > end.offset)) {
      const temp = start
      start = end
      end = temp
    }
    if (start.paragraph === end.paragraph && start.offset === end.offset) return

    const fullText = sourceText()
    const selectedText = sliceSource(start, end)
    if (!selectedText.trim()) return
    const startAbsolute = props.paragraphs.slice(0, start.paragraph).map(value => {
      const wrapper = document.createElement('div')
      wrapper.innerHTML = renderAnalysisMarkup(value || '')
      return wrapper.textContent?.length || 0
    }).reduce((total, length) => total + length + 1, 0) + start.offset
    const endAbsolute = startAbsolute + selectedText.length
    emit('select', {
      target_type: props.targetType,
      event_id: props.eventId,
      analysis_item_id: props.analysisItemId,
      field_name: props.targetType === 'EVENT_BODY' ? 'body' : props.targetType === 'EVENT_FEELING' ? 'feeling' : props.targetType === 'EVENT_REFLECTION' ? 'reflection' : undefined,
      start_paragraph: start.paragraph,
      start_offset: start.offset,
      end_paragraph: end.paragraph,
      end_offset: end.offset,
      selected_text: selectedText,
      context_before: fullText.slice(Math.max(0, startAbsolute - 24), startAbsolute),
      context_after: fullText.slice(endAbsolute, endAbsolute + 24),
    })
  }, 0)
}

const handleClick = (event: MouseEvent) => {
  const target = event.target as HTMLElement
  const mark = target.closest<HTMLElement>('[data-annotation-id]')
  if (!mark?.dataset.annotationId) return
  const annotation = matchingAnnotations().find(item => item.id === mark.dataset.annotationId)
  if (!annotation) return
  emit('annotation-clicked', {
    annotationId: annotation.id,
    selectedText: sliceSource(
      { paragraph: annotation.start_paragraph, offset: annotation.start_offset },
      { paragraph: annotation.end_paragraph, offset: annotation.end_offset },
    ),
    clientX: event.clientX,
    clientY: event.clientY,
  })
}

watch(() => [props.paragraphs, props.annotations], applyMarks, { deep: true })
onMounted(applyMarks)
</script>
