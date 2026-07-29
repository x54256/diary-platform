<template>
  <div class="h-dvh flex flex-col overflow-hidden">
    <!-- 顶部导航栏 -->
    <NavBar :title="diaryTitle" :show-back="true">
      <template #right>
        <button
          v-if="diary && !isEditing && !isEditingStructured"
          @click="handleDelete"
          :disabled="deleting || organizing || analyzing"
          class="text-red-500 text-sm font-medium disabled:opacity-50"
        >
          {{ deleting ? '删除中' : '删除' }}
        </button>
        <!-- 结构化编辑按钮：organized/analyzed 且非编辑模式时显示 -->
        <button
          v-if="isStructuredEditable && !isEditingStructured && !isEditing"
          @click="startEditStructured"
          class="text-primary-600 text-sm font-medium"
        >
          编辑
        </button>
        <!-- 编辑原文按钮：saved/organized 且非编辑模式时显示 -->
        <button
          v-if="isEditable && !isEditing && !isEditingStructured"
          @click="startEdit"
          class="text-primary-600 text-sm font-medium"
        >
          {{ diary?.status === 'organized' ? '编辑原文' : '编辑' }}
        </button>
      </template>
    </NavBar>

    <!-- 加载中 -->
    <div v-if="loading" class="flex-1 min-h-0 flex items-center justify-center">
      <span class="text-sm text-neutral-400">加载中...</span>
    </div>

    <!-- 未整理状态（saved）：显示原始文本 + 整理按钮 -->
    <template v-else-if="diary && !isOrganizedOrAnalyzed">
      <!-- 编辑模式 -->
      <template v-if="isEditing">
        <div class="flex-1 min-h-0 overflow-y-auto px-4 py-3">
          <div class="text-sm text-neutral-500 mb-3">{{ diary.diary_date }}</div>
          <textarea
            v-model="editText"
            data-auto-resize
            class="w-full min-h-[300px] text-sm text-neutral-800 leading-relaxed p-3 border border-neutral-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none resize-none overflow-hidden"
            @input="handleTextareaInput"
          />
          <p v-if="saveError" class="text-sm text-red-500 mt-2">{{ saveError }}</p>
        </div>
        <div class="px-4 py-3 border-t border-neutral-200 bg-white safe-area-bottom">
          <div class="flex gap-3">
            <button
              @click="cancelEdit"
              :disabled="saving"
              class="flex-1 py-2.5 rounded-lg border border-neutral-300 text-neutral-700 text-sm font-medium hover:bg-neutral-50 disabled:opacity-50"
            >
              取消
            </button>
            <button
              @click="handleSaveEdit"
              :disabled="saving"
              class="flex-1 py-2.5 rounded-lg bg-primary-600 text-white text-sm font-medium hover:bg-primary-700 disabled:opacity-50"
            >
              {{ saving ? '保存中...' : '保存' }}
            </button>
          </div>
        </div>
      </template>
      <!-- 查看模式 -->
      <template v-else>
        <div class="flex-1 min-h-0 overflow-y-auto px-4 py-3">
          <div class="text-sm text-neutral-500 mb-3">{{ diary.diary_date }}</div>
          <div class="text-sm text-neutral-800 whitespace-pre-wrap leading-relaxed">
            {{ diary.original_text }}
          </div>
        </div>
        <!-- 底部整理按钮 -->
        <div class="px-4 py-3 border-t border-neutral-200 bg-white safe-area-bottom">
          <button
            @click="handleOrganize"
            :disabled="organizing"
            class="w-full py-2.5 rounded-lg bg-primary-600 text-white text-sm font-medium hover:bg-primary-700 disabled:opacity-50"
          >
            <span v-if="organizing" class="inline-flex items-center gap-2">
              <Spinner />
              {{ organizeStep + '...' }}
            </span>
            <span v-else>AI 整理</span>
          </button>
          <p v-if="organizeError" class="text-sm text-red-500 text-center mt-2">{{ organizeError }}</p>
        </div>
      </template>
    </template>

    <!-- 已整理 / 已分析状态：显示内容 -->
    <template v-else-if="diary && isOrganizedOrAnalyzed">
      <!-- 双 Tab 切换（仅 analyzed 状态显示） -->
      <div v-if="diary.status === 'analyzed'" class="border-b border-neutral-200 bg-white">
        <div class="flex max-w-md mx-auto">
          <button
            @click="activeTab = 'diary'"
            class="flex-1 py-2.5 text-sm font-medium text-center transition-colors relative"
            :class="activeTab === 'diary' ? 'text-primary-600' : 'text-neutral-500 hover:text-neutral-700'"
          >
            日记
            <span
              v-if="activeTab === 'diary'"
              class="absolute bottom-0 left-1/2 -translate-x-1/2 w-12 h-0.5 bg-primary-600 rounded-full"
            />
          </button>
          <button
            @click="activeTab = 'analysis'"
            class="flex-1 py-2.5 text-sm font-medium text-center transition-colors relative"
            :class="activeTab === 'analysis' ? 'text-primary-600' : 'text-neutral-500 hover:text-neutral-700'"
          >
            分析
            <span
              v-if="activeTab === 'analysis'"
              class="absolute bottom-0 left-1/2 -translate-x-1/2 w-12 h-0.5 bg-primary-600 rounded-full"
            />
          </button>
        </div>
      </div>

      <!-- 日记 Tab 内容 -->
      <div v-show="activeTab === 'diary'" class="flex-1 min-h-0 overflow-y-auto px-4 py-3 pb-24">
        <!-- 编辑保存成功提示 -->
        <div
          v-if="editSaveMessage"
          class="mb-3 px-3 py-2 bg-amber-50 border border-amber-200 rounded-lg text-sm text-amber-700"
        >
          {{ editSaveMessage }}
        </div>
        <!-- 结构化编辑模式 -->
        <template v-if="isEditingStructured">
          <div class="space-y-4">
            <!-- 标题 -->
            <div>
              <label class="text-xs font-medium text-neutral-500 mb-1 block">标题</label>
              <input
                v-model="editFormData.title"
                class="w-full text-sm text-neutral-800 p-2 border border-neutral-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none"
                placeholder="日记标题"
              />
            </div>
            <!-- 摘要 -->
            <div>
              <label class="text-xs font-medium text-neutral-500 mb-1 block">摘要</label>
              <textarea
                v-model="editFormData.summary"
                rows="3"
                data-auto-resize
                class="w-full min-h-[4.5rem] text-sm text-neutral-800 leading-relaxed p-2 border border-neutral-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none resize-none overflow-hidden"
                @input="handleTextareaInput"
                placeholder="日记摘要"
              />
            </div>
            <!-- 引入段 -->
            <div>
              <label class="text-xs font-medium text-neutral-500 mb-1 block">引入段</label>
              <textarea
                v-model="editFormData.introduction"
                rows="2"
                data-auto-resize
                class="w-full min-h-[3rem] text-sm text-neutral-800 leading-relaxed p-2 border border-neutral-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none resize-none overflow-hidden"
                @input="handleTextareaInput"
                placeholder="引入段"
              />
            </div>
            <!-- 事件编辑 -->
            <div v-if="diary.organized?.events && diary.organized.events.length > 0">
              <label class="text-xs font-medium text-neutral-500 mb-2 block">事件</label>
              <EventCard
                v-for="event in sortedEvents"
                :key="event.id"
                :event="event"
                :editable="true"
                :analysis-run-id="diary.organized?.analysis?.id"
                @update="onEventUpdate"
              />
            </div>
            <!-- 琐事 -->
            <div>
              <label class="text-xs font-medium text-neutral-500 mb-1 block">琐事（每项一行）</label>
              <textarea
                v-model="editFormData.trivia"
                rows="3"
                data-auto-resize
                class="w-full min-h-[4.5rem] text-sm text-neutral-800 leading-relaxed p-2 border border-neutral-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none resize-none overflow-hidden"
                @input="handleTextareaInput"
                placeholder="每项琐事一行"
              />
            </div>
            <!-- 后续计划 -->
            <div>
              <label class="text-xs font-medium text-neutral-500 mb-1 block">后续计划（每项一行）</label>
              <textarea
                v-model="editFormData.plans"
                rows="3"
                data-auto-resize
                class="w-full min-h-[4.5rem] text-sm text-neutral-800 leading-relaxed p-2 border border-neutral-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none resize-none overflow-hidden"
                @input="handleTextareaInput"
                placeholder="每项计划一行"
              />
            </div>
            <!-- 错误提示 -->
            <p v-if="structuredSaveError" class="text-sm text-red-500">{{ structuredSaveError }}</p>
            <!-- 保存/取消按钮 -->
            <div class="flex gap-3 pt-2">
              <button
                @click="cancelEditStructured"
                :disabled="structuredSaving"
                class="flex-1 py-2.5 rounded-lg border border-neutral-300 text-neutral-700 text-sm font-medium hover:bg-neutral-50 disabled:opacity-50"
              >
                取消
              </button>
              <button
                @click="handleSaveStructured"
                :disabled="structuredSaving"
                class="flex-1 py-2.5 rounded-lg bg-primary-600 text-white text-sm font-medium hover:bg-primary-700 disabled:opacity-50"
              >
                {{ structuredSaving ? '保存中...' : '保存' }}
              </button>
            </div>
          </div>
        </template>
        <!-- organized 状态编辑原文模式 -->
        <template v-else-if="isEditing && diary.status === 'organized'">
          <div class="mb-3">
            <div class="text-sm text-neutral-500 mb-2">编辑原文</div>
            <textarea
              v-model="editText"
              data-auto-resize
              class="w-full min-h-[300px] text-sm text-neutral-800 leading-relaxed p-3 border border-neutral-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none resize-none overflow-hidden"
              @input="handleTextareaInput"
            />
            <p v-if="saveError" class="text-sm text-red-500 mt-2">{{ saveError }}</p>
          </div>
          <div class="flex gap-3 mb-4">
            <button
              @click="cancelEdit"
              :disabled="saving"
              class="flex-1 py-2.5 rounded-lg border border-neutral-300 text-neutral-700 text-sm font-medium hover:bg-neutral-50 disabled:opacity-50"
            >
              取消
            </button>
            <button
              @click="handleSaveEdit"
              :disabled="saving"
              class="flex-1 py-2.5 rounded-lg bg-primary-600 text-white text-sm font-medium hover:bg-primary-700 disabled:opacity-50"
            >
              {{ saving ? '保存中...' : '保存' }}
            </button>
          </div>
        </template>
        <!-- 正常查看模式 -->
        <template v-else>
        <!-- 元数据横排 -->
        <div class="flex flex-wrap items-center gap-x-3 gap-y-1 mb-4">
          <template v-if="displayMood">
            <span class="text-xs text-neutral-400">心情</span>
            <span class="text-xs text-primary-600 font-medium">{{ displayMood }}</span>
          </template>
          <template v-if="diary.organized?.location">
            <span class="text-xs text-neutral-400">地点</span>
            <span class="text-xs text-primary-600">{{ diary.organized.location }}</span>
          </template>
        </div>

        <!-- 日记级标签（从事件 tags 去重汇总） -->
        <div v-if="diaryLevelTags.length > 0" class="flex flex-wrap mb-4">
          <TagBadge v-for="tag in diaryLevelTags" :key="tag.id" :tag="tag" />
        </div>

        <!-- 摘要 -->
        <div
          v-if="diary.organized?.summary"
          class="text-[13px] italic text-neutral-600 leading-relaxed mb-4 pb-3 border-b border-neutral-100"
        >
          {{ diary.organized.summary }}
        </div>

        <!-- 引入段 -->
        <div
          v-if="diary.organized?.introduction"
          class="text-sm text-neutral-500 leading-relaxed mb-4"
        >
          {{ diary.organized.introduction }}
        </div>

        <!-- 事件卡片列表 -->
        <div v-if="diary.organized?.events && diary.organized.events.length > 0" class="mb-4">
          <EventCard
            v-for="event in sortedEvents"
            :key="event.id"
            :event="event"
            :editable="isEditingStructured"
            :analysis-run-id="diary.organized?.analysis?.id"
            :annotations="annotations"
            @update="onEventUpdate"
            @annotation-select="openAnnotationSelection"
            @annotation-clicked="openAnnotationById"
          />
        </div>

        <!-- 琐事（平铺） -->
        <div v-if="diary.organized?.trivia && diary.organized.trivia.length > 0" class="mb-3">
          <div class="text-base font-medium text-neutral-800 mb-2">琐事</div>
          <ol v-if="diary.organized.trivia.length > 1" class="list-decimal list-inside space-y-1.5">
            <li
              v-for="(item, idx) in diary.organized.trivia"
              :key="idx"
              class="text-[14px] text-neutral-600 leading-relaxed"
            >
              {{ item }}
            </li>
          </ol>
          <ul v-else class="list-none space-y-1.5">
            <li class="text-[14px] text-neutral-600 leading-relaxed">
              {{ diary.organized.trivia[0] }}
            </li>
          </ul>
        </div>

        <!-- 后续计划（平铺） -->
        <div v-if="diary.organized?.plans && diary.organized.plans.length > 0" class="mb-3">
          <div class="text-base font-medium text-neutral-800 mb-2">后续计划</div>
          <ol v-if="diary.organized.plans.length > 1" class="list-decimal list-inside space-y-1.5">
            <li
              v-for="(item, idx) in diary.organized.plans"
              :key="idx"
              class="text-[14px] text-neutral-600 leading-relaxed"
            >
              {{ item }}
            </li>
          </ol>
          <ul v-else class="list-none space-y-1.5">
            <li class="text-[14px] text-neutral-600 leading-relaxed">
              {{ diary.organized.plans[0] }}
            </li>
          </ul>
        </div>

        <!-- 原始文本（折叠，默认收起） -->
        <details class="border-t border-neutral-100 pt-3">
          <summary class="text-xs text-neutral-400 cursor-pointer">查看原始文本</summary>
          <div class="mt-2 text-xs text-neutral-500 whitespace-pre-wrap leading-relaxed font-mono">
            {{ diary.original_text }}
          </div>
        </details>
        </template>
      </div>

      <!-- 分析 Tab 内容 -->
      <div v-show="activeTab === 'analysis'" class="flex-1 min-h-0 overflow-y-auto px-4 py-3 pb-20">
        <AnalysisTab
          v-if="diary.organized?.analysis"
          :analysis="diary.organized.analysis"
          :annotations="annotations"
          @annotation-select="openAnnotationSelection"
          @annotation-clicked="openAnnotationById"
        />
        <div v-else class="flex items-center justify-center py-12">
          <span class="text-sm text-neutral-400">暂无分析数据</span>
        </div>
      </div>

      <!-- 底部操作区（编辑模式下隐藏） -->
      <div v-if="!isEditingStructured" class="fixed bottom-0 left-0 right-0 px-4 py-2 border-t border-neutral-200 bg-white safe-area-bottom">
        <div class="max-w-md mx-auto">
          <!-- 分析中状态 -->
          <div v-if="analyzing" class="flex items-center justify-center gap-2 py-2">
            <Spinner />
            <span class="text-sm text-neutral-500">{{ analyzeStep }}...</span>
          </div>
          <!-- 操作按钮 -->
          <div v-else class="flex items-center gap-2">
            <!-- 对话输入（日记 Tab 时显示） -->
            <template v-if="activeTab === 'diary' || diary.status !== 'analyzed'">
              <input
                v-model="dialogInput"
                type="text"
                placeholder="围绕这篇日记展开对话..."
                class="flex-1 px-3 py-2 rounded-full bg-neutral-100 text-sm text-neutral-800 placeholder-neutral-400"
              />
              <button class="w-8 h-8 rounded-full bg-primary-600 text-white text-sm flex items-center justify-center shrink-0">
                →
              </button>
            </template>
            <!-- AI 分析按钮（organized 状态） -->
            <button
              v-if="diary.status === 'organized'"
              @click="handleAnalyze"
              class="px-4 py-2 rounded-lg bg-primary-600 text-white text-sm font-medium hover:bg-primary-700 shrink-0"
            >
              AI 分析
            </button>
            <!-- 重新分析按钮（analyzed 状态） -->
            <button
              v-if="diary.status === 'analyzed'"
              @click="handleAnalyze"
              class="px-3 py-2 rounded-lg border border-neutral-200 text-sm text-neutral-600 hover:bg-neutral-50 shrink-0"
            >
              重新分析
            </button>
          </div>
          <p v-if="analyzeError" class="text-xs text-red-500 text-center mt-1">{{ analyzeError }}</p>
        </div>
      </div>
    </template>

    <!-- 未找到 -->
    <div v-else class="flex-1 min-h-0 flex items-center justify-center">
      <span class="text-sm text-neutral-400">日记不存在</span>
    </div>

    <NuxtLink
      v-if="diary?.diary_date && !isEditing && !isEditingStructured"
      :to="`/diary/new?date=${diary.diary_date}`"
      class="fixed bottom-20 right-4 w-12 h-12 rounded-full bg-primary-600 text-white text-2xl flex items-center justify-center shadow-lg hover:bg-primary-700 transition-colors"
    >
      +
    </NuxtLink>

    <!-- 选中文本后的浮动操作栏 -->
    <Teleport to="body">
      <div
        v-if="selectionToolbarOpen"
        ref="selectionToolbarRef"
        class="fixed z-50 flex w-32 items-stretch overflow-hidden rounded-md bg-neutral-700 text-white shadow-lg"
        :style="selectionToolbarStyle"
        @mousedown.prevent
        @click.stop
      >
        <button
          type="button"
          class="flex flex-1 flex-col items-center gap-0.5 px-2 py-1.5 text-xs hover:bg-neutral-600 disabled:opacity-50"
          :class="annotationActionOpen ? 'text-green-400' : 'text-white'"
          :disabled="annotationSaving"
          @click="annotationActionOpen ? deleteAnnotationFromAction() : saveAnnotation(false)"
        >
          <span class="text-base leading-4">▔</span>
          <span>划线</span>
        </button>
        <button
          type="button"
          class="flex flex-1 flex-col items-center gap-0.5 px-2 py-1.5 text-xs hover:bg-neutral-600 disabled:opacity-50"
          :disabled="annotationSaving"
          @click="annotationActionOpen ? showAnnotationCommentEditorFromAction() : showAnnotationCommentEditor()"
        >
          <span class="text-base leading-4">✎</span>
          <span>{{ annotationActionOpen ? '评论' : '写评论' }}</span>
        </button>
      </div>
    </Teleport>

    <!-- 选择文字后写评论：只显示底部输入栏 -->
    <Teleport to="body">
      <div
        v-if="selectionCommentBarOpen"
        class="fixed bottom-0 left-0 right-0 z-50 border-t border-neutral-200 bg-white px-4 py-3 safe-area-bottom"
      >
        <div class="mx-auto flex max-w-md gap-2">
          <input
            ref="annotationCommentInput"
            v-model="annotationCommentText"
            type="text"
            placeholder="写评论……"
            class="min-w-0 flex-1 rounded-full bg-neutral-100 px-4 py-2 text-base text-neutral-800 placeholder-neutral-400"
            @keyup.enter="saveAnnotationComment"
          />
          <button
            type="button"
            class="shrink-0 rounded-full bg-primary-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
            :disabled="annotationSaving || !annotationCommentText.trim()"
            @click="saveAnnotationComment"
          >
            提交
          </button>
        </div>
        <p v-if="annotationError" class="mx-auto mt-1 max-w-md text-center text-xs text-red-500">{{ annotationError }}</p>
      </div>
    </Teleport>

    <!-- 点击已有划线后的全屏评论查看层 -->
    <Teleport to="body">
      <div
        v-if="annotationPanelOpen"
        class="fixed inset-0 z-50 bg-black/45"
      >
        <section
          class="absolute bottom-0 left-0 right-0 mx-auto flex h-[100dvh] max-h-[100dvh] w-full flex-col overflow-hidden rounded-t-2xl bg-white shadow-2xl"
          :style="annotationViewerSheetStyle"
          @click.stop
        >
          <div
            class="flex shrink-0 cursor-grab touch-none justify-center py-4 active:cursor-grabbing"
            @pointerdown="startAnnotationViewerDrag"
            @pointermove="moveAnnotationViewerDrag"
            @pointerup="endAnnotationViewerDrag"
            @pointercancel="endAnnotationViewerDrag"
          >
            <span class="h-1 w-12 rounded-full bg-neutral-300" />
          </div>

          <div class="min-h-0 flex-1 overflow-y-auto px-4 pb-3">
            <blockquote class="border-l-2 border-primary-500 pl-3 text-sm leading-relaxed text-neutral-700">
              {{ annotationPanelQuote }}
            </blockquote>

            <div class="pt-5">
              <div class="mb-3 text-base font-medium text-neutral-800">
                评论 {{ annotationPanelComments.length }}
              </div>
              <div v-if="annotationPanelComments.length" class="space-y-3">
                <div
                  v-for="item in annotationPanelComments"
                  :key="`${item.annotation.id}-${item.comment.id}`"
                  class="border-b border-neutral-100 pb-3"
                >
                  <div class="mb-1 flex items-center justify-between gap-2">
                    <div class="text-xs text-neutral-400">{{ formatAnnotationTime(item.comment.created_at) }}</div>
                    <button
                      type="button"
                      class="shrink-0 text-xs text-red-500 disabled:opacity-50"
                      :disabled="annotationSaving"
                      @click="deleteAnnotationComment(item.annotation.id, item.comment.id)"
                    >
                      删除
                    </button>
                  </div>
                  <p class="whitespace-pre-wrap text-sm leading-relaxed text-neutral-700">{{ item.comment.content }}</p>
                </div>
              </div>
              <p v-else class="py-4 text-center text-sm text-neutral-400">暂无评论</p>
            </div>
          </div>

          <div class="flex shrink-0 gap-2 border-t border-neutral-100 bg-white px-4 py-3 safe-area-bottom">
            <input
              ref="annotationViewerCommentInput"
              v-model="annotationCommentText"
              type="text"
              placeholder="写评论……"
              class="min-w-0 flex-1 rounded-full bg-neutral-100 px-4 py-2 text-base text-neutral-800 placeholder-neutral-400"
              @keyup.enter="saveAnnotationComment"
            />
            <button
              type="button"
              class="shrink-0 rounded-full bg-primary-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
              :disabled="annotationSaving || !annotationCommentText.trim()"
              @click="saveAnnotationComment"
            >
              发送
            </button>
          </div>
          <p v-if="annotationError" class="shrink-0 px-4 pb-2 text-center text-xs text-red-500">{{ annotationError }}</p>
        </section>
      </div>
    </Teleport>

  </div>
