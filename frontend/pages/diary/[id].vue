<template>
  <div class="relative h-dvh flex flex-col overflow-hidden">
    <!-- 顶部导航栏 -->
    <NavBar :title="diaryTitle" :show-back="true">
      <template #title>
        <input
          v-if="inlineEditingField === 'title'"
          :value="inlineDraft"
          class="min-w-0 w-full truncate whitespace-nowrap rounded border border-primary-300 px-2 py-1 text-base font-medium text-neutral-800 outline-none focus:ring-2 focus:ring-primary-500"
          aria-label="编辑日记标题"
          @input="updateInlineDraft"
          @keyup.enter="saveInlineOrganizedField('title')"
          @keyup.esc="cancelInlineEdit"
        />
        <h1
          v-else
          class="block cursor-text truncate whitespace-nowrap text-lg font-medium text-neutral-800"
          @dblclick="diary?.organized && startInlineEdit('title', diary.organized.title || '')"
        >
          {{ diaryTitle }}
        </h1>
      </template>
      <template #right>
        <template v-if="inlineEditingField === 'title'">
          <button type="button" class="text-sm text-neutral-500" @click="cancelInlineEdit">取消</button>
          <button type="button" class="text-primary-600 text-sm font-medium" :disabled="inlineSaving" @click="saveInlineOrganizedField('title')">
            {{ inlineSaving ? '保存中' : '保存' }}
          </button>
        </template>
        <button
          v-if="diary && !inlineEditingField && !isEditing && !isEditingStructured"
          type="button"
          :disabled="favoriteSaving"
          :aria-label="diary.is_favorite ? '取消收藏日记' : '收藏日记'"
          class="text-amber-500 text-xl leading-none disabled:opacity-50"
          @click="toggleDiaryFavorite"
        >
          {{ diary.is_favorite ? '★' : '☆' }}
        </button>
        <button
          v-if="diary && !inlineEditingField && !isEditing && !isEditingStructured"
          @click="handleDelete"
          :disabled="deleting || organizing || analyzing"
          class="text-red-500 text-sm font-medium disabled:opacity-50"
        >
          {{ deleting ? '删除中' : '删除' }}
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
          <div class="text-base text-neutral-500 mb-3">{{ diary.diary_date }}</div>
          <p v-if="isVoicePending" class="mb-3 text-sm text-amber-700">{{ transcriptionStatusLabel }}</p>
          <textarea
            v-model="editText"
            data-auto-resize
            class="w-full min-h-[300px] text-base text-neutral-800 leading-relaxed p-3 border border-neutral-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none resize-none overflow-hidden"
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
          <div class="text-base text-neutral-500 mb-3">{{ diary.diary_date }}</div>
          <p v-if="isVoicePending" class="mb-3 text-sm text-amber-700">{{ transcriptionStatusLabel }}</p>
          <div class="text-base text-neutral-800 whitespace-pre-wrap leading-relaxed" @dblclick="isEditable && startEdit()">
            {{ diary.original_text }}
          </div>
        </div>
        <!-- 底部整理按钮 -->
        <div class="px-4 py-3 border-t border-neutral-200 bg-white safe-area-bottom">
          <button
            @click="handleOrganize"
            :disabled="organizing || isVoicePending"
            class="w-full py-2.5 rounded-lg bg-primary-600 text-white text-sm font-medium hover:bg-primary-700 disabled:opacity-50"
          >
            <span v-if="organizing" class="inline-flex items-center gap-2">
              <Spinner />
              {{ organizeStep + '...' }}
            </span>
            <span v-else>{{ isVoicePending ? transcriptionStatusLabel : 'AI 整理' }}</span>
          </button>
          <p v-if="organizeError" class="text-sm text-red-500 text-center mt-2">{{ organizeError }}</p>
        </div>
      </template>
    </template>

    <!-- 已整理 / 已分析状态：显示内容 -->
    <template v-else-if="diary && isOrganizedOrAnalyzed">
      <!-- 三 Tab 切换（仅 analyzed 状态显示） -->
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
          <button
            @click="activeTab = 'action'"
            class="flex-1 py-2.5 text-sm font-medium text-center transition-colors relative"
            :class="activeTab === 'action' ? 'text-primary-600' : 'text-neutral-500 hover:text-neutral-700'"
          >
            行动
            <span
              v-if="activeTab === 'action'"
              class="absolute bottom-0 left-1/2 -translate-x-1/2 w-12 h-0.5 bg-primary-600 rounded-full"
            />
          </button>
        </div>
      </div>

      <!-- 原事件标题滚出内容区后显示；完整复用原标题行的布局与收藏操作。 -->
      <div
        v-if="stickyEvent && activeTab === 'diary' && !isEditing && !isEditingStructured"
        class="absolute inset-x-0 z-30 border-b border-neutral-200 bg-white"
        :style="{ top: `${diaryContentTop}px` }"
      >
        <div class="flex items-start gap-2 px-4 py-3">
          <div class="min-w-0 flex-1 text-base font-medium text-neutral-800">
            {{ stickyEvent.event_title || '未命名事件' }}
          </div>
          <div class="flex shrink-0 items-center gap-0.5" role="radiogroup" aria-label="修改事件重要性">
            <button
              v-for="option in importanceOptions"
              :key="option.code"
              type="button"
              class="h-6 w-6 rounded-full border text-[10px] font-medium leading-none transition-colors disabled:opacity-50"
              :class="importanceButtonClass(option.code, stickyImportanceCode === option.code)"
              :aria-label="`重要性：${option.label}`"
              :aria-pressed="stickyImportanceCode === option.code"
              :disabled="importanceSavingEventId === stickyEvent.id"
              @click.stop="updateEventImportance(stickyEvent.id, option.code)"
            >
              {{ option.label }}
            </button>
          </div>
          <button
            type="button"
            class="shrink-0 -mr-1 -mt-1 w-8 h-8 text-lg leading-none text-amber-500 disabled:opacity-50"
            :aria-label="stickyEvent.is_favorite ? '取消收藏事件' : '收藏事件'"
            :title="stickyEvent.is_favorite ? '取消收藏' : '收藏'"
            :disabled="favoriteSaving"
            @click.stop="toggleEventFavorite(stickyEvent.id)"
          >
            {{ stickyEvent.is_favorite ? '★' : '☆' }}
          </button>
        </div>
      </div>

      <!-- 日记 Tab 内容 -->
      <div
        v-show="activeTab === 'diary'"
        ref="diaryContentRef"
        class="flex-1 min-h-0 overflow-y-auto px-4 py-3 pb-24"
        @scroll="updateStickyEventTitle"
      >
        <!-- 编辑保存成功提示 -->
        <div
          v-if="editSaveMessage"
          class="mb-3 px-3 py-2 bg-amber-50 border border-amber-200 rounded-lg text-sm text-amber-700"
        >
          {{ editSaveMessage }}
        </div>
        <div
          v-if="inlineSaveError"
          class="mb-3 px-3 py-2 bg-red-50 border border-red-200 rounded-lg text-sm text-red-600"
        >
          {{ inlineSaveError }}
        </div>
        <!-- 结构化编辑模式 -->
        <template v-if="isEditingStructured">
          <div class="space-y-4">
            <!-- 标题 -->
            <div>
              <label class="text-xs font-medium text-neutral-500 mb-1 block">标题</label>
              <input
                v-model="editFormData.title"
                class="w-full text-base text-neutral-800 p-2 border border-neutral-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none"
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
                class="w-full min-h-[4.5rem] text-base text-neutral-800 leading-relaxed p-2 border border-neutral-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none resize-none overflow-hidden"
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
                class="w-full min-h-[3rem] text-base text-neutral-800 leading-relaxed p-2 border border-neutral-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none resize-none overflow-hidden"
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
                :id="`event-${event.id}`"
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
                class="w-full min-h-[4.5rem] text-base text-neutral-800 leading-relaxed p-2 border border-neutral-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none resize-none overflow-hidden"
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
                class="w-full min-h-[4.5rem] text-base text-neutral-800 leading-relaxed p-2 border border-neutral-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none resize-none overflow-hidden"
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
            <div class="text-base text-neutral-500 mb-2">编辑原文</div>
            <textarea
              v-model="editText"
              data-auto-resize
              class="w-full min-h-[300px] text-base text-neutral-800 leading-relaxed p-3 border border-neutral-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none resize-none overflow-hidden"
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
        <div v-if="diary.organized?.summary" class="mb-4 pb-3 border-b border-neutral-100">
          <template v-if="inlineEditingField === 'summary'">
            <textarea
              :value="inlineDraft"
              class="w-full text-base italic text-neutral-600 leading-relaxed p-2 border border-neutral-200 rounded-lg focus:ring-2 focus:ring-primary-500 outline-none resize-none"
              rows="3"
              @input="updateInlineDraft"
            />
            <div class="mt-2 flex justify-end gap-2">
              <button type="button" class="px-3 py-1.5 rounded-lg border border-neutral-200 text-sm text-neutral-600" @click="cancelInlineEdit">取消</button>
              <button type="button" class="px-3 py-1.5 rounded-lg bg-primary-600 text-sm text-white" @click="saveInlineOrganizedField('summary')">保存</button>
            </div>
          </template>
          <div v-else class="cursor-text text-sm italic text-neutral-600 leading-relaxed" @dblclick="startInlineEdit('summary', diary.organized.summary)">
            {{ diary.organized.summary }}
          </div>
        </div>

        <!-- 引入段 -->
        <div v-if="diary.organized?.introduction" class="mb-4">
          <template v-if="inlineEditingField === 'introduction'">
            <textarea
              :value="inlineDraft"
              class="w-full text-base text-neutral-500 leading-relaxed p-2 border border-neutral-200 rounded-lg focus:ring-2 focus:ring-primary-500 outline-none resize-none"
              rows="3"
              @input="updateInlineDraft"
            />
            <div class="mt-2 flex justify-end gap-2">
              <button type="button" class="px-3 py-1.5 rounded-lg border border-neutral-200 text-sm text-neutral-600" @click="cancelInlineEdit">取消</button>
              <button type="button" class="px-3 py-1.5 rounded-lg bg-primary-600 text-sm text-white" @click="saveInlineOrganizedField('introduction')">保存</button>
            </div>
          </template>
          <div v-else class="cursor-text text-base text-neutral-500 leading-relaxed" @dblclick="startInlineEdit('introduction', diary.organized.introduction)">
            {{ diary.organized.introduction }}
          </div>
        </div>

        <!-- 事件卡片列表 -->
        <div v-if="diary.organized?.events && diary.organized.events.length > 0" class="mb-4">
          <EventCard
            v-for="event in sortedEvents"
            :key="event.id"
            :event="event"
            :id="`event-${event.id}`"
            :analysis-run-id="diary.organized?.analysis?.id"
            :annotations="annotations"
            :inline-edit-field="inlineEditingEvent?.eventId === event.id ? inlineEditingEvent.field : null"
            :favorite-saving="favoriteSaving"
            :importance-saving="importanceSavingEventId === event.id"
            @update="onEventUpdate"
            @importance-change="updateEventImportance"
            @annotation-select="openAnnotationSelection"
            @annotation-clicked="openAnnotationById"
            @favorite-toggle="toggleEventFavorite"
            @inline-edit-start="field => startInlineEventEdit(event.id, field)"
            @inline-edit-save="(field, value) => saveInlineEventEdit(event.id, field, value)"
            @inline-edit-cancel="cancelInlineEdit"
          />
        </div>

        <!-- 琐事（平铺） -->
        <div v-if="diary.organized?.trivia && diary.organized.trivia.length > 0" class="mb-3">
          <div class="text-lg font-medium text-neutral-800 mb-2">琐事</div>
          <template v-if="inlineEditingField === 'trivia'">
            <textarea :value="inlineDraft" rows="3" class="w-full text-base text-neutral-600 leading-relaxed p-2 border border-neutral-200 rounded-lg focus:ring-2 focus:ring-primary-500 outline-none resize-none" @input="updateInlineDraft" />
            <div class="mt-2 flex justify-end gap-2">
              <button type="button" class="px-3 py-1.5 rounded-lg border border-neutral-200 text-sm text-neutral-600" @click="cancelInlineEdit">取消</button>
              <button type="button" class="px-3 py-1.5 rounded-lg bg-primary-600 text-sm text-white" @click="saveInlineOrganizedField('trivia')">保存</button>
            </div>
          </template>
          <div v-else class="cursor-text" @dblclick="startInlineEdit('trivia', diary.organized.trivia.join('\n'))">
            <ol v-if="diary.organized.trivia.length > 1" class="list-decimal list-inside space-y-1.5">
              <li v-for="(item, idx) in diary.organized.trivia" :key="idx" class="text-base text-neutral-600 leading-relaxed">{{ item }}</li>
            </ol>
            <ul v-else class="list-none space-y-1.5">
              <li class="text-base text-neutral-600 leading-relaxed">{{ diary.organized.trivia[0] }}</li>
            </ul>
          </div>
        </div>

        <!-- 后续计划（平铺） -->
        <div v-if="diary.organized?.plans && diary.organized.plans.length > 0" class="mb-3">
          <div class="text-lg font-medium text-neutral-800 mb-2">后续计划</div>
          <template v-if="inlineEditingField === 'plans'">
            <textarea :value="inlineDraft" rows="3" class="w-full text-base text-neutral-600 leading-relaxed p-2 border border-neutral-200 rounded-lg focus:ring-2 focus:ring-primary-500 outline-none resize-none" @input="updateInlineDraft" />
            <div class="mt-2 flex justify-end gap-2">
              <button type="button" class="px-3 py-1.5 rounded-lg border border-neutral-200 text-sm text-neutral-600" @click="cancelInlineEdit">取消</button>
              <button type="button" class="px-3 py-1.5 rounded-lg bg-primary-600 text-sm text-white" @click="saveInlineOrganizedField('plans')">保存</button>
            </div>
          </template>
          <div v-else class="cursor-text" @dblclick="startInlineEdit('plans', diary.organized.plans.join('\n'))">
            <ol v-if="diary.organized.plans.length > 1" class="list-decimal list-inside space-y-1.5">
              <li v-for="(item, idx) in diary.organized.plans" :key="idx" class="text-base text-neutral-600 leading-relaxed">{{ item }}</li>
            </ol>
            <ul v-else class="list-none space-y-1.5">
              <li class="text-base text-neutral-600 leading-relaxed">{{ diary.organized.plans[0] }}</li>
            </ul>
          </div>
        </div>

        <KnowledgeDepositCard v-if="diary.status === 'analyzed'" :diary-id="diary.id" />

        <!-- 原始文本（折叠，默认收起） -->
        <details class="border-t border-neutral-100 pt-3">
          <summary class="text-xs text-neutral-400 cursor-pointer">查看原始文本</summary>
          <div class="mt-2 text-xs text-neutral-500 whitespace-pre-wrap leading-relaxed font-mono" @dblclick="isEditable && startEdit()">
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
            :favorite-saving="favoriteSaving"
          @annotation-select="openAnnotationSelection"
            @annotation-clicked="openAnnotationById"
            @favorite-toggle="toggleEventFavorite"
        />
        <div v-else class="flex items-center justify-center py-12">
          <span class="text-sm text-neutral-400">暂无分析数据</span>
        </div>
      </div>

      <!-- 行动 Tab 内容；日记与分析面板保持独立。 -->
      <DiaryActionPanel
        v-if="diary.status === 'analyzed'"
        v-show="activeTab === 'action'"
        :diary-id="diary.id"
        :visible="activeTab === 'action'"
      />

      <!-- 底部操作区（编辑模式下隐藏） -->
      <div v-if="!isEditingStructured" class="fixed bottom-0 left-0 right-0 px-4 py-2 border-t border-neutral-200 bg-white safe-area-bottom">
        <div class="max-w-md mx-auto">
          <!-- 整理或分析中状态：统一显示全宽进度按钮 -->
          <button
            v-if="organizing || analyzing"
            disabled
            class="w-full py-2.5 rounded-lg bg-primary-600 text-white text-sm font-medium disabled:opacity-50"
          >
            <span class="inline-flex items-center gap-2">
              <Spinner />
              {{ (organizing ? organizeStep : analyzeStep) + '...' }}
            </span>
          </button>
          <!-- 操作按钮 -->
          <div v-else class="flex items-center gap-2">
            <!-- 对话输入（日记 Tab 时显示） -->
            <template v-if="diary.status === 'analyzed'">
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
            <!-- 重新整理按钮（organized 状态） -->
            <button
              v-if="diary.status === 'organized'"
              @click="handleOrganize"
              :disabled="organizing"
              class="flex-1 py-2.5 rounded-lg border border-neutral-300 bg-white text-sm font-medium text-neutral-700 hover:bg-neutral-50 disabled:opacity-50 shrink-0"
            >
              {{ organizing ? '整理中...' : '重新整理' }}
            </button>
            <!-- AI 分析按钮（organized 状态） -->
            <button
              v-if="diary.status === 'organized'"
              @click="handleAnalyze"
              class="flex-1 py-2.5 rounded-lg bg-primary-600 text-white text-sm font-medium hover:bg-primary-700 shrink-0"
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
          <p v-if="organizeError" class="text-xs text-red-500 text-center mt-1">{{ organizeError }}</p>
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
      class="fixed bottom-20 right-4 z-40 flex h-12 w-12 items-center justify-center rounded-full bg-primary-600 text-2xl text-white shadow-lg transition-colors hover:bg-primary-700"
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
            <blockquote class="border-l-2 border-primary-500 pl-3 text-base leading-relaxed text-neutral-700">
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
                  <p class="whitespace-pre-wrap text-base leading-relaxed text-neutral-700">{{ item.comment.content }}</p>
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

