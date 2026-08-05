<template>
  <div class="schedule-page fixed inset-0 flex flex-col overflow-hidden bg-white" :class="{ 'z-[60]': modalOpen }">
    <header class="sticky top-0 z-20 shrink-0 bg-white border-b border-neutral-200">
      <div class="grid h-16 grid-cols-[1fr_auto_1fr] items-center px-3 sm:h-20 sm:px-4">
        <span>
</span>
        <div class="flex items-center gap-1 text-sm font-semibold sm:gap-2 sm:text-lg">
          <button class="h-8 w-5 text-xl text-neutral-400 sm:h-9 sm:w-7 sm:text-2xl" @click="moveWeek(-1)" aria-label="上一周">‹</button>
          <button class="whitespace-nowrap text-center leading-5" @click="pickerOpen = !pickerOpen">
<span class="sm:hidden">{{ headerCompactRangeLabel }}</span>
<span class="hidden sm:inline">{{ headerRangeLabel }}</span>
</button>
          <button class="h-8 w-5 text-xl text-neutral-400 sm:h-9 sm:w-7 sm:text-2xl" @click="moveWeek(1)" aria-label="下一周">›</button>
        </div>
        <div class="justify-self-end flex items-center rounded-full bg-neutral-50 px-1 shadow-sm sm:px-2">
          <button class="order-1 h-10 w-10 sm:h-12 sm:w-12" @click="view = view === 'day' ? 'week' : 'day'" :aria-label="view === 'day' ? '切换为周视图' : '切换为日视图'">
<svg viewBox="0 0 24 24" class="mx-auto h-6 w-6 fill-none stroke-current stroke-[2.5] sm:h-7 sm:w-7">
<rect x="3" y="4" width="7" height="7" rx="1"/>
<rect x="14" y="4" width="7" height="7" rx="1"/>
<rect x="3" y="14" width="7" height="7" rx="1"/>
<path d="M14 17.5h7M17.5 14v7"/>
</svg>
</button>
          <button class="order-3 hidden h-10 w-10 sm:block sm:h-12 sm:w-12" @click="openPrint" aria-label="打印周日程">
<svg viewBox="0 0 24 24" class="mx-auto h-6 w-6 fill-none stroke-current stroke-[2] sm:h-7 sm:w-7">
<path d="M6 9V3h12v6M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/>
<path d="M6 14h12v7H6zM18 12h.01"/>
</svg>
</button>
          <button class="order-2 h-10 w-10 sm:h-12 sm:w-12" @click="formOpen = true" aria-label="添加日程">
<svg viewBox="0 0 24 24" class="mx-auto h-7 w-7 fill-none stroke-current stroke-[2.5] sm:h-8 sm:w-8">
<path d="M12 5v14M5 12h14"/>
</svg>
</button>
        </div>
      </div>
      <div v-if="pickerOpen" class="absolute left-4 right-4 top-16 z-30 rounded-xl bg-white p-4 shadow-xl border border-neutral-200">
<label class="block text-xs text-neutral-500 mb-2">选择年份与周</label>
<input v-model="weekPicker" type="week" class="w-full rounded-lg bg-neutral-100 p-3" @change="applyWeek">
</div>
      <div class="grid grid-cols-7 px-2 pb-2" @touchstart="swipeStart=$event.touches[0].clientX" @touchend="handleSwipe($event.changedTouches[0].clientX)">
        <button v-for="day in headerWeekDays" :key="day.key" @click="selectDay(day.key)" class="flex flex-col items-center gap-1 text-xs" :class="day.key === headerDate ? 'text-neutral-800 font-medium' : 'text-neutral-400'">
          <span>{{ day.name }}</span>
<span :class="day.isToday ? 'w-7 h-7 rounded-full bg-red-500 text-white flex items-center justify-center' : 'w-7 h-7 flex items-center justify-center'">{{ day.date }}</span>
        </button>
      </div>
    </header>

    <main class="min-h-0 flex-1 overflow-x-hidden overflow-y-auto overscroll-contain pb-[calc(52px+env(safe-area-inset-bottom)+12px)]" @touchstart="startScheduleSwipeV2" @touchmove="moveScheduleSwipeV2" @touchend="endScheduleSwipeSmoothV2" @touchcancel="cancelScheduleSwipeV2">
      <div class="schedule-swipe-viewport">
<div v-if="view === 'day'" ref="swipeTrack" class="flex w-[300%]" :style="scheduleSwipeTrackStyle">
<section v-for="(panel, panelIndex) in dayPanels" :key="panelIndex" class="w-1/3 shrink-0">
<div class="sticky top-0 z-10 grid grid-cols-[118px_1fr] border-t border-b border-neutral-200 bg-white">
<div class="border-r border-neutral-200"></div>
<div class="py-3 text-center text-lg font-semibold" :class="dayInfo(panel.key).isToday ? 'text-red-500' : 'text-neutral-800'">{{ dayInfo(panel.key).month }}月{{ dayInfo(panel.key).date }}日－周{{ dayInfo(panel.key).name }}</div>
</div>
<section v-if="allDayFor(panel.key).length" class="border-t border-neutral-200">
<div class="flex">
<span class="w-[118px] shrink-0 pt-3 pr-4 text-right text-sm text-neutral-400">全天</span>
<div class="flex-1 border-l border-neutral-200 space-y-2 px-3 py-2">
<div v-for="item in allDayFor(panel.key)" :key="item.id" @click="openDetail(item)" class="block min-w-0 w-full overflow-hidden rounded-xl border border-neutral-200 border-l-4 bg-[#f5f5f7] px-3 py-2 text-left shadow-sm" :class="item.status==='completed' ? 'border-l-[#007aff] opacity-50' : 'border-l-[#ff9500]'">
<span class="flex min-w-0 items-center gap-2">
<span class="min-w-0 flex-1">
<span class="block break-all text-base font-semibold leading-5 text-neutral-900" :class="item.status==='completed'?'line-through':''">{{ item.title }}</span>
<span v-if="item.execution_note" class="schedule-note-preview mt-1 block break-all text-xs text-slate-500">{{ item.execution_note }}</span>
</span>
<button type="button" @click.stop="toggleSchedule(item)" class="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border-2" :class="item.status==='completed' ? 'border-[#007aff] text-[#007aff]' : 'border-[#ff9500] text-[#ff9500]'">{{ item.status==='completed' ? '✓' : '' }}</button>
</span>
</div>
</div>
</div>
</section>
<template v-for="block in timeBlocksFor([panel.key])" :key="block.key">
<div v-if="block.type === 'empty'" class="relative flex min-h-11 border-t border-neutral-200">
<span class="w-[118px] shrink-0 pt-3 pr-4 text-right text-sm text-neutral-400">{{ block.startLabel }}</span>
<div class="flex-1 border-l border-neutral-200 px-4 py-2 text-base text-neutral-500">空档已压缩 · {{ block.startLabel }}—{{ block.endLabel }}</div>
</div>
<div v-else class="flex border-t border-neutral-200">
<span class="w-[118px] shrink-0 pt-3 pr-4 text-right text-sm text-neutral-400">{{ block.startLabel }}</span>
<div class="flex-1 border-l border-neutral-200 space-y-2 px-3 py-2">
<div v-for="item in block.items[panel.key] || []" :key="item.id" @click="openDetail(item)" class="block min-w-0 w-full overflow-hidden rounded-xl border border-neutral-200 border-l-4 bg-[#f5f5f7] px-3 py-2 text-left shadow-sm" :class="item.status==='completed' ? 'border-l-[#007aff] opacity-50' : 'border-l-[#ff9500]'">
<span class="flex min-w-0 items-center gap-2">
<span class="min-w-0 flex-1">
<span class="block break-all text-base font-semibold leading-5 text-neutral-900" :class="item.status==='completed'?'line-through':''">{{ item.title }}</span>
<span class="mt-1 block text-sm text-neutral-500">{{ item.start_time?.slice(0,5) }}–{{ item.end_time?.slice(0,5) }}</span>
<span v-if="item.execution_note" class="schedule-note-preview mt-1 block break-all text-xs text-slate-500">{{ item.execution_note }}</span>
</span>
<button type="button" @click.stop="toggleSchedule(item)" class="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border-2" :class="item.status==='completed' ? 'border-[#007aff] text-[#007aff]' : 'border-[#ff9500] text-[#ff9500]'">{{ item.status==='completed' ? '✓' : '' }}</button>
</span>
</div>
</div>
</div>
</template>
</section>
</div>
      <div v-else ref="swipeTrack" class="flex w-[300%]" :style="scheduleSwipeTrackStyle">