</template>

<script setup lang="ts">
// 日记详情页：支持双 Tab（日记 + 分析）

import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { resizeTextarea, resizeTextareas } from '~/composables/useAutoResizeTextarea'
import type { DiaryAnnotation, DiaryAnnotationClick, DiaryAnnotationSelection } from '~/types'

definePageMeta({
  layout: 'auth',
  middleware: 'auth',
})

const route = useRoute()
const { api } = useApi()
const diaryId = computed(() => route.params.id as string)

// ───────────────── 类型导入 ─────────────────
// Nuxt auto-imports types from types/index.ts

// ───────────────── 核心数据 ─────────────────
const diary = ref<Diary | null>(null)
const loading = ref(true)
const activeTab = ref<'diary' | 'analysis'>('diary')
const annotations = ref<DiaryAnnotation[]>([])

const annotationPanelOpen = ref(false)
const selectionToolbarOpen = ref(false)
const selectionToolbarRef = ref<HTMLElement | null>(null)
const selectionToolbarStyle = ref<Record<string, string>>({ top: '8px', left: '8px' })
const selectionCommentBarOpen = ref(false)
const annotationPanelMode = ref<'selection' | 'existing'>('selection')
const annotationSelection = ref<DiaryAnnotationSelection | null>(null)
const annotationClickQuote = ref('')
const annotationActionOpen = ref(false)
const annotationActionId = ref<string | null>(null)
const activeAnnotationId = ref<string | null>(null)
const annotationCommentText = ref('')
const annotationSaving = ref(false)
const annotationError = ref('')
const annotationCommentInput = ref<HTMLInputElement | null>(null)
const annotationViewerCommentInput = ref<HTMLInputElement | null>(null)
const annotationViewerDragStartY = ref<number | null>(null)
const annotationViewerDragOffset = ref(0)
const annotationViewerDragging = ref(false)