import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { resizeTextarea, resizeTextareas } from '~/composables/useAutoResizeTextarea'
import type { DiaryAnnotation, DiaryAnnotationClick, DiaryAnnotationSelection } from '~/types'
import { formatDateTimeInAppTimeZone } from '~/utils/datetime'

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
const activeTab = ref<'diary' | 'analysis' | 'action'>('diary')
const annotations = ref<DiaryAnnotation[]>([])
const favoriteSaving = ref(false)
const importanceSavingEventId = ref<string | null>(null)
const diaryContentRef = ref<HTMLElement | null>(null)
const diaryContentTop = ref(44)
const stickyEvent = ref<DiaryEvent | null>(null)
const importanceOptions = [
  { code: 'HIGH' as const, label: '高' },
  { code: 'MEDIUM' as const, label: '中' },
  { code: 'LOW' as const, label: '低' },
]
const stickyImportanceCode = computed<'HIGH' | 'MEDIUM' | 'LOW' | ''>(() => {
  const value = stickyEvent.value?.user_importance || stickyEvent.value?.ai_importance
  return value === 'HIGH' || value === 'MEDIUM' || value === 'LOW' ? value : ''
})
const importanceButtonClass = (importance: 'HIGH' | 'MEDIUM' | 'LOW', selected: boolean) => {
  if (selected) {
    return importance === 'HIGH'
      ? 'border-red-500 bg-red-500 text-white'
      : importance === 'MEDIUM'
        ? 'border-orange-500 bg-orange-500 text-white'
        : 'border-neutral-500 bg-neutral-500 text-white'
  }
  return importance === 'HIGH'
    ? 'border-red-200 text-red-500 hover:bg-red-50'
    : importance === 'MEDIUM'
      ? 'border-orange-200 text-orange-500 hover:bg-orange-50'
      : 'border-neutral-300 text-neutral-500 hover:bg-neutral-50'
}

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

