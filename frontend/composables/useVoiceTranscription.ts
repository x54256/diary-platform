import type { TranscriptionBatch, TranscriptionItem } from '~/types'
import { orderAudioFiles } from '~/utils/audio-file-order'

const MAX_FILE_SIZE = 300 * 1024 * 1024
const MAX_UPLOAD_CONCURRENCY = 3
const ALLOWED_EXTENSIONS = new Set([
  'aac', 'amr', 'avi', 'flac', 'flv', 'm4a', 'mkv', 'mov', 'mp3', 'mp4',
  'mpeg', 'ogg', 'opus', 'wav', 'webm', 'wma', 'wmv',
])

const createLocalId = () => {
  if (globalThis.crypto?.randomUUID) return `local-${globalThis.crypto.randomUUID()}`
  return `local-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

const addLocalFailedItem = (items: Ref<TranscriptionItem[]>, file: File, message: string) => {
  items.value.push({
    id: createLocalId(),
    sort_order: Number.MAX_SAFE_INTEGER,
    filename: file.name || '未命名音频',
    file_size: file.size,
    status: 'FAILED',
    error_message: message,
    retry_count: 0,
    local: true,
  })
}

export function useVoiceTranscription() {
  const { api } = useApi()
  const config = useRuntimeConfig()
  const authStore = useAuthStore()
  const router = useRouter()
  const batch = ref<TranscriptionBatch | null>(null)
  const localItems = ref<TranscriptionItem[]>([])
  const actionLoading = ref(false)
  const error = ref('')
  let pollTimer: ReturnType<typeof setTimeout> | null = null

  const items = computed(() => [
    ...(batch.value?.items || []),
    ...localItems.value,
  ].sort((a, b) => a.sort_order - b.sort_order))
  const hasAudio = computed(() => items.value.length > 0)
  const uploading = computed(() => localItems.value.some(item => item.status === 'UPLOADING'))
  const uploadFailed = computed(() => localItems.value.some(item => item.status === 'FAILED'))
  const canStart = computed(() =>
    batch.value?.status === 'COLLECTING' && hasAudio.value && !uploading.value && !uploadFailed.value,
  )
  const locked = computed(() => !!batch.value && !['COLLECTING', 'CANCELLED', 'EXPIRED'].includes(batch.value.status))

  const createBatch = async (diaryDate: string) => {
    if (batch.value?.status !== 'COLLECTING') {
      batch.value = await api<TranscriptionBatch>('/transcription-batches', {
        method: 'POST', body: { diary_date: diaryDate },
      })
      localItems.value = []
    }
    return batch.value
  }

  const uploadOne = (batchId: string, file: File, sortOrder: number, localId: string) => new Promise<TranscriptionItem>((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', `${String(config.public.apiBase).replace(/\/$/, '')}/transcription-batches/${batchId}/items`)
    if (authStore.token) xhr.setRequestHeader('Authorization', `Bearer ${authStore.token}`)
    xhr.upload.onprogress = (event) => {
      const item = localItems.value.find(value => value.id === localId)
      if (item && event.lengthComputable) item.progress = Math.round(event.loaded / event.total * 100)
    }
    xhr.onload = () => {
      let data: any = null
      try { data = JSON.parse(xhr.responseText) } catch {}
      const renewedToken = xhr.getResponseHeader('X-Access-Token')
      if (renewedToken) authStore.setToken(renewedToken)
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(data as TranscriptionItem)
      } else {
        if (xhr.status === 401) {
          const currentPath = router.currentRoute.value.fullPath
          authStore.logout()
          void navigateTo(getLoginPath(currentPath))
        }
        reject(new Error(data?.detail || '音频上传失败'))
      }
    }
    xhr.onerror = () => reject(new Error('网络异常，音频上传失败'))
    const form = new FormData()
    form.append('file', file)
    form.append('sort_order', String(sortOrder))
    xhr.send(form)
  })

  const addFiles = async (files: File[], diaryDate: string) => {
    error.value = ''
    const valid: File[] = []
    for (const file of files) {
      const extension = file.name.split('.').pop()?.toLowerCase() || ''
      if (!ALLOWED_EXTENSIONS.has(extension)) {
        error.value = `${file.name}：不支持该音频格式`
        addLocalFailedItem(localItems, file, '不支持该音频格式')
        continue
      }
      if (file.size > MAX_FILE_SIZE) {
        error.value = `${file.name}：单个音频不能超过 300 MB`
        addLocalFailedItem(localItems, file, '单个音频不能超过 300 MB')
        continue
      }
      valid.push(file)
    }
    if (!valid.length) return
    const orderedFiles = orderAudioFiles(valid)
    const currentBatch = await createBatch(diaryDate)
    let nextOrder = Math.max(-1, ...items.value.map(item => item.sort_order)) + 1
    let cursor = 0
    const uploadNext = async () => {
      const file = orderedFiles[cursor++]
      if (!file) return
      const localId = createLocalId()
      const order = nextOrder++
      localItems.value.push({
        id: localId, sort_order: order, filename: file.name, file_size: file.size,
        status: 'UPLOADING', progress: 0, retry_count: 0, local: true,
      })
      try {
        const uploaded = await uploadOne(currentBatch.id, file, order, localId)
        localItems.value = localItems.value.filter(item => item.id !== localId)
        if (batch.value) batch.value.items.push(uploaded)
      } catch (err: any) {
        const item = localItems.value.find(value => value.id === localId)
        if (item) {
          item.status = 'FAILED'
          item.error_message = err.message
        }
      }
      await uploadNext()
    }
    await Promise.all(
      Array.from({ length: Math.min(MAX_UPLOAD_CONCURRENCY, orderedFiles.length) }, () => uploadNext()),
    )
  }

  const reorder = async (itemIds: string[]) => {
    if (!batch.value || batch.value.status !== 'COLLECTING' || localItems.value.length) return
    batch.value = await api<TranscriptionBatch>(`/transcription-batches/${batch.value.id}/item-order`, {
      method: 'PUT', body: { item_ids: itemIds },
    })
  }

  const removeItem = async (item: TranscriptionItem) => {
    error.value = ''
    if (item.local) {
      localItems.value = localItems.value.filter(value => value.id !== item.id)
      return
    }
    if (!batch.value) return
    await api(`/transcription-batches/${batch.value.id}/items/${item.id}`, { method: 'DELETE' })
    batch.value.items = batch.value.items.filter(value => value.id !== item.id)
    if (batch.value.status === 'PARTIAL_FAILED') await refresh()
  }

  const start = async (diaryDate: string, baseText: string) => {
    if (!batch.value || !canStart.value) return
    actionLoading.value = true
    error.value = ''
    try {
      batch.value = await api<TranscriptionBatch>(`/transcription-batches/${batch.value.id}/start`, {
        method: 'POST', body: { diary_date: diaryDate, base_text: baseText },
      })
      schedulePoll(0)
    } catch (err: any) {
      error.value = err?.data?.detail || '启动语音转写失败'
    } finally {
      actionLoading.value = false
    }
  }

  const refresh = async () => {
    if (!batch.value || ['COLLECTING', 'CANCELLED', 'EXPIRED'].includes(batch.value.status)) return
    batch.value = await api<TranscriptionBatch>(`/transcription-batches/${batch.value.id}`)
    if (['QUEUED', 'PROCESSING', 'FINALIZING'].includes(batch.value.status)) schedulePoll(2000)
  }

  const schedulePoll = (delay: number) => {
    if (import.meta.server) return
    if (pollTimer) clearTimeout(pollTimer)
    if (document.visibilityState === 'hidden') return
    pollTimer = setTimeout(() => refresh().catch((err: any) => {
      error.value = err?.data?.detail || '状态更新失败'
      schedulePoll(4000)
    }), delay)
  }

  const loadActive = async (diaryDate: string) => {
    if (locked.value) return
    error.value = ''
    const active = await api<TranscriptionBatch | null>(`/transcription-batches/active?diary_date=${encodeURIComponent(diaryDate)}`)
    if (active) {
      batch.value = active
      localItems.value = []
      if (['QUEUED', 'PROCESSING', 'FINALIZING'].includes(active.status)) schedulePoll(0)
    }
  }

  const retry = async (item?: TranscriptionItem) => {
    if (!batch.value) return
    actionLoading.value = true
    try {
      const suffix = item ? `/items/${item.id}/retry` : '/retry-failed'
      batch.value = await api<TranscriptionBatch>(`/transcription-batches/${batch.value.id}${suffix}`, { method: 'POST' })
      schedulePoll(0)
    } catch (err: any) {
      error.value = err?.data?.detail || '重试失败'
    } finally { actionLoading.value = false }
  }

  const cancel = async () => {
    if (!batch.value) return null
    actionLoading.value = true
    try {
      const restored = await api<{ diary_date: string | null; base_text: string }>(`/transcription-batches/${batch.value.id}/cancel`, { method: 'POST' })
      if (pollTimer) clearTimeout(pollTimer)
      batch.value = null
      localItems.value = []
      return restored
    } finally { actionLoading.value = false }
  }

  const onVisibility = () => {
    if (document.visibilityState === 'visible' && batch.value && ['QUEUED', 'PROCESSING', 'FINALIZING'].includes(batch.value.status)) schedulePoll(0)
  }
  onMounted(() => document.addEventListener('visibilitychange', onVisibility))
  onBeforeUnmount(() => {
    document.removeEventListener('visibilitychange', onVisibility)
    if (pollTimer) clearTimeout(pollTimer)
  })

  return { batch, items, hasAudio, uploading, canStart, locked, actionLoading, error, addFiles, reorder, removeItem, start, loadActive, retry, cancel }
}