<section v-for="(panel, panelIndex) in weekPanels" :key="panelIndex" class="w-1/3 shrink-0">
<div class="grid grid-cols-[96px_repeat(2,minmax(0,1fr))] border-l border-t border-neutral-200 text-xs bg-white">
<div class="schedule-table-date-header sticky top-0 z-10 border-r border-b border-neutral-200 bg-white">
</div>
<div v-for="d in panel.days" :key="d.key" class="schedule-table-date-header sticky top-0 z-10 border-r border-b border-neutral-200 bg-white py-3 text-center text-lg font-semibold" :class="d.isToday?'text-red-500':''">{{ d.month }}月{{ d.date }}日－周{{ d.name }}</div>
<template v-if="panel.days.some(day=>allDayFor(day.key).length)">
<div class="border-r border-b border-neutral-200 pt-3 pr-3 text-right text-sm text-neutral-400">全天</div>
<div v-for="d in panel.days" :key="`all-day-${d.key}`" class="border-r border-b border-neutral-200 space-y-2 px-2 py-2">
<div v-for="item in allDayFor(d.key)" :key="item.id" @click="openDetail(item)" class="block w-full rounded-xl border border-neutral-200 border-l-4 bg-[#f5f5f7] px-2 py-2 text-left shadow-sm" :class="item.status==='completed' ? 'border-l-[#007aff] opacity-50' : 'border-l-[#ff9500]'">
<span class="flex items-center gap-1">
<span class="min-w-0 flex-1">
<span class="block truncate text-sm font-semibold" :class="item.status==='completed'?'line-through':''">{{ item.title }}</span>
<span v-if="item.execution_note" class="schedule-note-preview mt-1 block text-[11px] text-slate-500">{{ item.execution_note }}</span>
</span>
<button type="button" @click.stop="toggleSchedule(item)" class="h-5 w-5 shrink-0 rounded-full border-2 text-center text-xs leading-4" :class="item.status==='completed' ? 'border-[#007aff] text-[#007aff]' : 'border-[#ff9500] text-[#ff9500]'">{{ item.status==='completed' ? '✓' : '' }}</button>
</span>
</div>
</div>
</template>
<template v-for="block in timeBlocksFor(panel.days.map(day=>day.key))" :key="block.key">
<template v-if="block.type === 'empty'">
<div class="min-h-11 border-r border-b border-neutral-200 pt-3 pr-3 text-right text-sm text-neutral-400">{{ block.startLabel }}</div>
<div v-for="d in panel.days" :key="d.key+block.key" class="min-h-11 border-r border-b border-neutral-200 px-2 py-2 text-neutral-500">空档已压缩<br>
<span class="text-[11px]">{{ block.startLabel }}—{{ block.endLabel }}</span>
</div>
</template>
<template v-else>
<div class="border-r border-b border-neutral-200 pt-3 pr-3 text-right text-sm text-neutral-400">{{ block.startLabel }}</div>
<div v-for="d in panel.days" :key="d.key+block.key" class="border-r border-b border-neutral-200 space-y-2 p-2">
<div v-for="item in block.items[d.key] || []" :key="item.id" @click="openDetail(item)" class="block w-full rounded-xl border border-neutral-200 border-l-4 bg-[#f5f5f7] px-2 py-2 text-left shadow-sm" :class="item.status==='completed' ? 'border-l-[#007aff] opacity-50' : 'border-l-[#ff9500]'">
<span class="flex items-center gap-1">
<span class="min-w-0 flex-1">
<span class="block truncate text-sm font-semibold" :class="item.status==='completed'?'line-through':''">{{ item.title }}</span>
<span class="block text-xs text-neutral-500">{{ item.start_time?.slice(0,5) }}–{{ item.end_time?.slice(0,5) }}</span>
<span v-if="item.execution_note" class="schedule-note-preview mt-1 block text-[11px] text-slate-500">{{ item.execution_note }}</span>
</span>
<button type="button" @click.stop="toggleSchedule(item)" class="h-5 w-5 shrink-0 rounded-full border-2 text-center text-xs leading-4" :class="item.status==='completed' ? 'border-[#007aff] text-[#007aff]' : 'border-[#ff9500] text-[#ff9500]'">{{ item.status==='completed' ? '✓' : '' }}</button>
</span>
</div>
</div>
</template>
</template>
</div>
</section>
</div>
      </div>
    </main>
    <button @click="goToday" class="fixed bottom-24 left-5 z-20 rounded-full bg-white px-4 py-2 text-sm font-medium text-neutral-700 shadow-lg ring-1 ring-neutral-200">今天</button>
    <button type="button" @click="openOverdue" aria-label="查看过期未完成日程" class="fixed bottom-24 right-5 z-20 flex h-10 w-10 items-center justify-center rounded-full bg-white text-neutral-800 shadow-lg ring-1 ring-neutral-200">
        <svg viewBox="0 0 24 24" class="h-6 w-6 fill-none stroke-current stroke-[2.2]" aria-hidden="true">
          <path d="M4 10.5h16v7A2.5 2.5 0 0 1 17.5 20h-11A2.5 2.5 0 0 1 4 17.5z" />
          <path d="M4 10.5 6.5 5h11l2.5 5.5" />
          <path d="M9 10.5v1.25A1.25 1.25 0 0 0 10.25 13h3.5A1.25 1.25 0 0 0 15 11.75V10.5" />
        </svg>
    </button>
    <div v-if="overdueOpen" class="fixed inset-0 z-[70] flex items-end bg-black/30" @click.self="closeOverdue">
      <section class="flex w-full max-h-[82dvh] flex-col overflow-hidden rounded-t-2xl bg-white p-5 pb-0">
        <div class="flex shrink-0 items-center justify-between gap-4 pb-4">
          <h2 class="text-lg font-semibold text-neutral-900">过期未完成日程</h2>
          <button type="button" class="shrink-0 text-sm text-neutral-500" @click="closeOverdue">关闭</button>
        </div>
        <div class="min-h-0 flex-1 overflow-y-auto pb-[calc(1.25rem+env(safe-area-inset-bottom))]">
          <div v-if="overdueLoading" class="py-12 text-center text-sm text-neutral-400">正在加载…</div>
          <p v-else-if="overdueError" class="py-8 text-center text-sm text-red-600">{{ overdueError }}</p>
          <p v-else-if="!overdueItems.length" class="py-12 text-center text-sm text-neutral-400">暂无过期未完成日程</p>
          <div v-else class="space-y-5">
          <section v-for="group in overdueGroups" :key="group.date">
            <h3 class="sticky top-0 z-10 mb-2 bg-white py-2 text-sm font-medium text-neutral-500">{{ group.date }}</h3>
            <div class="space-y-3">
              <button v-for="item in group.items" :key="item.id" type="button" class="block w-full rounded-xl border border-neutral-200 border-l-4 bg-[#f5f5f7] px-3 py-3 text-left shadow-sm" :class="item.status === 'completed' ? 'border-l-[#007aff] opacity-50' : 'border-l-[#ff9500]'" @click="openOverdueEdit(item)">
                <span class="flex min-w-0 items-center gap-3">
                  <span class="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border-2 text-sm" :class="item.status === 'completed' ? 'border-[#007aff] text-[#007aff]' : 'border-[#ff9500]'" @click.stop="toggleSchedule(item)">{{ item.status === 'completed' ? '✓' : '' }}</span>
                  <span class="min-w-0 flex-1">
                    <span class="block break-all text-base font-semibold leading-5 text-neutral-900" :class="item.status === 'completed' ? 'line-through' : ''">{{ item.title }}</span>
                    <span class="mt-1 block text-sm text-neutral-500">{{ item.is_all_day ? '全天' : `${item.start_time?.slice(0, 5)}–${item.end_time?.slice(0, 5)}` }}</span>
                  </span>
                </span>
              </button>
            </div>
          </section>
          </div>
        </div>
      </section>
    </div>
    <div v-if="printOpen" class="fixed inset-0 z-[70] flex items-end bg-black/30" @click.self="closePrint">
<form @submit.prevent="preparePrint" class="w-full max-h-[88dvh] overflow-y-auto rounded-t-2xl bg-white p-5 pb-[calc(1.25rem+env(safe-area-inset-bottom))]">
<div class="flex items-center justify-between">
<h2 class="text-lg font-semibold">打印周日程</h2>
<button type="button" class="text-sm text-neutral-500" @click="closePrint">关闭</button>
</div>
<p class="mt-1 text-sm text-neutral-500">每个选中周单独打印一张 A4 横向页面。</p>
<div class="mt-4 flex items-center justify-between text-sm">
<span class="font-medium text-neutral-700">选择需要打印的周</span>
<span class="text-neutral-500">已选 {{ selectedPrintWeeks.length }} 周</span>
</div>
<div class="mt-2 max-h-[48dvh] overflow-y-auto rounded-xl border border-neutral-200">
<label v-for="week in printWeeks" :key="week.key" class="flex items-center gap-3 border-b border-neutral-100 px-4 py-3 last:border-b-0">
<input v-model="selectedPrintWeeks" type="checkbox" :value="week.key" class="h-5 w-5 accent-[#007aff]">
<span class="text-sm text-neutral-800">{{ week.label }}</span>
</label>
</div>
<div class="mt-3 flex gap-2 text-sm">
<button type="button" class="rounded-lg bg-neutral-100 px-3 py-2 text-neutral-700" @click="selectAllPrintWeeks">全选</button>
<button type="button" class="rounded-lg bg-neutral-100 px-3 py-2 text-neutral-700" @click="clearPrintWeeks">清空</button>
</div>
<p v-if="printError" class="mt-3 text-sm text-red-600">{{ printError }}</p>
<div class="mt-5 flex gap-3">
<button type="button" class="flex-1 rounded-xl bg-neutral-100 py-3" @click="closePrint">取消</button>
<button type="submit" class="flex-1 rounded-xl bg-[#007aff] py-3 font-medium text-white" :disabled="printLoading">{{ printLoading ? '准备中…' : '打印' }}</button>
</div>
</form>
</div>
    <section v-if="selectedPrintWeekObjects.length" class="schedule-print-root">