const isVoicePending = computed(() => !!diary.value?.transcription_status)
const transcriptionStatusLabel = computed(() => ({
  audio_uploaded: '已上传录音',
  transcribing: '录音转写中',
  partial_failed: '部分录音转写失败',
}[diary.value?.transcription_status || ''] || ''))

// 可编辑判断：仅 saved / organized 可编辑
const isEditable = computed(() =>
  !isVoicePending.value && (diary.value?.status === 'saved' || diary.value?.status === 'organized')
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

const updateStickyEventTitle = () => {
  const content = diaryContentRef.value
  if (!content || activeTab.value !== 'diary' || isEditing.value || isEditingStructured.value) {
    stickyEvent.value = null
    return
  }

  const contentTop = content.getBoundingClientRect().top
  diaryContentTop.value = contentTop
  let currentEvent: DiaryEvent | null = null
  for (const event of sortedEvents.value) {
    const eventElement = document.getElementById(`event-${event.id}`)
    if (eventElement && eventElement.getBoundingClientRect().top <= contentTop) {
      currentEvent = event
    }
  }
  stickyEvent.value = currentEvent
}

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
  return formatDateTimeInAppTimeZone(value) || value
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
  const isMobile = window.matchMedia('(max-width: 767px)').matches
  const left = Math.min(
    Math.max(gap, rect.left + (rect.width - toolbarWidth) / 2),
    window.innerWidth - toolbarWidth - gap,
  )
  // 手机浏览器的原生选中文单通常紧贴选区下方，预留其高度后再放置应用操作栏。
  const top = isMobile
    ? Math.min(rect.bottom + 40, window.innerHeight - toolbarHeight - gap)
    : rect.top >= toolbarHeight + gap
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

const clearNativeSelection = () => {
  window.getSelection()?.removeAllRanges()
}

const handleDocumentPointerDown = (event: PointerEvent) => {
  if (!selectionToolbarOpen.value) return
  const target = event.target as Node | null
  if (target && selectionToolbarRef.value?.contains(target)) return
  // 选区保留时，卡片内后续 touchend 会把旧选区再次识别为新的批注选择。
  clearNativeSelection()
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
    await nextTick()
    await scrollToEventAnchor()
    updateStickyEventTitle()
  }
}