// 状态判断
const isOrganizedOrAnalyzed = computed(() =>
  diary.value?.status === 'organized' || diary.value?.status === 'analyzed'
)

// 可编辑判断：仅 saved / organized 可编辑
const isEditable = computed(() =>
  diary.value?.status === 'saved' || diary.value?.status === 'organized'
)

// 标题
const diaryTitle = computed(() => {
  if (!diary.value) return '日记详情'
  if (diary.value.organized?.title) return diary.value.organized.title
  return diary.value.diary_date
})

// 心情展示：已分析取 analysis.mood，否则取 organized.mood
const displayMood = computed(() => {
  if (!diary.value?.organized) return null
  return diary.value.organized.analysis?.mood || diary.value.organized.mood
})

// 事件按 sort_order 排序
const sortedEvents = computed(() => {
  const events = diary.value?.organized?.events || []
  return [...events].sort((a, b) => a.sort_order - b.sort_order)
})

// 标签按类别排序：领域 → 主题 → 人物/对象 → 心理 → 知识点
const TAG_TYPE_ORDER: Record<string, number> = {
  domain: 0,
  topic: 1,
  person_object: 2,
  psychological: 3,
  knowledge: 4,
}

// 日记级标签：从所有事件的 tags 中去重汇总
const diaryLevelTags = computed<Tag[]>(() => {
  const events = diary.value?.organized?.events || []
  const seen = new Set<string>()
  const tags: Tag[] = []
  for (const event of events) {
    if (!event.tags) continue
    for (const tag of event.tags) {
      const key = `${tag.type}:${tag.name}`
      if (!seen.has(key)) {
        seen.add(key)
        tags.push(tag)
      }
    }
  }
  return tags.sort((a, b) => {
    const orderA = TAG_TYPE_ORDER[a.type] ?? 99
    const orderB = TAG_TYPE_ORDER[b.type] ?? 99
    return orderA - orderB
  })
})