<article v-for="week in selectedPrintWeekObjects" :key="week.key" class="schedule-print-week">
<div class="schedule-print-grid schedule-print-date-header">
<div class="schedule-print-label">时间</div>
<div v-for="day in printDays(week)" :key="day.key" class="schedule-print-day">{{ day.month }}月{{ day.date }}日 周{{ day.name }}</div>
</div>
<div class="schedule-print-grid schedule-print-body">
<div class="schedule-print-label">全天</div>
<div v-for="day in printDays(week)" :key="`all-${day.key}`" class="schedule-print-cell">
<div v-for="item in printAllDayItems(day.key)" :key="item.id" class="schedule-print-task">□ {{ item.title }}</div>
</div>
<template v-for="row in printTimeRows(week)" :key="`${week.key}-${row.key}`">
<template v-if="row.type === 'empty'">
<div class="schedule-print-time schedule-print-empty"><span>{{ row.startLabel }}</span><span>{{ row.endLabel }}</span></div>
<div v-for="day in printDays(week)" :key="`${day.key}-${row.key}`" class="schedule-print-cell schedule-print-empty"></div>
</template>
<template v-else>
<div class="schedule-print-time">{{ row.startLabel }}</div>
<div v-for="day in printDays(week)" :key="`${day.key}-${row.key}`" class="schedule-print-cell">
<div v-for="item in row.items[day.key] || []" :key="item.id" class="schedule-print-task">□ {{ item.title }}<small>{{ item.start_time?.slice(0,5) }}–{{ item.end_time?.slice(0,5) }}</small></div>
</div>
</template>
</template>
</div>
</article>
    </section>
    <div v-if="detailItem" class="fixed inset-0 z-[60] flex items-end bg-black/30" @click.self="closeDetail">
<section class="w-full max-h-[82dvh] overflow-y-auto rounded-t-2xl bg-white p-5 pb-[calc(1.25rem+env(safe-area-inset-bottom))]">
<div class="flex items-start justify-between gap-4">
<div class="min-w-0">
<h2 class="break-all text-lg font-semibold">{{ detailItem.title }}</h2>
<p class="mt-1 text-sm text-neutral-500">{{ detailItem.scheduled_date }} · {{ detailItem.is_all_day ? '全天' : `${detailItem.start_time?.slice(0,5)}–${detailItem.end_time?.slice(0,5)}` }}</p>
</div>
<button type="button" class="shrink-0 text-sm text-neutral-500" @click="closeDetail">关闭</button>
</div>
<div class="mt-5 flex items-center justify-between rounded-xl bg-neutral-100 px-4 py-3">
<span class="text-sm font-medium text-neutral-700">{{ detailItem.status === 'completed' ? '已完成' : '未完成' }}</span>
<button type="button" @click="toggleSchedule(detailItem)" class="rounded-lg bg-white px-3 py-2 text-sm font-medium text-[#007aff] shadow-sm">{{ detailItem.status === 'completed' ? '取消完成' : '标记完成' }}</button>
</div>
<div class="mt-5">
<div class="flex items-center justify-between">
<h3 class="text-sm font-semibold text-neutral-800">执行记录</h3>
<span class="text-xs text-neutral-400">{{ noteDraft.length }}/500</span>
</div>
<textarea v-model="noteDraft" rows="6" maxlength="500" placeholder="记录这次日程发生了什么，例如未完成原因、执行过程或完成结果。" class="mt-2 w-full rounded-xl bg-neutral-100 p-3 text-sm outline-none ring-[#007aff] focus:ring-2" />
<p v-if="noteError" class="mt-2 text-sm text-red-600">{{ noteError }}</p>
<button type="button" @click="saveNote" class="mt-3 w-full rounded-xl bg-[#007aff] py-3 font-medium text-white" :disabled="noteSaving">{{ noteSaving ? '保存中…' : '保存记录' }}</button>
</div>
<button type="button" @click="openEdit(detailItem); closeDetail()" class="mt-3 w-full rounded-xl border border-neutral-200 py-3 text-sm font-medium text-neutral-700">编辑日程</button>
</section>
</div>
    <div v-if="editingItem" class="fixed inset-0 z-[60] flex w-screen items-end bg-black/30" @click.self="requestCloseEdit">
<form @submit.prevent="requestSave" class="schedule-form w-full max-w-none box-border max-h-[92dvh] overflow-y-auto rounded-t-2xl bg-white p-5 pb-[calc(1.25rem+env(safe-area-inset-bottom))] space-y-3">
<div class="flex items-center justify-between">
<h2 class="text-lg font-semibold">编辑日程</h2>
<div class="flex items-center gap-4 text-sm">
<button type="button" class="text-red-500" @click="requestDelete">删除</button>
<button type="button" @click="requestCloseEdit">关闭</button>
<button type="submit" class="font-medium text-[#007aff]">保存</button>
</div>
</div>
<input v-model="editForm.title" required maxlength="200" placeholder="任务名称" class="w-full rounded-lg bg-neutral-100 p-3 text-sm">
<label class="flex gap-2 text-sm">
<input type="checkbox" v-model="editForm.is_all_day"> 全天</label>
<template v-if="!editForm.is_all_day">
<input v-model="editForm.start_time" type="time" required class="w-full rounded-lg bg-neutral-100 p-3 text-sm">
<input v-model="editForm.end_time" type="time" required class="w-full rounded-lg bg-neutral-100 p-3 text-sm">
</template>
<div>
<span class="mb-2 block text-sm font-medium text-neutral-700">重复</span>
<div class="grid grid-cols-4 gap-1 rounded-xl bg-neutral-100 p-1">
<button v-for="option in recurrenceOptions" :key="option.value" type="button" @click="selectRecurrence(editForm, option.value)" class="rounded-lg py-2.5 text-xs font-medium" :class="isRecurrenceSelected(editForm, option.value) ? 'bg-white text-[#007aff] shadow-sm' : 'text-neutral-500'">{{ option.label }}</button>
</div>
<p v-if="editForm.customConfigured" class="mt-2 text-sm text-neutral-500">{{ recurrenceDescription(editForm) }}</p>
<div v-if="editForm.recurrence_type !== 'NONE'" class="mt-3 space-y-3">
<div class="grid grid-cols-2 gap-2">
<button type="button" @click="editForm.recurrence_until=''" class="rounded-xl border p-3 text-sm" :class="!editForm.recurrence_until ? 'border-[#007aff] bg-[#f0f7ff] text-[#007aff]' : 'border-neutral-200'">永久</button>
<button type="button" @click="editForm.recurrence_until=editForm.recurrence_until || editingItem.scheduled_date" class="rounded-xl border p-3 text-sm" :class="editForm.recurrence_until ? 'border-[#007aff] bg-[#f0f7ff] text-[#007aff]' : 'border-neutral-200'">截止日期</button>
</div>
<input v-if="editForm.recurrence_until" v-model="editForm.recurrence_until" :min="editingItem.scheduled_date" type="date" class="w-full rounded-xl bg-neutral-100 p-3 text-sm">
<label v-if="!editForm.recurrence_until" class="flex items-center gap-2 text-sm text-neutral-600"><span>重复次数</span><input v-model.number="editForm.recurrence_count" min="1" type="number" placeholder="永久" class="w-24 rounded-lg bg-neutral-100 p-2"></label>
</div>
</div>
<p v-if="editError" class="text-sm text-red-600">{{ editError }}</p>
</form>
</div>
    <div v-if="formOpen" class="fixed inset-0 z-[60] flex w-screen items-end bg-black/30" @click.self="formOpen=false">