const scrollToEventAnchor = async () => {
  if (!route.hash.startsWith('#event-')) return
  await nextTick()
  const target = document.getElementById(route.hash.slice(1))
  if (!target) return
  target.scrollIntoView({ behavior: 'smooth', block: 'start' })
  target.classList.add('favorite-event-highlight')
  window.setTimeout(() => target.classList.remove('favorite-event-highlight'), 1600)
}

const toggleDiaryFavorite = async () => {
  if (!diary.value || favoriteSaving.value) return
  favoriteSaving.value = true
  try {
    const action = diary.value.is_favorite ? 'DELETE' : 'PUT'
    await api(`/diaries/${diary.value.id}/favorite`, { method: action })
    diary.value.is_favorite = !diary.value.is_favorite
  } catch (err) {
    console.error('切换日记收藏失败', err)
  } finally {
    favoriteSaving.value = false
  }
}

const toggleEventFavorite = async (eventId: string) => {
  if (!diary.value || favoriteSaving.value) return
  const event = diary.value.organized?.events.find(item => item.id === eventId)
  if (!event) return
  favoriteSaving.value = true
  try {
    const action = event.is_favorite ? 'DELETE' : 'PUT'
    await api(`/diaries/${diary.value.id}/events/${eventId}/favorite`, { method: action })
    event.is_favorite = !event.is_favorite
  } catch (err) {
    console.error('切换事件收藏失败', err)
  } finally {
    favoriteSaving.value = false
  }
}