const activeAnnotation = computed(() =>
  annotations.value.find(annotation => annotation.id === activeAnnotationId.value) || null,
)

const annotationPanelQuote = computed(() =>
  annotationSelection.value?.selected_text || annotationClickQuote.value || activeAnnotation.value?.selected_text || '',
)

const sameAnnotationSource = (left: DiaryAnnotation, right: DiaryAnnotation) =>
  left.target_type === right.target_type
  && left.event_id === right.event_id
  && left.analysis_item_id === right.analysis_item_id
  && left.field_name === right.field_name

const compareAnnotationPoint = (
  paragraph: number,
  offset: number,
  otherParagraph: number,
  otherOffset: number,
) => paragraph - otherParagraph || offset - otherOffset

const annotationsOverlap = (left: DiaryAnnotation, right: DiaryAnnotation) => {
  if (!sameAnnotationSource(left, right)) return false
  const leftBeforeRight = compareAnnotationPoint(
    left.end_paragraph,
    left.end_offset,
    right.start_paragraph,
    right.start_offset,
  ) <= 0
  const rightBeforeLeft = compareAnnotationPoint(
    right.end_paragraph,
    right.end_offset,
    left.start_paragraph,
    left.start_offset,
  ) <= 0
  return !leftBeforeRight && !rightBeforeLeft
}