<form @submit.prevent="createWithDeadline" class="schedule-form w-full max-w-none box-border max-h-[92dvh] overflow-y-auto rounded-t-2xl bg-white pb-[calc(1.25rem+env(safe-area-inset-bottom))]">
<div class="flex items-center justify-between border-b border-neutral-200 px-5 py-4">
<h2 class="text-lg font-semibold">添加日程</h2>
<div class="flex items-center gap-4 text-sm">
<button type="button" class="text-neutral-600" @click="formOpen=false">关闭</button>
<button type="submit" class="font-semibold text-[#007aff]">保存</button>
</div>
</div>
<div class="space-y-5 px-5 py-5">
<label class="block">
<span class="mb-2 block text-sm font-medium text-neutral-700">名称</span>
<input v-model="form.title" required maxlength="200" placeholder="输入日程名称" class="w-full rounded-xl bg-neutral-100 px-4 py-3 text-base outline-none ring-[#007aff] focus:ring-2">
</label>
<div class="flex min-w-0 items-center gap-3">
<label class="flex min-w-0 flex-1 items-center gap-3">
<span class="w-16 shrink-0 text-base font-medium text-neutral-700">日期：</span>
<input v-model="form.start_date" :min="todayKey" type="date" class="box-border min-w-0 w-0 max-w-full flex-1 rounded-xl bg-neutral-100 px-3 py-2.5 text-base text-neutral-800 outline-none ring-[#007aff] focus:ring-2">
</label>
<div class="flex shrink-0 items-center gap-2">
<span class="text-base font-medium text-neutral-700">全天</span>
<button type="button" role="switch" :aria-checked="form.is_all_day" @click="form.is_all_day=!form.is_all_day" class="relative h-7 w-12 shrink-0 rounded-full transition-colors" :class="form.is_all_day ? 'bg-[#007aff]' : 'bg-neutral-300'">
<span class="absolute left-1 top-1 h-5 w-5 rounded-full bg-white shadow transition-transform" :class="form.is_all_day ? 'translate-x-5' : 'translate-x-0'">
</span>
</button>
</div>
</div>
<div v-if="!form.is_all_day" class="grid grid-cols-2 gap-3">
<label>
<span class="mb-2 block text-sm font-medium text-neutral-700">开始时间</span>
<input v-model="form.start_time" type="time" required class="w-full rounded-xl bg-neutral-100 px-3 py-3 text-base outline-none ring-[#007aff] focus:ring-2">
</label>
<label>
<span class="mb-2 block text-sm font-medium text-neutral-700">结束时间</span>
<input v-model="form.end_time" type="time" required class="w-full rounded-xl bg-neutral-100 px-3 py-3 text-base outline-none ring-[#007aff] focus:ring-2">
</label>
</div>
<div>
<span class="mb-2 block text-sm font-medium text-neutral-700">重复</span>
<div class="grid grid-cols-4 gap-1 rounded-xl bg-neutral-100 p-1">
<button v-for="option in recurrenceOptions" :key="option.value" type="button" @click="selectRecurrence(form, option.value)" class="rounded-lg py-2.5 text-xs font-medium transition-colors" :class="isRecurrenceSelected(form, option.value) ? 'bg-white text-[#007aff] shadow-sm' : 'text-neutral-500'">{{ option.label }}</button>
</div>
<p v-if="form.customConfigured" class="mt-2 text-sm text-neutral-500">{{ recurrenceDescription(form) }}</p>
</div>
<div v-if="form.recurrence_type !== 'NONE'" class="space-y-3">
<span class="block text-sm font-medium text-neutral-700">结束</span>
<div class="grid grid-cols-2 gap-2">
<button type="button" @click="form.recurrence_until=''" class="rounded-xl border p-3 text-sm" :class="!form.recurrence_until ? 'border-[#007aff] bg-[#f0f7ff] text-[#007aff]' : 'border-neutral-200'">永久</button>
<button type="button" @click="form.recurrence_until=form.recurrence_until || dateWithOffset(form.start_date, 30)" class="rounded-xl border p-3 text-sm" :class="form.recurrence_until ? 'border-[#007aff] bg-[#f0f7ff] text-[#007aff]' : 'border-neutral-200'">截止日期</button>
</div>
<input v-if="form.recurrence_until" v-model="form.recurrence_until" :min="form.start_date" type="date" class="w-full rounded-xl bg-neutral-100 p-3 text-sm">
<label v-if="!form.recurrence_until" class="flex items-center gap-2 text-sm text-neutral-600"><span>重复次数</span><input v-model.number="form.recurrence_count" min="1" type="number" placeholder="永久" class="w-24 rounded-lg bg-neutral-100 p-2"></label>
</div>
<p v-if="formError" class="text-sm text-red-600">{{ formError }}</p>
</div>
</form>
</div>
    <div v-if="customOpen" class="fixed inset-0 z-[90] flex items-end bg-black/35" @click.self="cancelCustom">
<form @submit.prevent="confirmCustom" class="w-full max-h-[92dvh] overflow-y-auto rounded-t-2xl bg-white pb-[calc(1.25rem+env(safe-area-inset-bottom))]">
<div class="flex items-center justify-between border-b border-neutral-200 px-5 py-4"><h2 class="text-lg font-semibold">自定义重复</h2><button type="button" class="text-sm text-neutral-500" @click="cancelCustom">关闭</button></div>
<div class="space-y-4 px-5 py-5">
<div class="rounded-2xl border border-neutral-200 bg-neutral-50">
<div class="flex items-center justify-between border-b border-neutral-200 px-4 py-4"><span class="text-base font-medium">频率</span><select :value="customForm.recurrence_type.startsWith('MONTHLY') ? 'MONTH' : customForm.recurrence_type" @change="setCustomFrequency(($event.target as HTMLSelectElement).value)" class="bg-transparent text-right text-base text-neutral-500 outline-none"><option value="DAILY">天</option><option value="WEEKLY">周</option><option value="MONTH">月</option></select></div>
<label class="flex items-center justify-between px-4 py-4"><span class="text-base font-medium">每</span><input v-model.number="customForm.interval" min="1" required type="number" class="w-14 rounded-lg bg-white p-2 text-center text-lg shadow-sm"></label>
</div>
<p class="px-1 text-sm text-neutral-500">{{ customPreview }}</p>
<div v-if="customForm.recurrence_type === 'WEEKLY'" class="rounded-2xl border border-neutral-200 px-4 py-3"><p class="mb-2 text-base font-medium">选择星期</p><div class="divide-y divide-neutral-100"><button v-for="day in weekdayOptions" :key="day.value" type="button" @click="toggleWeekday(customForm, day.value)" class="flex w-full items-center justify-between py-3 text-left text-base"><span>星期{{ day.label }}</span><span :class="customForm.weekdays.includes(day.value) ? 'text-[#007aff]' : 'text-neutral-300'">{{ customForm.weekdays.includes(day.value) ? '✓' : '○' }}</span></button></div></div>
<div v-if="customForm.recurrence_type === 'MONTHLY_DATE' || customForm.recurrence_type === 'MONTHLY_NTH_WEEKDAY'" class="space-y-3">
<div class="flex rounded-xl bg-neutral-100 p-1"><button type="button" @click="customForm.recurrence_type='MONTHLY_DATE'" class="flex-1 rounded-lg py-2 text-sm" :class="customForm.recurrence_type === 'MONTHLY_DATE' ? 'bg-white text-[#007aff] shadow-sm' : 'text-neutral-500'">按日期</button><button type="button" @click="customForm.recurrence_type='MONTHLY_NTH_WEEKDAY'" class="flex-1 rounded-lg py-2 text-sm" :class="customForm.recurrence_type === 'MONTHLY_NTH_WEEKDAY' ? 'bg-white text-[#007aff] shadow-sm' : 'text-neutral-500'">按第几个星期几</button></div>
<div v-if="customForm.recurrence_type === 'MONTHLY_DATE'" class="rounded-2xl border border-neutral-200 px-4 py-3"><p class="mb-3 text-base font-medium">日期</p><div class="grid grid-cols-7 overflow-hidden rounded-xl border border-neutral-200"><button v-for="day in 31" :key="day" type="button" @click="customForm.month_day=day" class="border-b border-r border-neutral-100 py-3 text-sm last:border-r-0" :class="customForm.month_day === day ? 'bg-[#007aff] text-white' : 'bg-white text-neutral-800'">{{ day }}</button></div></div>
<div v-else class="grid grid-cols-2 gap-3"><select v-model.number="customForm.nth_week" class="rounded-xl bg-neutral-100 p-3 text-sm"><option v-for="n in [1,2,3,4,5]" :key="n" :value="n">第{{ n }}个</option></select><select v-model.number="customForm.nth_weekday" class="rounded-xl bg-neutral-100 p-3 text-sm"><option v-for="day in weekdayOptions" :key="day.value" :value="day.value">星期{{ day.label }}</option></select></div>
</div>
<div class="grid grid-cols-2 gap-3"><button type="button" @click="cancelCustom" class="rounded-xl bg-neutral-100 py-3.5 text-sm font-medium">取消</button><button type="submit" class="rounded-xl bg-[#007aff] py-3.5 text-sm font-medium text-white">确认</button></div>
</div>
</form>
</div>
    <div v-if="confirmAction" class="fixed inset-0 z-[80] flex items-end bg-black/35" @click.self="cancelConfirm">
<div class="w-full rounded-t-2xl bg-white px-5 pb-[calc(1.25rem+env(safe-area-inset-bottom))] pt-5 shadow-2xl">
<h2 class="text-lg font-semibold text-neutral-900">{{ confirmTitle }}</h2>
<p class="mt-2 text-sm leading-6 text-neutral-500">{{ confirmMessage }}</p>
<template v-if="confirmAction === 'delete' && editingItem?.recurrence_type !== 'NONE'">
<p class="mt-5 text-sm font-medium text-neutral-700">删除范围</p>
<div class="mt-2 grid grid-cols-2 gap-2">
<button type="button" @click="deleteScope='single'" class="rounded-xl border p-3 text-sm" :class="deleteScope==='single'?'border-red-200 bg-red-50 text-red-600':'border-neutral-200'">仅删除此日程</button>
<button type="button" @click="deleteScope='following'" class="rounded-xl border p-3 text-sm" :class="deleteScope==='following'?'border-red-200 bg-red-50 text-red-600':'border-neutral-200'">删除此日程及以后</button>
</div>
</template>
<div class="mt-4 space-y-2">
<button type="button" @click="confirmPrimary" class="w-full rounded-xl py-3 text-base font-semibold text-white" :class="confirmAction === 'delete' ? 'bg-red-500' : 'bg-[#007aff]'">{{ confirmPrimaryLabel }}</button>
<button type="button" @click="cancelConfirm" class="w-full rounded-2xl bg-neutral-100 py-3.5 text-base font-semibold text-neutral-800">取消</button>
</div>
</div>
</div>
  </div>
 </template>

