const getScrollParents = (element: HTMLTextAreaElement) => {
  const parents: Array<HTMLElement | Element> = []
  let parent = element.parentElement

  while (parent) {
    const overflowY = window.getComputedStyle(parent).overflowY
    if (overflowY === 'auto' || overflowY === 'scroll' || overflowY === 'overlay') {
      parents.push(parent)
    }
    parent = parent.parentElement
  }

  if (document.scrollingElement) parents.push(document.scrollingElement)
  return parents
}

export const resizeTextarea = (element: HTMLTextAreaElement) => {
  const parents = getScrollParents(element)
  const scrollTop = parents.map(parent => parent.scrollTop)

  element.style.height = 'auto'
  element.style.height = `${element.scrollHeight}px`

  parents.forEach((parent, index) => {
    parent.scrollTop = scrollTop[index]
  })
}

export const resizeTextareas = (root: ParentNode = document) => {
  root.querySelectorAll<HTMLTextAreaElement>('textarea[data-auto-resize]').forEach(resizeTextarea)
}