const annotationPanelAnnotations = computed(() => {
  if (!activeAnnotation.value) return []
  return annotations.value.filter(annotation => annotationsOverlap(annotation, activeAnnotation.value!))
})

const annotationPanelComments = computed(() =>
  annotationPanelAnnotations.value.flatMap(annotation =>
    annotation.comments.map(comment => ({ annotation, comment })),
  ).sort((left, right) =>
    new Date(left.comment.created_at).getTime() - new Date(right.comment.created_at).getTime(),
  ),
)

const annotationViewerSheetStyle = computed(() => ({
  transform: `translateY(${annotationViewerDragOffset.value}px)`,
  transition: annotationViewerDragging.value ? 'none' : 'transform 180ms ease-out',
}))

const formatAnnotationTime = (value: string) => {
  const time = new Date(value)
  if (Number.isNaN(time.getTime())) return value
  return time.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

const startAnnotationViewerDrag = (event: PointerEvent) => {
  annotationViewerDragStartY.value = event.clientY
  annotationViewerDragOffset.value = 0
  annotationViewerDragging.value = true
  ;(event.currentTarget as HTMLElement)?.setPointerCapture?.(event.pointerId)
}

const moveAnnotationViewerDrag = (event: PointerEvent) => {
  if (annotationViewerDragStartY.value === null) return
  annotationViewerDragOffset.value = Math.max(0, event.clientY - annotationViewerDragStartY.value)
}

const endAnnotationViewerDrag = () => {
  if (annotationViewerDragStartY.value === null) return
  const shouldClose = annotationViewerDragOffset.value >= 100
  annotationViewerDragStartY.value = null
  annotationViewerDragging.value = false
  if (shouldClose) {
    closeAnnotationPanel()
  } else {
    annotationViewerDragOffset.value = 0
  }
}

const updateSelectionToolbarPosition = () => {
  const selection = window.getSelection()
  if (!selection || selection.rangeCount === 0) return
  const rect = selection.getRangeAt(0).getBoundingClientRect()
  const toolbarWidth = 128
  const toolbarHeight = 56
  const gap = 8
  const left = Math.min(
    Math.max(gap, rect.left + (rect.width - toolbarWidth) / 2),
    window.innerWidth - toolbarWidth - gap,
  )
  const top = rect.top >= toolbarHeight + gap
    ? rect.top - toolbarHeight - gap
    : Math.min(rect.bottom + gap, window.innerHeight - toolbarHeight - gap)
  selectionToolbarStyle.value = {
    top: `${Math.max(gap, top)}px`,
    left: `${Math.max(gap, left)}px`,
  }
}

const updateAnnotationToolbarPosition = (clientX: number, clientY: number) => {
  const toolbarWidth = 128
  const toolbarHeight = 56
  const gap = 8
  const left = Math.min(
    Math.max(gap, clientX - toolbarWidth / 2),
    window.innerWidth - toolbarWidth - gap,
  )
  const top = clientY >= toolbarHeight + gap
    ? clientY - toolbarHeight - gap
    : Math.min(clientY + gap, window.innerHeight - toolbarHeight - gap)
  selectionToolbarStyle.value = {
    top: `${Math.max(gap, top)}px`,
    left: `${Math.max(gap, left)}px`,
  }
}

const clearPendingSelectionHighlight = () => {
  const highlights = (window.CSS as typeof window.CSS & {
    highlights?: { delete: (name: string) => void }
  }).highlights
  highlights?.delete('pending-annotation-selection')
}

const updatePendingSelectionHighlight = () => {
  const selection = window.getSelection()
  if (!selection || selection.rangeCount === 0 || selection.isCollapsed) {
    clearPendingSelectionHighlight()
    return
  }
  const highlights = (window.CSS as typeof window.CSS & {
    highlights?: {
      set: (name: string, highlight: unknown) => void
    }
  }).highlights
  const HighlightConstructor = (window as typeof window & {
    Highlight?: new (...ranges: Range[]) => unknown
  }).Highlight
  if (!highlights || !HighlightConstructor) return
  highlights.set(
    'pending-annotation-selection',
    new HighlightConstructor(selection.getRangeAt(0).cloneRange()),
  )
}

const closeSelectionToolbar = () => {
  selectionToolbarOpen.value = false
  clearPendingSelectionHighlight()
  if (!annotationPanelOpen.value) {
    annotationSelection.value = null
    annotationError.value = ''
  }
}

const handleDocumentPointerDown = (event: PointerEvent) => {
  if (!selectionToolbarOpen.value) return
  const target = event.target as Node | null
  if (target && selectionToolbarRef.value?.contains(target)) return
  if (annotationActionOpen.value) closeAnnotationAction()
  else closeSelectionToolbar()
}

const handleDocumentScroll = () => {
  if (selectionToolbarOpen.value) closeSelectionToolbar()
}

// ───────────────── 加载日记 ─────────────────
const loadAnnotations = async () => {
  if (!diary.value || diary.value.status === 'saved') {
    annotations.value = []
    return
  }
  try {
    annotations.value = await api<DiaryAnnotation[]>(`/diaries/${diaryId.value}/annotations`)
  } catch (err) {
    console.error('加载日记批注失败', err)
    annotations.value = []
  }
}

const loadDiary = async () => {
  loading.value = true
  try {
    diary.value = await api<Diary>(`/diaries/${diaryId.value}`)
    await loadAnnotations()
  } catch (err) {
    console.error('加载日记失败', err)
    diary.value = null
    annotations.value = []
  } finally {
    loading.value = false
  }
}

const openAnnotationSelection = (selection: DiaryAnnotationSelection) => {
  annotationSelection.value = selection
  annotationClickQuote.value = ''
  clearPendingSelectionHighlight()
  annotationActionOpen.value = false
  annotationActionId.value = null
  annotationPanelMode.value = 'selection'
  activeAnnotationId.value = null
  selectionCommentBarOpen.value = false
  annotationCommentText.value = ''
  annotationError.value = ''
  annotationPanelOpen.value = false
  selectionToolbarOpen.value = true
  nextTick(updateSelectionToolbarPosition)
}

const openAnnotationById = (payload: DiaryAnnotationClick) => {
  const annotation = annotations.value.find(item => item.id === payload.annotationId)
  if (!annotation) return
  annotationSelection.value = null
  annotationClickQuote.value = payload.selectedText
  selectionToolbarOpen.value = false
  selectionCommentBarOpen.value = false
  annotationCommentText.value = ''
  annotationError.value = ''
  if (annotation.comments.length === 0) {
    annotationActionId.value = annotation.id
    annotationActionOpen.value = true
    updateAnnotationToolbarPosition(payload.clientX, payload.clientY)
    selectionToolbarOpen.value = true
    return
  }
  annotationPanelMode.value = 'existing'
  activeAnnotationId.value = annotation.id
  annotationViewerDragOffset.value = 0
  annotationViewerDragging.value = false
  annotationPanelOpen.value = true
}

const closeAnnotationAction = () => {
  annotationActionOpen.value = false
  annotationActionId.value = null
  annotationClickQuote.value = ''
  selectionToolbarOpen.value = false
}

const updateAnnotation = (saved: DiaryAnnotation) => {
  const index = annotations.value.findIndex(annotation => annotation.id === saved.id)
  if (index >= 0) annotations.value[index] = saved
}

const deleteAnnotationFromAction = async () => {
  const annotationId = annotationActionId.value
  if (!annotationId || annotationSaving.value) return
  annotationSaving.value = true
  annotationError.value = ''
  try {
    await api<DiaryAnnotation>(
      `/diaries/${diaryId.value}/annotations/${annotationId}`,
      { method: 'DELETE' },
    )
    annotations.value = annotations.value.filter(annotation => annotation.id !== annotationId)
    closeAnnotationAction()
  } catch (err: any) {
    annotationError.value = err?.data?.detail || '取消划线失败，请稍后重试'
  } finally {
    annotationSaving.value = false
  }
}

const showAnnotationCommentEditorFromAction = () => {
  const annotationId = annotationActionId.value
  if (!annotationId) return
  closeAnnotationAction()
  activeAnnotationId.value = annotationId
  annotationPanelMode.value = 'existing'
  selectionCommentBarOpen.value = true
  nextTick(() => annotationCommentInput.value?.focus())
}

const closeAnnotationPanel = () => {
  annotationPanelOpen.value = false
  selectionCommentBarOpen.value = false
  closeSelectionToolbar()
  annotationSelection.value = null
  annotationClickQuote.value = ''
  activeAnnotationId.value = null
  annotationCommentText.value = ''
  annotationError.value = ''
  annotationViewerDragOffset.value = 0
  annotationViewerDragStartY.value = null
  annotationViewerDragging.value = false
}

const showAnnotationCommentEditor = () => {
  updatePendingSelectionHighlight()
  selectionToolbarOpen.value = false
  selectionCommentBarOpen.value = true
  nextTick(() => annotationCommentInput.value?.focus())
}

const saveAnnotation = async (withComment: boolean) => {
  if (!annotationSelection.value || annotationSaving.value) return
  const comment = annotationCommentText.value.trim()
  if (withComment && !comment) {
    annotationError.value = '请输入评论内容'
    return
  }
  annotationSaving.value = true
  annotationError.value = ''
  try {
    const saved = await api<DiaryAnnotation>(`/diaries/${diaryId.value}/annotations`, {
      method: 'POST',
      body: { ...annotationSelection.value, comment: withComment ? comment : null },
    })
    const index = annotations.value.findIndex(annotation => annotation.id === saved.id)
    if (index >= 0) annotations.value[index] = saved
    else annotations.value.push(saved)
    closeAnnotationPanel()
  } catch (err: any) {
    annotationError.value = err?.data?.detail || '保存批注失败，请稍后重试'
  } finally {
    annotationSaving.value = false
  }
}

const saveAnnotationComment = async () => {
  const content = annotationCommentText.value.trim()
  if (!content || annotationSaving.value) return
  if (annotationPanelMode.value === 'selection') {
    await saveAnnotation(true)
    return
  }
  if (!activeAnnotationId.value) return
  annotationSaving.value = true
  annotationError.value = ''
  try {
    const saved = await api<DiaryAnnotation>(
      `/diaries/${diaryId.value}/annotations/${activeAnnotationId.value}/comments`,
      { method: 'POST', body: { content } },
    )
    updateAnnotation(saved)
    annotationCommentText.value = ''
  } catch (err: any) {
    annotationError.value = err?.data?.detail || '保存评论失败，请稍后重试'
  } finally {
    annotationSaving.value = false
  }
}

const deleteAnnotationComment = async (annotationId: string, commentId: string) => {
  if (annotationSaving.value) return
  if (!window.confirm('确定删除这条评论吗？')) return
  annotationSaving.value = true
  annotationError.value = ''
  try {
    const saved = await api<DiaryAnnotation>(
      `/diaries/${diaryId.value}/annotations/${annotationId}/comments/${commentId}`,
      { method: 'DELETE' },
    )
    updateAnnotation(saved)
    if (saved.comments.length === 0) closeAnnotationPanel()
  } catch (err: any) {
    annotationError.value = err?.data?.detail || '删除评论失败，请稍后重试'
  } finally {
    annotationSaving.value = false
  }
}

// ───────────────── 删除日记 ─────────────────
const deleting = ref(false)

const handleDelete = async () => {
  if (!diary.value || deleting.value) return
  const confirmed = window.confirm('确定删除这篇日记吗？删除后不可恢复。')
  if (!confirmed) return

  deleting.value = true
  try {
    await api(`/diaries/${diaryId.value}`, { method: 'DELETE' })
    await navigateTo('/')
  } catch (err: any) {
    window.alert(err?.data?.detail || '删除失败，请稍后重试')
  } finally {
    deleting.value = false
  }
}

// ───────────────── 编辑原文 ─────────────────
const isEditing = ref(false)
const editText = ref('')
const saving = ref(false)
const saveError = ref('')
const editSaveMessage = ref('')

const handleTextareaInput = (event: Event) => {
  resizeTextarea(event.target as HTMLTextAreaElement)
}

// ───────────────── 结构化编辑 ─────────────────
const isStructuredEditable = computed(() =>
  diary.value?.status === 'organized' || diary.value?.status === 'analyzed'
)
const isEditingStructured = ref(false)
const editFormData = ref<any>(null)
const structuredSaving = ref(false)
const structuredSaveError = ref('')
const editedEvents = ref<Map<string, any>>(new Map())

const onEventUpdate = (eventData: any) => {
  editedEvents.value.set(eventData.id, eventData)
}

const startEdit = () => {
  editText.value = diary.value?.original_text ?? ''
  saveError.value = ''
  editSaveMessage.value = ''
  isEditing.value = true
  nextTick(() => resizeTextareas())
}

const cancelEdit = () => {
  isEditing.value = false
  saveError.value = ''
  editSaveMessage.value = ''
}

const handleSaveEdit = async () => {
  saving.value = true
  saveError.value = ''
  const wasOrganized = diary.value?.status === 'organized'
  try {
    await api<Diary>(`/diaries/${diaryId.value}`, {
      method: 'PUT',
      body: { original_text: editText.value },
    })
    isEditing.value = false
    await loadDiary()
    if (wasOrganized) {
      editSaveMessage.value = '原文已修改，如需同步结构化内容请重新整理'
      setTimeout(() => { editSaveMessage.value = '' }, 5000)
    }
  } catch (err: any) {
    saveError.value = err?.data?.detail || '保存失败，请稍后重试'
  } finally {
    saving.value = false
  }
}

// ───────────────── 结构化编辑函数 ─────────────────
const startEditStructured = () => {
  const org = diary.value?.organized
  if (!org) return
  editFormData.value = {
    title: org.title ?? '',
    summary: org.summary ?? '',
    introduction: org.introduction ?? '',
    trivia: (org.trivia ?? []).join('\n'),
    plans: (org.plans ?? []).join('\n'),
  }
  structuredSaveError.value = ''
  editedEvents.value.clear()
  isEditingStructured.value = true
  nextTick(() => resizeTextareas())
}

onMounted(() => {
  resizeTextareas()
  document.addEventListener('pointerdown', handleDocumentPointerDown, true)
  window.addEventListener('scroll', handleDocumentScroll, true)
})

onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', handleDocumentPointerDown, true)
  window.removeEventListener('scroll', handleDocumentScroll, true)
})