const updateEventImportance = async (eventId: string, importance: 'HIGH' | 'MEDIUM' | 'LOW') => {
  if (!diary.value || importanceSavingEventId.value) return
  const event = diary.value.organized?.events.find(item => item.id === eventId)
  if (!event) return

  const previousImportance = event.user_importance
  const previousReason = event.user_importance_reason
  importanceSavingEventId.value = eventId
  event.user_importance = importance
  event.user_importance_reason = null
  try {
    await api(`/diaries/${diary.value.id}/events/${eventId}`, {
      method: 'PUT',
      body: {
        id: eventId,
        user_importance: importance,
        user_importance_reason: null,
      },
    })
  } catch (err) {
    event.user_importance = previousImportance
    event.user_importance_reason = previousReason
    console.error('修改事件重要性失败', err)
  } finally {
    importanceSavingEventId.value = null
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

type InlineEventField = 'title' | 'body' | 'feeling' | 'reflection'
const inlineEditingField = ref<string | null>(null)
const inlineDraft = ref('')
const inlineSaving = ref(false)
const inlineSaveError = ref('')

const inlineEditingEvent = computed<{ eventId: string; field: InlineEventField } | null>(() => {
  const value = inlineEditingField.value
  if (!value?.startsWith('event:')) return null
  const [, eventId, field] = value.split(':')
  if (!eventId || !['title', 'body', 'feeling', 'reflection'].includes(field)) return null
  return { eventId, field: field as InlineEventField }
})

const updateInlineDraft = (event: Event) => {
  inlineDraft.value = (event.target as HTMLTextAreaElement).value
}

const startInlineEdit = (field: string, value: string) => {
  if (inlineSaving.value || structuredSaving.value) return
  const selection = window.getSelection()
  if (selection && !selection.isCollapsed) return
  inlineEditingField.value = field
  inlineDraft.value = value
  inlineSaveError.value = ''
  nextTick(() => resizeTextareas())
}

const startInlineEventEdit = (eventId: string, field: InlineEventField) => {
  const event = diary.value?.organized?.events.find(item => item.id === eventId)
  if (!event) return
  startInlineEdit(`event:${eventId}:${field}`, (event[field] || []).join('\n'))
}

const cancelInlineEdit = () => {
  inlineEditingField.value = null
  inlineDraft.value = ''
  inlineSaveError.value = ''
}

const saveInlineOrganizedField = async (field: 'title' | 'summary' | 'introduction' | 'trivia' | 'plans') => {
  if (!diary.value || inlineSaving.value) return
  inlineSaving.value = true
  inlineSaveError.value = ''
  try {
    const body: Record<string, unknown> = {}
    if (field === 'trivia' || field === 'plans') {
      body[field] = inlineDraft.value.split('\n').filter(item => item.trim())
    } else {
      body[field] = inlineDraft.value
    }
    const updatedOrganized = await api(`/diaries/${diaryId.value}/organized`, { method: 'PUT', body })
    cancelInlineEdit()
    if (diary.value) diary.value.organized = updatedOrganized
    await loadAnnotations()
  } catch (err: any) {
    inlineSaveError.value = err?.data?.detail || '保存失败，请稍后重试'
  } finally {
    inlineSaving.value = false
  }
}

const saveInlineEventEdit = async (eventId: string, field: InlineEventField, value: string) => {
  if (!diary.value || inlineSaving.value) return
  const event = diary.value.organized?.events.find(item => item.id === eventId)
  if (!event) return
  inlineSaving.value = true
  inlineSaveError.value = ''
  try {
    const updatedEvent = await api(`/diaries/${diaryId.value}/events/${eventId}`, {
      method: 'PUT',
      body: {
        id: event.id,
        event_title: field === 'title' ? value : event.event_title,
        body: field === 'body' ? value.split('\n').filter(item => item.trim()) : event.body,
        feeling: field === 'feeling' ? value.split('\n').filter(item => item.trim()) : event.feeling,
        reflection: field === 'reflection' ? value.split('\n').filter(item => item.trim()) : event.reflection,
      },
    })
    cancelInlineEdit()
    const localEvent = diary.value?.organized?.events.find(item => item.id === eventId)
    if (localEvent) Object.assign(localEvent, updatedEvent)
    await loadAnnotations()
  } catch (err: any) {
    inlineSaveError.value = err?.data?.detail || '保存失败，请稍后重试'
  } finally {
    inlineSaving.value = false
  }
}

watch([activeTab, isEditing, isEditingStructured], () => {
  nextTick(updateStickyEventTitle)
})

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
    const updatedDiary = await api<Diary>(`/diaries/${diaryId.value}`, {
      method: 'PUT',
      body: { original_text: editText.value },
    })
    isEditing.value = false
    if (diary.value) Object.assign(diary.value, updatedDiary)
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
  window.addEventListener('resize', updateStickyEventTitle)
})

onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', handleDocumentPointerDown, true)
  window.removeEventListener('scroll', handleDocumentScroll, true)
  window.removeEventListener('resize', updateStickyEventTitle)
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
    const updatedOrganized = await api(`/diaries/${diaryId.value}/organized`, {
      method: 'PUT',
      body: body,
    })
    isEditingStructured.value = false
    editFormData.value = null
    editedEvents.value.clear()
    if (diary.value) diary.value.organized = updatedOrganized
    await loadAnnotations()
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
    await new Promise(resolve => setTimeout(resolve, 20000))
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
const analyzeMode = ref<'ordinary' | 'feedback'>('ordinary')

const ANALYZE_STEP_LABELS: Record<'ordinary' | 'feedback', Record<string, string>> = {
  ordinary: {
    mood_tag_extract: '元数据、心情与标签提取',
    core_analysis: '核心分析与可行动建议',
    cognition_analysis: '认知校准、问题解答与认知完善',
    action_planning: '行动项规划',
  },
  feedback: {
    feedback_core_analysis: '核心分析与可行动建议',
    feedback_cognition_analysis: '认知校准、问题解答与认知完善',
    action_planning: '行动项规划',
  },
}

const formatAnalyzeStep = (stepKey: string) => {
  if (stepKey === 'saving_result') return '正在保存分析结果'
  const labels = ANALYZE_STEP_LABELS[analyzeMode.value]
  const stepKeys = Object.keys(labels)
  const idx = stepKeys.indexOf(stepKey)
  const label = labels[stepKey] || stepKey
  if (idx === -1) return label
  return `${idx + 1}/${stepKeys.length} ${label}`
}