<style scoped>
.schedule-form { width: 100% !important; min-width: 0; max-width: 100% !important; box-sizing: border-box; overflow-x: hidden; }
.schedule-form > div,
.schedule-form label { width: 100%; min-width: 0; max-width: 100%; box-sizing: border-box; }
.schedule-form :deep(input.w-full),
.schedule-form :deep(select.w-full),
.schedule-form :deep(textarea.w-full) { width: 100% !important; min-width: 0; }
.schedule-form :deep(input:not([type="checkbox"])),
.schedule-form :deep(select),
.schedule-form :deep(textarea) { box-sizing: border-box; max-width: 100%; }
.schedule-form :deep(input[type="date"]),
.schedule-form :deep(input[type="time"]),
.schedule-form :deep(select) {
  display: block;
  width: 100% !important;
  min-width: 0 !important;
  max-width: 100% !important;
  -webkit-appearance: none;
  appearance: none;
}
@media (max-width: 767px) {
  .schedule-form :deep(input:not([type="checkbox"])),
  .schedule-form :deep(select),
  .schedule-form :deep(textarea) {
    font-size: 16px !important;
    -webkit-text-size-adjust: 100%;
  }
}
:deep([class~="w-[118px]"]) { width: 84px !important; }
:deep([class~="grid-cols-[118px_1fr]"]) { grid-template-columns: 84px minmax(0, 1fr) !important; }
:deep([class~="grid-cols-[96px_repeat(2,minmax(0,1fr))]"]) { grid-template-columns: 72px repeat(2, minmax(0, 1fr)) !important; }
.schedule-note-preview { display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2; overflow: hidden; }
.schedule-swipe-viewport { width: 100%; min-width: 0; overflow-x: hidden; }
.schedule-print-root { display: none; }
:global(body.printing-schedule .schedule-page) { display: block !important; height: auto !important; min-height: 0 !important; overflow: visible !important; }
:global(body.printing-schedule .schedule-page > :not(.schedule-print-root)) { display: none !important; }
:global(body.printing-schedule .schedule-print-root) { display: block !important; }
:global(body.printing-schedule .schedule-print-week) { display: flex !important; flex-direction: column !important; width: 100% !important; height: 180mm !important; max-height: 180mm !important; box-sizing: border-box !important; }
:global(body.printing-schedule .schedule-print-date-header) { flex: 0 0 auto !important; }
:global(body.printing-schedule .schedule-print-body) { flex: 1 1 auto !important; min-height: 0 !important; align-content: stretch !important; grid-auto-rows: 1fr; }
@media print {
  @page { size: A4 landscape; margin: 10mm; }
  :global(body.printing-schedule *) { visibility: hidden !important; }
  :global(body.printing-schedule .schedule-print-root),
  :global(body.printing-schedule .schedule-print-root *) { visibility: visible !important; }
  :global(body.printing-schedule .schedule-print-root) { display: block !important; position: static; width: 100%; background: white; color: #111827; }
  .schedule-print-week { display: flex; flex-direction: column; width: 100%; height: 180mm; max-height: 180mm; overflow: hidden; page-break-after: always; break-after: page; break-inside: avoid; page-break-inside: avoid; font-family: Arial, sans-serif; transform-origin: top left; box-sizing: border-box; }
  .schedule-print-week:last-child { page-break-after: auto; break-after: auto; }
  .schedule-print-grid { display: grid; grid-template-columns: 16mm repeat(7, minmax(0, 1fr)); border-top: 0.25mm solid #9ca3af; border-left: 0.25mm solid #9ca3af; }
  .schedule-print-date-header { flex: 0 0 auto; }
  .schedule-print-body { flex: 1 1 auto; min-height: 0; align-content: stretch; grid-auto-rows: 1fr; }
  .schedule-print-label, .schedule-print-day, .schedule-print-time, .schedule-print-cell { min-width: 0; border-right: 0.25mm solid #9ca3af; border-bottom: 0.25mm solid #9ca3af; box-sizing: border-box; }
  .schedule-print-label, .schedule-print-day, .schedule-print-time { padding: 1mm; text-align: center; font-size: 7pt; font-weight: 400; line-height: 1.15; }
  .schedule-print-day { min-height: 8mm; }
  .schedule-print-body .schedule-print-cell { min-height: 7mm; padding: 0.5mm; }
  .schedule-print-time { min-height: 7mm; display: flex; flex-direction: column; justify-content: space-between; }
  .schedule-print-task { margin: 0.5mm 0; padding: 0.5mm; border: 0.2mm solid #d1d5db; border-radius: 1mm; font-size: 7pt; line-height: 1.15; overflow-wrap: anywhere; }
  .schedule-print-task small { display: block; margin-top: 0.5mm; color: #4b5563; font-size: 6pt; }
  .schedule-print-body > :nth-last-child(-n+8) { border-bottom: 0.25mm solid #9ca3af; }
}
</style>

<script setup lang="ts">
import type { ScheduleOccurrence } from '~/types'
definePageMeta({ layout: 'default', middleware: 'auth' })
const { api } = useApi(); const now = new Date(); const selectedDate = ref(now.toISOString().slice(0,10)); const weekStart = ref(new Date(now)); weekStart.value.setDate(now.getDate() - ((now.getDay() + 6) % 7))
const recurrenceOptions = [{value:'NONE',label:'不重复'},{value:'DAILY',label:'每天'},{value:'WEEKLY',label:'每周'},{value:'MONTHLY_DATE',label:'每月'},{value:'YEARLY',label:'每年'},{value:'WORKDAY',label:'工作日'},{value:'REST_DAY',label:'休息日'},{value:'CUSTOM',label:'自定义'}] as const
const weekdayOptions = [{value:1,label:'一'},{value:2,label:'二'},{value:3,label:'三'},{value:4,label:'四'},{value:5,label:'五'},{value:6,label:'六'},{value:0,label:'日'}]
const view = ref<'day'|'week'>('day'); const items = ref<ScheduleOccurrence[]>([]); const loading = ref(false); const formOpen = ref(false); const formError = ref(''); const pickerOpen = ref(false); const swipeStart = ref(0); const weekPicker = ref(''); const editingItem = ref<ScheduleOccurrence|null>(null); const deleteConfirm = ref(false); const confirmAction = ref<"save"|"delete"|"discard"|null>(null); const editSnapshot = ref(""); const deleteScope = ref<'single'|'following'>('single'); const editScope = ref<'single'|'following'>('single'); const editError = ref(''); const editForm = reactive({title:'',is_all_day:false,start_time:'09:00',end_time:'10:00',recurrence_type:'NONE',interval:1,weekdays:[] as number[],month_day:null as number|null,nth_week:1,nth_weekday:0,recurrence_until:'',recurrence_count:null as number|null,customConfigured:false}); const overdueItem = ref<ScheduleOccurrence|null>(null); const overdueReason = ref(''); const scheduleSwipe = reactive({startX:0,startY:0,offset:0,horizontal:false,animating:false,previewDate:selectedDate.value})
const form = reactive({ title:'', is_all_day:false, start_date:selectedDate.value, start_time:'09:00', end_time:'10:00', recurrence_type:'NONE', interval:1, weekdays:[] as number[], month_day:null as number|null, nth_week:1, nth_weekday:0, recurrence_until:'', recurrence_count:null as number|null,customConfigured:false })
const detailItem = ref<ScheduleOccurrence|null>(null); const noteDraft = ref(''); const noteSaving = ref(false); const noteError = ref('')
const overdueOpen = ref(false); const overdueItems = ref<ScheduleOccurrence[]>([]); const overdueLoading = ref(false); const overdueError = ref('')
const overdueGroups=computed(()=>{const grouped=new Map<string,ScheduleOccurrence[]>();for(const item of overdueItems.value){const group=grouped.get(item.scheduled_date)||[];group.push(item);grouped.set(item.scheduled_date,group)}return [...grouped.entries()].sort(([a],[b])=>b.localeCompare(a)).map(([date,items])=>({date,items}))})
const printOpen = ref(false); const printLoading = ref(false); const printError = ref(''); const selectedPrintWeeks = ref<string[]>([]); const printItems = ref<ScheduleOccurrence[]>([])
const swipeTrack = ref<HTMLElement|null>(null); const gestureAxis = ref<'none'|'horizontal'|'vertical'>('none')
const customOpen = ref(false); const customTarget = ref<'create'|'edit'|null>(null); const customForm = reactive({recurrence_type:'DAILY',interval:1,weekdays:[] as number[],month_day:null as number|null,nth_week:1,nth_weekday:0,recurrence_until:'',recurrence_count:null as number|null,customConfigured:true})
const modalOpen = computed(() => Boolean(formOpen.value || editingItem.value || detailItem.value || printOpen.value || customOpen.value || confirmAction.value || overdueOpen.value))
function isCustomRecurrence(type:string){return ['DAILY','WEEKLY','MONTHLY_DATE','MONTHLY_NTH_WEEKDAY'].includes(type)}
function isRecurrenceSelected(target:any, type:string){return type==='CUSTOM' ? target.customConfigured : !target.customConfigured && target.recurrence_type===type}
function selectRecurrence(target:any, type:string){if(type==='CUSTOM'){openCustom(target===editForm?'edit':'create');return}target.customConfigured=false;target.recurrence_type=type;if(type==='NONE'){target.recurrence_until='';target.recurrence_count=null}}
function openCustom(mode:'create'|'edit'){customTarget.value=mode;const target=mode==='edit'?editForm:form;Object.assign(customForm,{recurrence_type:isCustomRecurrence(target.recurrence_type)?target.recurrence_type:'DAILY',interval:target.interval||1,weekdays:[...target.weekdays],month_day:target.month_day,nth_week:target.nth_week||1,nth_weekday:target.nth_weekday??0,recurrence_until:target.recurrence_until,recurrence_count:target.recurrence_count,customConfigured:true});customOpen.value=true}
function cancelCustom(){customOpen.value=false;customTarget.value=null}
function setCustomFrequency(value:string){customForm.recurrence_type=value==='MONTH'?'MONTHLY_DATE':value}
function confirmCustom(){if(customForm.interval<1)return;if(customForm.recurrence_type==='WEEKLY'&&!customForm.weekdays.length)customForm.weekdays=[sundayWeekday(new Date(`${(customTarget.value==='create'?form.start_date:editingItem.value?.scheduled_date)||todayKey}T12:00:00`))];if(customForm.recurrence_type==='MONTHLY_DATE'&&!customForm.month_day)customForm.month_day=Number(((customTarget.value==='create'?form.start_date:editingItem.value?.scheduled_date)||todayKey).slice(8,10));const target=customTarget.value==='edit'?editForm:form;Object.assign(target,{...customForm,customConfigured:true});cancelCustom()}
const customPreview = computed(()=>recurrenceDescription(customForm))
function recurrenceDescription(target:any){const count=Number(target.interval||1);const number=count===1?'一':count===2?'两':String(count);if(target.recurrence_type==='DAILY')return `每${number}天重复一次。`;if(target.recurrence_type==='YEARLY')return `每${number}年重复一次。`;if(target.recurrence_type==='WEEKLY'){const days=target.weekdays.map((value:number)=>`星期${weekdayOptions[value].label}`).join('、');return `每${number}周的${days}重复。`}if(target.recurrence_type==='MONTHLY_DATE')return `每${number}个月的${target.month_day || ''}号重复。`;if(target.recurrence_type==='MONTHLY_NTH_WEEKDAY')return `每${number}个月的第${target.nth_week}个星期${weekdayOptions[target.nth_weekday]?.label}重复。`;return ''}
function sundayWeekday(value:Date){return value.getDay()}
function toggleWeekday(target:any, value:number){target.weekdays=target.weekdays.includes(value)?target.weekdays.filter((item:number)=>item!==value):[...target.weekdays,value].sort((a:number,b:number)=>a-b)}
const dateKey=(d:Date)=>d.toISOString().slice(0,10); const todayKey=dateKey(now); const dateWithOffset=(key:string,offset:number)=>{const d=new Date(`${key}T12:00:00`);d.setDate(d.getDate()+offset);return dateKey(d)}; const weekStartFor=(key:string)=>{const d=new Date(`${key}T12:00:00`);d.setDate(d.getDate()-((d.getDay()+6)%7));return d}; const dayInfo=(key:string)=>{const d=new Date(`${key}T12:00:00`);return {key,date:d.getDate(),month:d.getMonth()+1,name:['日','一','二','三','四','五','六'][d.getDay()],isToday:key===todayKey}}; const daysForWeek=(start:Date)=>Array.from({length:7},(_,i)=>{const d=new Date(start);d.setDate(d.getDate()+i);return dayInfo(dateKey(d))}); const weekDays=computed(()=>daysForWeek(weekStart.value)); const headerDate=computed(()=>scheduleSwipe.previewDate||selectedDate.value); const headerWeekDays=computed(()=>daysForWeek(weekStartFor(headerDate.value))); const headerSelectedDay=computed(()=>dayInfo(headerDate.value)); const selectedIndex=computed(()=>Math.max(0,weekDays.value.findIndex(d=>d.key===selectedDate.value))); const selectedDay=computed(()=>dayInfo(selectedDate.value)); const detailDays=computed(()=>[dayInfo(selectedDate.value),dayInfo(dateWithOffset(selectedDate.value,1))]); const headerRangeLabel=computed(()=>`${headerWeekDays.value[0].key.slice(0,4)}年${headerWeekDays.value[0].month}月${headerWeekDays.value[0].date}日-${headerWeekDays.value[6].month}月${headerWeekDays.value[6].date}日`); const headerCompactRangeLabel=computed(()=>`${headerWeekDays.value[0].month}月${headerWeekDays.value[0].date}日-${headerWeekDays.value[6].date}日`); const rangeLabel=headerRangeLabel; const compactRangeLabel=headerCompactRangeLabel; const hours=Array.from({length:24},(_,i)=>i)
const printWeeks=computed(()=>{const first=weekStartFor(selectedDate.value);const result:{key:string,start:string,end:string,label:string}[]=[];for(let index=0;index<52;index++){const cursor=new Date(first);cursor.setDate(cursor.getDate()+index*7);const start=dateKey(cursor);const end=dateWithOffset(start,6);result.push({key:start,start,end,label:`${start.replace(/-/g,'年').replace(/年(\d{2})$/, '月$1日')}—${end.replace(/-/g,'年').replace(/年(\d{2})$/, '月$1日')}`})}return result})
const selectedPrintWeekObjects=computed(()=>printWeeks.value.filter(week=>selectedPrintWeeks.value.includes(week.key)))
const todayItems=computed(()=>items.value.filter(x=>x.scheduled_date===selectedDate.value)); const allDay=computed(()=>todayItems.value.filter(x=>x.is_all_day)); const timeToMinute=(time?:string|null)=>{const [hour,minute]=(time||'00:00').split(':').map(Number);return hour*60+minute}; const minuteLabel=(minute:number)=>`${String(Math.floor(minute/60)).padStart(2,'0')}:${String(minute%60).padStart(2,'0')}`
type TimelineBlock={type:'empty',key:string,startLabel:string,endLabel:string}|{type:'tasks',key:string,startLabel:string,items:Record<string,ScheduleOccurrence[]>}
type PrintTimeRow={type:'empty',key:string,startLabel:string,endLabel:string}|{type:'tasks',key:string,startLabel:string,items:Record<string,ScheduleOccurrence[]>}
const buildTimeBlocks=(days:string[]):TimelineBlock[]=>{const scheduleItems=items.value.filter(item=>days.includes(item.scheduled_date)&&!item.is_all_day&&item.start_time&&item.end_time);const boundaries=new Set([0,1440]);scheduleItems.forEach(item=>{boundaries.add(timeToMinute(item.start_time));boundaries.add(timeToMinute(item.end_time))});const points=[...boundaries].filter(point=>point>=0&&point<=1440).sort((a,b)=>a-b);return points.flatMap((point,index)=>{const starting=scheduleItems.filter(item=>timeToMinute(item.start_time)===point);if(starting.length){const grouped=Object.fromEntries(days.map(day=>[day,starting.filter(item=>item.scheduled_date===day)]));return [{type:'tasks' as const,key:`tasks-${point}`,startLabel:minuteLabel(point),items:grouped}]}const next=points[index+1];return next?[{type:'empty' as const,key:`empty-${point}-${next}`,startLabel:minuteLabel(point),endLabel:minuteLabel(next)}]:[]})}
const dayTimeBlocks=computed(()=>buildTimeBlocks([selectedDate.value])); const weekTimeBlocks=computed(()=>buildTimeBlocks(detailDays.value.map(day=>day.key))); const timeBlocksFor=(days:string[])=>buildTimeBlocks(days); const allDayFor=(key:string)=>items.value.filter(item=>item.scheduled_date===key&&item.is_all_day); const dayPanels=computed(()=>[-1,0,1].map(offset=>({key:dateWithOffset(selectedDate.value,offset)}))); const weekPanels=computed(()=>[-1,0,1].map(offset=>{const key=dateWithOffset(selectedDate.value,offset);return {key,days:[dayInfo(key),dayInfo(dateWithOffset(key,1))]}})); const scheduleSwipeTrackStyle=computed(()=>({transform:`translateX(calc(-33.333333% + ${scheduleSwipe.offset}px))`,transition:scheduleSwipe.animating?'transform 280ms cubic-bezier(.22,.61,.36,1)':'none',touchAction:'pan-y'}))
async function load(){loading.value=true;try{items.value=await api<ScheduleOccurrence[]>(`/schedules?start_date=${dateWithOffset(weekDays.value[0].key,-2)}&end_date=${dateWithOffset(weekDays.value[6].key,2)}`)}finally{loading.value=false}} function moveWeek(delta:number){const d=new Date(weekStart.value);d.setDate(d.getDate()+delta*7);weekStart.value=d;selectedDate.value=dateKey(d);scheduleSwipe.previewDate=selectedDate.value;load()} async function moveDay(delta:number){const next=dateWithOffset(selectedDate.value,delta);const nextWeekStart=weekStartFor(next);const shouldLoad=dateKey(nextWeekStart)!==dateKey(weekStart.value);selectedDate.value=next;weekStart.value=nextWeekStart;scheduleSwipe.previewDate=next;if(shouldLoad)await load()} function selectDay(key:string){selectedDate.value=key;weekStart.value=weekStartFor(key);scheduleSwipe.previewDate=key;load()} function updateSwipePreview(){const width=window.innerWidth;if(Math.abs(scheduleSwipe.offset)>=width/2){scheduleSwipe.previewDate=dateWithOffset(selectedDate.value,scheduleSwipe.offset<0?1:-1)}else scheduleSwipe.previewDate=selectedDate.value} function startScheduleSwipe(event:TouchEvent){if(scheduleSwipe.animating)return;const touch=event.touches[0];scheduleSwipe.startX=touch.clientX;scheduleSwipe.startY=touch.clientY;scheduleSwipe.offset=0;scheduleSwipe.horizontal=false;scheduleSwipe.previewDate=selectedDate.value} function moveScheduleSwipe(event:TouchEvent){if(scheduleSwipe.animating)return;const touch=event.touches[0];const dx=touch.clientX-scheduleSwipe.startX;const dy=touch.clientY-scheduleSwipe.startY;if(!scheduleSwipe.horizontal){if(Math.abs(dx)<12)return;if(Math.abs(dx)<=Math.abs(dy))return;scheduleSwipe.horizontal=true}scheduleSwipe.offset=dx;updateSwipePreview()} async function endScheduleSwipe(){if(!scheduleSwipe.horizontal){cancelScheduleSwipe();return}const width=window.innerWidth;const direction=Math.abs(scheduleSwipe.offset)>=width/2?(scheduleSwipe.offset<0?1:-1):0;if(!direction){scheduleSwipe.animating=true;scheduleSwipe.offset=0;scheduleSwipe.previewDate=selectedDate.value;window.setTimeout(()=>scheduleSwipe.animating=false,180);return}scheduleSwipe.animating=true;scheduleSwipe.offset=-direction*width;await new Promise(resolve=>window.setTimeout(resolve,180));await moveDay(direction);scheduleSwipe.offset=direction*width;await nextTick();requestAnimationFrame(()=>{scheduleSwipe.offset=0;window.setTimeout(()=>{scheduleSwipe.animating=false;scheduleSwipe.horizontal=false},180)})} function cancelScheduleSwipe(){scheduleSwipe.offset=0;scheduleSwipe.horizontal=false;scheduleSwipe.previewDate=selectedDate.value} function goToday(){const d=weekStartFor(todayKey);weekStart.value=d;selectedDate.value=todayKey;scheduleSwipe.previewDate=todayKey;load()} function handleSwipe(end:number){if(Math.abs(end-swipeStart.value)>45)moveWeek(end<swipeStart.value?1:-1)} function applyWeek(){const [year,week]=weekPicker.value.split('-W').map(Number);if(!year||!week)return;const jan4=new Date(year,0,4);const monday=new Date(jan4);monday.setDate(jan4.getDate()-((jan4.getDay()+6)%7)+(week-1)*7);weekStart.value=monday;selectedDate.value=dateKey(monday);scheduleSwipe.previewDate=selectedDate.value;pickerOpen.value=false;load()} const isOverdue=(item:ScheduleOccurrence)=>item.is_all_day?new Date(`${item.scheduled_date}T23:59:59`)<new Date():!!item.end_time&&new Date(`${item.scheduled_date}T${item.end_time}`)<new Date(); async function complete(item:ScheduleOccurrence,reason?:string){const updated=await api<ScheduleOccurrence>(`/schedules/occurrences/${item.id}/completion`,{method:'PUT',body:{completed:item.status!=='completed',overdue_reason:reason}});items.value=items.value.map(x=>x.id===item.id?updated:x)} async function toggle(item:ScheduleOccurrence){if(item.status==='completed'){await complete(item);return}if(isOverdue(item)){overdueItem.value=item;overdueReason.value='';return}await complete(item)} async function confirmOverdue(){if(!overdueItem.value)return;await complete(overdueItem.value,overdueReason.value||undefined);cancelOverdue()} function cancelOverdue(){overdueItem.value=null;overdueReason.value=''} function editFormState(){return JSON.stringify({...editForm})} const isEditDirty=computed(()=>editFormState()!==editSnapshot.value); const confirmTitle=computed(()=>confirmAction.value==='save'?'确定保存这次修改吗？':confirmAction.value==='delete'?'确定删除此日程吗？':'放弃未保存的修改？'); const confirmMessage=computed(()=>confirmAction.value==='save'?'保存后将更新日程安排。':confirmAction.value==='delete'?(editingItem.value?.recurrence_type==='NONE'?'删除后不可恢复。':'请选择要删除的范围。'):'关闭后本次修改不会保留。'); const confirmPrimaryLabel=computed(()=>confirmAction.value==='save'?'确认保存':confirmAction.value==='delete'?'确认删除':'放弃修改'); function openEdit(item:ScheduleOccurrence){editingItem.value=item;deleteConfirm.value=false;confirmAction.value=null;deleteScope.value='single';editScope.value='single';editError.value='';editForm.title=item.title;editForm.is_all_day=item.is_all_day;editForm.start_time=item.start_time?.slice(0,5)||'09:00';editForm.end_time=item.end_time?.slice(0,5)||'10:00';editForm.recurrence_type=item.recurrence_type;editForm.interval=item.interval||1;editForm.weekdays=item.recurrence_type==='WEEKLY'?[new Date(`${item.scheduled_date}T12:00:00`).getDay()]:[];editForm.month_day=item.recurrence_type==='MONTHLY_DATE'?Number(item.scheduled_date.slice(8,10)):null;editForm.nth_week=item.nth_week||1;editForm.nth_weekday=item.nth_weekday??new Date(`${item.scheduled_date}T12:00:00`).getDay();editForm.recurrence_until=item.recurrence_until||'';editForm.recurrence_count=item.recurrence_count||null;editSnapshot.value=editFormState()} function requestCloseEdit(){if(isEditDirty.value){confirmAction.value='discard';return}closeEdit()} function closeEdit(){editingItem.value=null;deleteConfirm.value=false;confirmAction.value=null;editError.value=''} function requestSave(){confirmAction.value='save'} function requestDelete(){deleteConfirm.value=false;confirmAction.value='delete'} function cancelConfirm(){confirmAction.value=null} function confirmPrimary(){if(confirmAction.value==='save'){void saveEdit()}else if(confirmAction.value==='delete'){void removeSchedule()}else if(confirmAction.value==='discard'){closeEdit()}} async function saveEdit(){if(!editingItem.value)return;editError.value='';try{await api(`/schedules/occurrences/${editingItem.value.id}`,{method:'PUT',body:{...editForm,recurrence_until:editForm.recurrence_type==='NONE'?null:(editForm.recurrence_until||null),start_time:editForm.is_all_day?null:editForm.start_time,end_time:editForm.is_all_day?null:editForm.end_time,scope:editScope.value}});closeEdit();await load()}catch(error:any){editError.value=error?.data?.detail || '保存失败，请检查填写内容'}} async function removeSchedule(){if(!editingItem.value)return;await api(`/schedules/occurrences/${editingItem.value.id}?scope=${deleteScope.value}`,{method:'DELETE'});closeEdit();await load()} async function create(){formError.value='';try{await api('/schedules',{method:'POST',body:form});formOpen.value=false;form.title='';await load()}catch(error:any){formError.value=error?.data?.detail || '保存失败，请检查填写内容'}} watch(selectedDate,v=>form.start_date=v); onMounted(load)
watch(editingItem, item => { if (!item) return; editForm.recurrence_type = item.recurrence_type; editForm.recurrence_until = item.recurrence_until || ''; editForm.customConfigured = item.recurrence_type === 'MONTHLY_NTH_WEEKDAY' || item.interval > 1 || (item.recurrence_type === 'WEEKLY' && item.weekdays.length > 1); editSnapshot.value = editFormState() })
async function completeSchedule(item:ScheduleOccurrence){const updated=await api<ScheduleOccurrence>(`/schedules/occurrences/${item.id}/completion`,{method:'PUT',body:{completed:item.status!=='completed'}});items.value=items.value.map(x=>x.id===item.id?updated:x);overdueItems.value=overdueItems.value.map(x=>x.id===item.id?updated:x);if(detailItem.value?.id===item.id)detailItem.value=updated}
async function toggleSchedule(item:ScheduleOccurrence){await completeSchedule(item)}
function openDetail(item:ScheduleOccurrence){detailItem.value=item;noteDraft.value=item.execution_note || '';noteError.value=''}
function closeDetail(){detailItem.value=null;noteDraft.value='';noteError.value=''}
async function openOverdue(){overdueOpen.value=true;overdueLoading.value=true;overdueError.value='';try{overdueItems.value=await api<ScheduleOccurrence[]>('/schedules/overdue')}catch(error:any){overdueError.value=error?.data?.detail || '加载失败，请重试'}finally{overdueLoading.value=false}}
function closeOverdue(){if(overdueLoading.value)return;overdueOpen.value=false;overdueError.value=''}
function openOverdueEdit(item:ScheduleOccurrence){closeOverdue();openEdit(item)}
async function saveNote(){if(!detailItem.value)return;noteSaving.value=true;noteError.value='';try{const updated=await api<ScheduleOccurrence>(`/schedules/occurrences/${detailItem.value.id}/note`,{method:'PUT',body:{execution_note:noteDraft.value}});items.value=items.value.map(x=>x.id===updated.id?updated:x);listItems.value=listItems.value.map(x=>x.id===updated.id?updated:x);closeDetail()}catch(error:any){noteError.value=error?.data?.detail || '保存失败，请重试'}finally{noteSaving.value=false}}
function printDays(week:{key:string}){return daysForWeek(new Date(`${week.key}T12:00:00`))}
function printAllDayItems(day:string){return printItems.value.filter(item=>item.scheduled_date===day&&item.is_all_day)}
function printTimeRows(week:{key:string}):PrintTimeRow[]{const days=printDays(week).map(day=>day.key);const timed=printItems.value.filter(item=>days.includes(item.scheduled_date)&&!item.is_all_day&&item.start_time&&item.end_time);if(!timed.length)return [];const boundaries=new Set<number>();timed.forEach(item=>{boundaries.add(timeToMinute(item.start_time));boundaries.add(timeToMinute(item.end_time))});const points=[...boundaries].sort((a,b)=>a-b);return points.flatMap((point,index)=>{const starting=timed.filter(item=>timeToMinute(item.start_time)===point);const rows:PrintTimeRow[]=[];if(starting.length){const grouped=Object.fromEntries(days.map(day=>[day,starting.filter(item=>item.scheduled_date===day)]));rows.push({type:'tasks',key:`tasks-${point}`,startLabel:minuteLabel(point),items:grouped})}const next=points[index+1];if(next&&!starting.length)rows.push({type:'empty',key:`empty-${point}-${next}`,startLabel:minuteLabel(point),endLabel:minuteLabel(next)});return rows})}
function fitPrintWeeksToPage(){const pageHeight=180*96/25.4;const maxRowHeight=36*96/25.4;const root=document.querySelector<HTMLElement>('.schedule-print-root');if(!root)return;root.querySelectorAll<HTMLElement>('.schedule-print-week').forEach(week=>{const body=week.querySelector<HTMLElement>('.schedule-print-body');const header=week.querySelector<HTMLElement>('.schedule-print-date-header');week.style.transform='none';week.style.width='100%';week.style.height=`${pageHeight}px`;if(body){body.style.flex='0 0 auto';const availableHeight=Math.max(0,week.clientHeight-(header?.offsetHeight||0));body.style.height=`${availableHeight}px`;const rowCount=Math.max(1,Math.ceil(body.children.length/8));const idealRowHeight=availableHeight/rowCount;body.style.gridAutoRows=idealRowHeight<=maxRowHeight?'1fr':`${maxRowHeight}px`}})}
function clearPrintLayout(){const root=document.querySelector<HTMLElement>('.schedule-print-root');if(!root)return;root.style.display='';root.querySelectorAll<HTMLElement>('.schedule-print-week').forEach(week=>{week.style.transform='';week.style.width='';week.style.height='';const body=week.querySelector<HTMLElement>('.schedule-print-body');if(body){body.style.removeProperty('grid-auto-rows');body.style.removeProperty('height');body.style.removeProperty('flex')}})}
function openPrint(){printError.value='';printItems.value=[];const current=dateKey(weekStart.value);selectedPrintWeeks.value=printWeeks.value.some(week=>week.key===current)?[current]:[];printOpen.value=true}
function closePrint(){if(printLoading.value)return;printOpen.value=false;printError.value=''}
function selectAllPrintWeeks(){selectedPrintWeeks.value=printWeeks.value.map(week=>week.key)}
function clearPrintWeeks(){selectedPrintWeeks.value=[]}
async function preparePrint(){if(!selectedPrintWeeks.value.length){printError.value='请至少选择一周';return}printLoading.value=true;printError.value='';let beforePrint: (()=>void)|null=null;try{const selected=selectedPrintWeekObjects.value;const start=selected[0].start;const end=selected[selected.length-1].end;printItems.value=await api<ScheduleOccurrence[]>(`/schedules?start_date=${start}&end_date=${end}`);printOpen.value=false;document.body.classList.add('printing-schedule');await nextTick();fitPrintWeeksToPage();beforePrint=()=>fitPrintWeeksToPage();window.addEventListener('beforeprint',beforePrint);const finish=()=>{if(beforePrint)window.removeEventListener('beforeprint',beforePrint);document.body.classList.remove('printing-schedule');clearPrintLayout();window.setTimeout(()=>{printItems.value=[]},0)};window.addEventListener('afterprint',finish,{once:true});window.print()}catch(error:any){if(beforePrint)window.removeEventListener('beforeprint',beforePrint);document.body.classList.remove('printing-schedule');clearPrintLayout();printError.value=error?.data?.detail || '准备打印失败，请重试'}finally{printLoading.value=false}}
async function createWithDeadline(){formError.value='';try{await api('/schedules',{method:'POST',body:{...form,recurrence_until:form.recurrence_type==='NONE'?null:(form.recurrence_until||null),recurrence_count:form.recurrence_count||null}});formOpen.value=false;form.title='';form.recurrence_type='NONE';form.interval=1;form.weekdays=[];form.month_day=null;form.recurrence_until='';form.recurrence_count=null;form.customConfigured=false;await load()}catch(error:any){formError.value=error?.data?.detail || '保存失败，请检查填写内容'}}
async function endScheduleSwipeSmooth(){if(!scheduleSwipe.horizontal){cancelScheduleSwipe();return}const width=window.innerWidth;const direction=Math.abs(scheduleSwipe.offset)>=width/2?(scheduleSwipe.offset<0?1:-1):0;if(!direction){scheduleSwipe.animating=true;scheduleSwipe.offset=0;scheduleSwipe.previewDate=selectedDate.value;window.setTimeout(()=>{scheduleSwipe.animating=false;scheduleSwipe.horizontal=false},180);return}scheduleSwipe.animating=true;scheduleSwipe.offset=-direction*width;await new Promise(resolve=>window.setTimeout(resolve,180));const next=dateWithOffset(selectedDate.value,direction);const nextWeekStart=weekStartFor(next);const shouldLoad=dateKey(nextWeekStart)!==dateKey(weekStart.value);selectedDate.value=next;weekStart.value=nextWeekStart;scheduleSwipe.previewDate=next;scheduleSwipe.offset=0;scheduleSwipe.horizontal=false;scheduleSwipe.animating=false;if(shouldLoad)void load()}
function waitForSwipeTransition(){return new Promise<void>(resolve=>{const track=swipeTrack.value;if(!track){resolve();return}let settled=false;const finish=()=>{if(settled)return;settled=true;track.removeEventListener('transitionend',finish);resolve()};track.addEventListener('transitionend',finish);window.setTimeout(finish,260)})}
function startScheduleSwipeV2(event:TouchEvent){if(scheduleSwipe.animating)return;const touch=event.touches[0];scheduleSwipe.startX=touch.clientX;scheduleSwipe.startY=touch.clientY;scheduleSwipe.offset=0;scheduleSwipe.horizontal=false;gestureAxis.value='none';scheduleSwipe.previewDate=selectedDate.value}
function moveScheduleSwipeV2(event:TouchEvent){if(scheduleSwipe.animating)return;const touch=event.touches[0];const dx=touch.clientX-scheduleSwipe.startX;const dy=touch.clientY-scheduleSwipe.startY;if(gestureAxis.value==='none'){if(Math.max(Math.abs(dx),Math.abs(dy))<12)return;gestureAxis.value=Math.abs(dx)>Math.abs(dy)?'horizontal':'vertical';scheduleSwipe.horizontal=gestureAxis.value==='horizontal'}if(gestureAxis.value==='vertical'){scheduleSwipe.offset=0;scheduleSwipe.previewDate=selectedDate.value;return}if(event.cancelable)event.preventDefault();scheduleSwipe.offset=dx;updateSwipePreview()}
function cancelScheduleSwipeV2(){scheduleSwipe.offset=0;scheduleSwipe.horizontal=false;gestureAxis.value='none';scheduleSwipe.previewDate=selectedDate.value}
async function endScheduleSwipeSmoothV2(){if(gestureAxis.value!=='horizontal'){cancelScheduleSwipeV2();return}const width=window.innerWidth;const direction=Math.abs(scheduleSwipe.offset)>=width/2?(scheduleSwipe.offset<0?1:-1):0;if(!direction){scheduleSwipe.animating=true;scheduleSwipe.offset=0;await new Promise(resolve=>requestAnimationFrame(resolve));scheduleSwipe.animating=false;scheduleSwipe.horizontal=false;gestureAxis.value='none';return}scheduleSwipe.animating=true;scheduleSwipe.offset=-direction*width;await new Promise(resolve=>requestAnimationFrame(resolve));await waitForSwipeTransition();const next=dateWithOffset(selectedDate.value,direction);const nextWeekStart=weekStartFor(next);const shouldLoad=dateKey(nextWeekStart)!==dateKey(weekStart.value);selectedDate.value=next;weekStart.value=nextWeekStart;scheduleSwipe.previewDate=next;await nextTick();scheduleSwipe.offset=0;scheduleSwipe.animating=false;scheduleSwipe.horizontal=false;gestureAxis.value='none';if(shouldLoad)void load()}
</script>