const cancelEditStructured = () => {
  isEditingStructured.value = false
  editFormData.value = null
  structuredSaveError.value = ''
  editedEvents.value.clear()
}

const handleSaveStructured = async () => {
  structuredSaving.value = true
  structuredSaveError.value = ''
  try {
    const body: any = {
      title: editFormData.value.title,
      summary: editFormData.value.summary,
      introduction: editFormData.value.introduction,
      trivia: editFormData.value.trivia.split('\n').filter((s: string) => s.trim()),
      plans: editFormData.value.plans.split('\n').filter((s: string) => s.trim()),
    }
    if (editedEvents.value.size > 0) {
      body.events = Array.from(editedEvents.value.values())
    }
    await api(`/diaries/${diaryId.value}/organized`, {
      method: 'PUT',
      body: body,
    })
    isEditingStructured.value = false
    editFormData.value = null
    editedEvents.value.clear()
    await loadDiary()
  } catch (err: any) {
    structuredSaveError.value = err?.data?.detail || '保存失败，请稍后重试'
  } finally {
    structuredSaving.value = false
  }
}

// ───────────────── AI 整理 ─────────────────
const organizing = ref(false)
const organizeError = ref('')
const organizeStep = ref('')

const STEP_LABELS: Record<string, string> = {
  text_cleaning: '文本清洗中',
  clean_checking: '清洗审核中',
  event_organizing: '事件识别与归类中',
  structuring: '结构化整理中',
  content_checking: '内容审核与修正中',
}
const STEP_KEYS = Object.keys(STEP_LABELS)

