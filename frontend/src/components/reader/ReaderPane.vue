<script setup lang="ts">
import { ref, watch } from 'vue'
import { ArrowLeft, X, Maximize2, Minimize2 } from 'lucide-vue-next'
import ItemActions from '@/components/items/ItemActions.vue'
import Skeleton from '@/components/ui/skeleton/Skeleton.vue'
import AnalysisTab from './AnalysisTab.vue'
import ReaderTab from './ReaderTab.vue'
import ReadingProgress from './ReadingProgress.vue'
import * as api from '@/lib/api'
import { sourceName } from '@/lib/wall'
import { useUiStore } from '@/stores/ui'
import { useItemsStore } from '@/stores/items'
import { useMutations } from '@/composables/useMutations'

const ui = useUiStore()
const itemsStore = useItemsStore()
const { updateCategory } = useMutations()
const fetchingFull = ref(false)
const detailError = ref('')
let detailRequest = 0

function closeReader() {
  ui.activeItem = null
  ui.focusMode = false
}
async function loadFull(id: number) {
  const request = ++detailRequest
  fetchingFull.value = true
  detailError.value = ''
  try {
    const full = await api.getItem(id)
    if (request === detailRequest && ui.activeItem?.id === id) ui.activeItem = full
  } catch {
    if (request === detailRequest && ui.activeItem?.id === id) detailError.value = '完整內容載入失敗，目前顯示已儲存的摘要。'
  } finally {
    if (request === detailRequest) fetchingFull.value = false
  }
}
watch(() => ui.activeItem?.id, (id) => {
  if (id == null) {
    detailRequest++
    fetchingFull.value = false
    detailError.value = ''
  } else void loadFull(id)
}, { immediate: true })

function changeTab(event: KeyboardEvent) {
  const tabs = Array.from((event.currentTarget as HTMLElement).querySelectorAll<HTMLButtonElement>('[role="tab"]'))
  const index = tabs.indexOf(event.target as HTMLButtonElement)
  if (index < 0) return
  let next = index
  if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') next = 1 - index
  else if (event.key === 'Home') next = 0
  else if (event.key === 'End') next = 1
  else return
  event.preventDefault()
  event.stopPropagation()
  tabs[next]?.click()
  tabs[next]?.focus()
}
</script>

<template>
  <section v-if="ui.activeItem" data-reader-root
    class="safe-top safe-bottom fixed inset-0 z-40 flex min-w-0 flex-col bg-shell lg:flex-1 lg:border-l lg:border-hairline"
    :class="ui.focusMode ? 'lg:inset-0 lg:z-30 lg:fixed' : 'lg:static lg:z-auto'" aria-label="閱讀面板">
    <div class="flex min-h-14 shrink-0 items-center justify-between gap-1 border-b border-hairline px-2 sm:px-4">
      <button class="item-action lg:hidden" aria-label="返回清單" @click="closeReader"><ArrowLeft class="size-5" /></button>
      <span class="min-w-0 flex-1 truncate text-sm text-muted-foreground">{{ sourceName(ui.activeItem) }}</span>
      <ItemActions :item="ui.activeItem" allow-delete />
      <button class="item-action hidden lg:flex" :aria-label="ui.focusMode ? '結束全寬閱讀' : '全寬閱讀'" :aria-pressed="ui.focusMode" @click="ui.focusMode = !ui.focusMode">
        <Minimize2 v-if="ui.focusMode" class="size-4" /><Maximize2 v-else class="size-4" />
      </button>
      <button class="item-action hidden lg:flex" aria-label="關閉閱讀面板" title="關閉（Esc）" @click="closeReader"><X class="size-4" /></button>
    </div>
    <div class="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b border-hairline px-3 py-2 sm:px-4">
      <label class="flex min-w-0 items-center gap-2 text-xs text-muted-foreground">
        分類
        <select :value="ui.activeItem.category_name" class="min-h-11 w-36 max-w-full rounded-lg border border-border bg-card px-2 text-sm text-foreground" @change="updateCategory(ui.activeItem!, ($event.target as HTMLSelectElement).value)">
          <option v-for="c in itemsStore.categories.filter(c => c.name !== 'Inbox')" :key="c.id" :value="c.name">{{ c.name }}</option>
          <option value="Inbox">收件匣</option>
        </select>
      </label>
      <span class="text-xs text-muted-foreground">{{ ui.activeItem.is_read ? '已封存' : '未封存' }}</span>
    </div>
    <div class="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b border-hairline px-3 py-1 sm:px-4">
      <div class="flex items-center gap-1" role="tablist" aria-label="閱讀模式" @keydown="changeTab">
        <button v-for="t in [{ id: 'analysis', label: '重點分析' }, { id: 'reader', label: '原文' }]" :id="'tab-' + t.id" :key="t.id"
          role="tab" :aria-selected="ui.detailTab === t.id" :aria-controls="'panel-' + t.id" :tabindex="ui.detailTab === t.id ? 0 : -1"
          class="min-h-11 rounded-lg px-3 text-sm font-medium" :class="ui.detailTab === t.id ? 'bg-primary-soft text-primary-soft-foreground' : 'text-muted-foreground hover:bg-accent'"
          @click="ui.detailTab = t.id as 'analysis' | 'reader'">{{ t.label }}</button>
      </div>
      <div v-if="ui.detailTab === 'reader'" class="flex items-center text-xs text-muted-foreground" role="group" aria-label="原文字級">
        <button class="item-action" :disabled="ui.readerFontSize <= 13" aria-label="縮小字級" @click="ui.readerFontSize = Math.max(13, ui.readerFontSize - 1)">A−</button>
        <span class="w-5 text-center tabular-nums">{{ ui.readerFontSize }}</span>
        <button class="item-action" :disabled="ui.readerFontSize >= 20" aria-label="放大字級" @click="ui.readerFontSize = Math.min(20, ui.readerFontSize + 1)">A+</button>
      </div>
    </div>
    <div v-if="detailError" class="flex flex-wrap items-center gap-2 border-b border-hairline px-4 py-2 text-sm" role="alert">
      <span>{{ detailError }}</span><button class="min-h-11 px-2 font-medium underline underline-offset-4" @click="loadFull(ui.activeItem.id)">重試</button>
    </div>
    <div :id="'panel-' + ui.detailTab" data-reader-scroll role="tabpanel" :aria-labelledby="'tab-' + ui.detailTab" tabindex="0" :aria-busy="fetchingFull" class="relative min-h-0 flex-1 overflow-y-auto">
      <ReadingProgress />
      <div v-if="fetchingFull && !ui.activeItem.citations && !ui.activeItem.deep_analysis" class="mx-auto max-w-3xl space-y-4 p-6 lg:p-8" aria-label="正在載入完整內容">
        <Skeleton class="h-7 w-3/4" /><Skeleton class="h-4 w-1/2" />
        <div class="space-y-2 pt-6"><Skeleton v-for="i in 4" :key="i" class="h-4 w-full" /></div>
      </div>
      <AnalysisTab v-else-if="ui.detailTab === 'analysis'" /><ReaderTab v-else />
    </div>
  </section>
</template>