const handleAnalyze = async () => {
  analyzing.value = true
  analyzeError.value = ''
  analyzeStep.value = formatAnalyzeStep('mood_tag_extract')
  try {
    const task = await api<{ analysis_mode?: 'ordinary' | 'feedback'; current_step?: string }>(
      `/diaries/${diaryId.value}/analyze`,
      { method: 'POST' },
    )
    if (task.analysis_mode) {
      analyzeMode.value = task.analysis_mode
    }
    if (task.current_step) {
      analyzeStep.value = formatAnalyzeStep(task.current_step)
    }
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
    await new Promise(resolve => setTimeout(resolve, 20000))
    try {
      const task = await api<{ status: string; analysis_mode?: 'ordinary' | 'feedback'; current_step?: string; error_message?: string }>(
        `/diaries/${diaryId.value}/analyze/status`
      )
      consecutiveErrors = 0
      if (task.analysis_mode) {
        analyzeMode.value = task.analysis_mode
      }
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
    const task = await api<{ status: string; analysis_mode?: 'ordinary' | 'feedback'; current_step?: string }>(
      `/diaries/${diaryId.value}/analyze/status`
    )
    if (task.status === 'running') {
      analyzing.value = true
      if (task.analysis_mode) {
        analyzeMode.value = task.analysis_mode
      }
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
    if (diary.value.status === 'saved' || diary.value.status === 'organized') {
      checkOrganizeStatus()
    }
    if (diary.value.status === 'organized' || diary.value.status === 'analyzed') {
      checkAnalyzeStatus()
    }
  }
})
</script>