const formatStep = (stepKey: string) => {
  const idx = STEP_KEYS.indexOf(stepKey)
  const label = STEP_LABELS[stepKey] || stepKey
  if (idx === -1) return label
  return `${idx + 1}/${STEP_KEYS.length} ${label}`
}

const handleOrganize = async () => {
  organizing.value = true
  organizeError.value = ''
  organizeStep.value = formatStep('text_cleaning')
  try {
    await api(`/diaries/${diaryId.value}/organize`, { method: 'POST' })
    await pollOrganizeStatus()
  } catch (err: any) {
    organizeError.value = err?.data?.detail || '整理启动失败'
    organizing.value = false
  }
}

const pollOrganizeStatus = async () => {
  const maxAttempts = 200
  let consecutiveErrors = 0
  for (let i = 0; i < maxAttempts; i++) {
    await new Promise(resolve => setTimeout(resolve, 3000))
    try {
      const task = await api<{ status: string; current_step?: string; error_message?: string }>(
        `/diaries/${diaryId.value}/organize/status`
      )
      consecutiveErrors = 0
      if (task.current_step) {
        organizeStep.value = formatStep(task.current_step)
      }
      if (task.status === 'completed') {
        await loadDiary()
        organizing.value = false
        return
      }
      if (task.status === 'failed') {
        organizeError.value = task.error_message || 'AI 整理失败，请重试'
        organizing.value = false
        return
      }
    } catch {
      consecutiveErrors++
      if (consecutiveErrors >= 5) {
        organizeError.value = '网络异常，请检查连接后重试'
        organizing.value = false
        return
      }
    }
  }
  organizeError.value = '整理超时，请稍后重试'
  organizing.value = false
}

// ───────────────── AI 分析 ─────────────────
const analyzing = ref(false)
const analyzeError = ref('')
const analyzeStep = ref('')

const ANALYZE_STEP_LABELS: Record<string, string> = {
  analysis_generating: '生成分析',
  saving_result: '保存分析结果',
}
const ANALYZE_STEP_KEYS = Object.keys(ANALYZE_STEP_LABELS)

const formatAnalyzeStep = (stepKey: string) => {
  const idx = ANALYZE_STEP_KEYS.indexOf(stepKey)
  const label = ANALYZE_STEP_LABELS[stepKey] || stepKey
  if (idx === -1) return label
  return `${idx + 1}/${ANALYZE_STEP_KEYS.length} ${label}`
}

const handleAnalyze = async () => {
  analyzing.value = true
  analyzeError.value = ''
  analyzeStep.value = formatAnalyzeStep('analysis_generating')
  try {
    await api(`/diaries/${diaryId.value}/analyze`, { method: 'POST' })
    await pollAnalyzeStatus()
  } catch (err: any) {
    analyzeError.value = err?.data?.detail || '分析启动失败'
    analyzing.value = false
  }
}

const pollAnalyzeStatus = async () => {
  const maxAttempts = 200
  let consecutiveErrors = 0
  for (let i = 0; i < maxAttempts; i++) {
    await new Promise(resolve => setTimeout(resolve, 2000))
    try {
      const task = await api<{ status: string; current_step?: string; error_message?: string }>(
        `/diaries/${diaryId.value}/analyze/status`
      )
      consecutiveErrors = 0
      if (task.current_step) {
        analyzeStep.value = formatAnalyzeStep(task.current_step)
      }
      if (task.status === 'completed') {
        await loadDiary()
        activeTab.value = 'analysis'
        analyzing.value = false
        return
      }
      if (task.status === 'failed') {
        analyzeError.value = task.error_message || 'AI 分析失败，请重试'
        analyzing.value = false
        return
      }
    } catch {
      consecutiveErrors++
      if (consecutiveErrors >= 5) {
        analyzeError.value = '网络异常，请检查连接后重试'
        analyzing.value = false
        return
      }
    }
  }
  analyzeError.value = '分析超时，请稍后重试'
  analyzing.value = false
}

// ───────────────── 检查未完成任务 ─────────────────
const checkOrganizeStatus = async () => {
  try {
    const task = await api<{ status: string; current_step?: string }>(
      `/diaries/${diaryId.value}/organize/status`
    )
    if (task.status === 'running') {
      organizing.value = true
      if (task.current_step) {
        organizeStep.value = formatStep(task.current_step)
      }
      pollOrganizeStatus()
    }
  } catch { /* 无任务，忽略 */ }
}

const checkAnalyzeStatus = async () => {
  try {
    const task = await api<{ status: string; current_step?: string }>(
      `/diaries/${diaryId.value}/analyze/status`
    )
    if (task.status === 'running') {
      analyzing.value = true
      if (task.current_step) {
        analyzeStep.value = formatAnalyzeStep(task.current_step)
      }
      pollAnalyzeStatus()
    }
  } catch { /* 无任务，忽略 */ }
}

// ───────────────── 对话输入 ─────────────────
const dialogInput = ref('')

// ───────────────── Spinner 组件（内联） ─────────────────
const Spinner = defineComponent({
  setup() {
    return () => h('span', {
      class: 'inline-block w-4 h-4 border-2 border-neutral-300 border-t-primary-600 rounded-full animate-spin',
    })
  },
})

// ───────────────── 初始化 ─────────────────
onMounted(async () => {
  await loadDiary()
  if (diary.value) {
    if (diary.value.status === 'saved') {
      checkOrganizeStatus()
    }
    if (diary.value.status === 'organized' || diary.value.status === 'analyzed') {
      checkAnalyzeStatus()
    }
  }
})
</script>
