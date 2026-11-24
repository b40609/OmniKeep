<script setup lang="ts">
import { ref, watch, computed, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { ArrowLeft, X, Maximize2, Minimize2, PanelLeft, PanelRight } from 'lucide-vue-next'
import ItemActions from '@/components/items/ItemActions.vue'
import Select from '@/components/ui/select/Select.vue'
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
    if (request === detailRequest && ui.activeItem?.id === id) {
      ui.activeItem = full
      // J/K or next/previous onto an item with no article text: show its analysis, not an empty reader tab
      if (ui.detailTab === 'reader' && !full.content_raw) ui.detailTab = 'analysis'
    }
  } catch {
    if (request === detailRequest && ui.activeItem?.id === id) detailError.value = '完整內容載入失敗，目前顯示已儲存的摘要。'
  } finally {
    if (request === detailRequest) fetchingFull.value = false
  }
}
// opening an item (not switching from one open item to the next) follows the chosen way to open
watch(() => ui.activeItem?.id != null, (open) => { if (open) ui.focusMode = ui.readerOpen === 'full' }, { immediate: true })
// the expand button is also the choice: what you pick is how the next item opens
function toggleFull() {
  ui.focusMode = !ui.focusMode
  ui.readerOpen = ui.focusMode ? 'full' : 'side'
}
watch(() => ui.activeItem?.id, (id) => {
  if (id == null) {
    detailRequest++
    fetchingFull.value = false
    detailError.value = ''
  } else void loadFull(id)
}, { immediate: true })

// on a desktop the tabs and the category join the top bar whenever it is wide enough (full page or a wide
// side panel), so the article starts right under one bar; a narrow pane keeps them on one second row
const lgQuery = typeof window !== 'undefined' && window.matchMedia ? window.matchMedia('(min-width: 1024px)') : null
const isLg = ref(!!lgQuery?.matches)
const onLg = () => { isLg.value = !!lgQuery?.matches }
lgQuery?.addEventListener?.('change', onLg)
const rootRef = ref<HTMLElement | null>(null)
const paneW = ref(0)
let ro: ResizeObserver | null = null
watch(rootRef, (el) => {
  ro?.disconnect(); ro = null
  if (!el) return
  paneW.value = el.getBoundingClientRect().width // the first frame already knows, so the bar does not jump
  if (typeof ResizeObserver === 'undefined') return
  ro = new ResizeObserver(([e]) => { paneW.value = e.contentRect.width })
  ro.observe(el)
})
let inHistory = false
function onPopState() {
  if (!inHistory) return
  inHistory = false
  closeReader()
}
onMounted(() => {
  if (typeof window !== 'undefined' && !isLg.value && typeof window.history?.pushState === 'function') {
    window.history.pushState({ ...(window.history.state || {}), omnikeepReader: true }, '')
    inHistory = true
    window.addEventListener?.('popstate', onPopState)
  }
})
onBeforeUnmount(() => {
  ro?.disconnect()
  lgQuery?.removeEventListener?.('change', onLg)
  if (typeof window !== 'undefined') {
    window.removeEventListener?.('popstate', onPopState)
    if (inHistory && window.history?.state?.omnikeepReader) {
      inHistory = false
      window.history.back()
    }
  }
})
const merged = computed(() => isLg.value && paneW.value >= 840)
const TABS = [{ id: 'analysis', label: '重點分析' }, { id: 'reader', label: '原文' }] as const
const categoryOptions = computed(() => [
  ...itemsStore.categories.filter((c) => c.name !== 'Inbox').map((c) => ({ value: c.name, label: c.name })),
  { value: 'Inbox', label: '收件匣' },
])

// another item, or the other tab: start at the top, not where the last one was left
watch(() => [ui.activeItem?.id, ui.detailTab], () => {
  void nextTick(() => { const s = rootRef.value?.querySelector?.<HTMLElement>('[data-reader-scroll]'); if (s) s.scrollTop = 0 })
})

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
  <section v-if="ui.activeItem" ref="rootRef" data-reader-root
    class="safe-top safe-bottom fixed inset-0 z-40 flex min-w-0 flex-col bg-shell lg:flex-1 lg:border-hairline"
    :class="[ui.focusMode ? 'lg:inset-0 lg:z-50 lg:fixed' : 'lg:static lg:z-auto', ui.readerSide === 'left' ? 'lg:-order-1 lg:border-r' : 'lg:border-l']" aria-label="閱讀面板">
    <div class="relative flex min-h-14 shrink-0 items-center justify-between gap-1 border-b border-hairline px-2 sm:px-4">
      <button class="item-action" :class="ui.focusMode ? '' : 'lg:hidden'" aria-label="返回清單" title="返回清單（Esc）" @click="closeReader"><ArrowLeft class="size-5" /></button>
      <span class="min-w-0 truncate text-sm text-muted-foreground" :class="merged && !ui.focusMode ? 'mr-3 shrink' : 'flex-1'">{{ sourceName(ui.activeItem) }}</span>
      <div v-if="merged" class="flex items-center gap-0.5 rounded-xl bg-muted/60 p-1" :class="ui.focusMode ? '2xl:absolute 2xl:left-1/2 2xl:-translate-x-1/2' : 'mr-auto'" role="tablist" aria-label="閱讀模式" @keydown="changeTab">
        <button v-for="t in TABS" :id="'tab-' + t.id" :key="t.id"
          role="tab" :aria-selected="ui.detailTab === t.id" :aria-controls="'panel-' + t.id" :tabindex="ui.detailTab === t.id ? 0 : -1"
          class="min-h-9 rounded-lg px-4 text-sm font-medium transition-colors" :class="ui.detailTab === t.id ? 'bg-card text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'"
          @click="ui.detailTab = t.id">{{ t.label }}</button>
      </div>
      <template v-if="merged">
        <div v-if="ui.detailTab === 'reader'" class="flex items-center text-xs text-muted-foreground" role="group" aria-label="原文字級">
          <button class="item-action" :disabled="ui.readerFontSize <= 13" aria-label="縮小字級" @click="ui.readerFontSize = Math.max(13, ui.readerFontSize - 1)">A−</button>
          <span class="w-5 text-center tabular-nums">{{ ui.readerFontSize }}</span>
          <button class="item-action" :disabled="ui.readerFontSize >= 20" aria-label="放大字級" @click="ui.readerFontSize = Math.min(20, ui.readerFontSize + 1)">A+</button>
        </div>
        <div class="mr-1 flex items-center gap-2 text-xs text-muted-foreground">
          <span>分類</span>
          <Select
            :model-value="ui.activeItem.category_name || 'Inbox'"
            :options="categoryOptions"
            aria-label="分類"
            small
            @update:model-value="updateCategory(ui.activeItem!, $event)"
          />
        </div>
        <span class="mr-2 text-xs text-muted-foreground">{{ ui.activeItem.is_read ? '已封存' : '未封存' }}</span>
        <template v-if="ui.sidesFit">
        <span class="mx-1 h-5 w-px bg-hairline" aria-hidden="true" />
        <button class="item-action" :aria-pressed="ui.outlineOpen" :aria-label="ui.outlineOpen ? '收起左邊目錄' : '打開左邊目錄'" :title="(ui.outlineOpen ? '收起目錄' : '打開目錄') + '（[）'" @click="ui.outlineOpen = !ui.outlineOpen">
          <PanelLeft class="size-4" :class="ui.outlineOpen ? 'text-foreground' : 'text-subtle-foreground'" />
        </button>
        <button v-if="ui.railFits" class="item-action" :aria-pressed="ui.railOpen" :aria-label="ui.railOpen ? '收起右邊資訊欄' : '打開右邊資訊欄'" :title="(ui.railOpen ? '收起資訊欄' : '打開資訊欄') + '（]）'" @click="ui.railOpen = !ui.railOpen">
          <PanelRight class="size-4" :class="ui.railOpen ? 'text-foreground' : 'text-subtle-foreground'" />
        </button>
        </template>
        <span class="mx-1 h-5 w-px bg-hairline" aria-hidden="true" />
      </template>
      <ItemActions :item="ui.activeItem" allow-delete />
      <button class="item-action hidden lg:flex" :aria-label="ui.focusMode ? '改成側邊預覽（之後都這樣開）' : '改成整頁閱讀（之後都這樣開）'" :title="ui.focusMode ? '改成側邊預覽，之後點開也這樣' : '改成整頁閱讀，之後點開也這樣'" :aria-pressed="ui.focusMode" @click="toggleFull">
        <Minimize2 v-if="ui.focusMode" class="size-4" /><Maximize2 v-else class="size-4" />
      </button>
      <button class="item-action hidden lg:flex" aria-label="關閉閱讀面板" title="關閉（Esc）" @click="closeReader"><X class="size-4" /></button>
    </div>
    <div v-if="!merged" class="flex h-12 shrink-0 items-center justify-between gap-2 border-b border-hairline px-3 sm:px-4">
      <div class="flex shrink-0 items-center gap-1" role="tablist" aria-label="閱讀模式" @keydown="changeTab">
        <button v-for="t in TABS" :id="'tab-' + t.id" :key="t.id"
          role="tab" :aria-selected="ui.detailTab === t.id" :aria-controls="'panel-' + t.id" :tabindex="ui.detailTab === t.id ? 0 : -1"
          class="min-h-10 rounded-lg px-3 text-sm font-medium transition-colors" :class="ui.detailTab === t.id ? 'bg-surface-2 text-foreground font-semibold' : 'text-muted-foreground hover:bg-surface-1'"
          @click="ui.detailTab = t.id">{{ t.label }}</button>
      </div>
      <div v-if="ui.detailTab === 'reader'" class="flex shrink-0 items-center text-xs text-muted-foreground" role="group" aria-label="原文字級">
        <button class="item-action" :disabled="ui.readerFontSize <= 13" aria-label="縮小字級" @click="ui.readerFontSize = Math.max(13, ui.readerFontSize - 1)">A−</button>
        <span class="w-6 text-center tabular-nums">{{ ui.readerFontSize }}</span>
        <button class="item-action" :disabled="ui.readerFontSize >= 20" aria-label="放大字級" @click="ui.readerFontSize = Math.min(20, ui.readerFontSize + 1)">A+</button>
      </div>
      <div v-else class="min-w-0 max-w-[10rem] shrink">
        <Select
          :model-value="ui.activeItem.category_name || 'Inbox'"
          :options="categoryOptions"
          aria-label="分類"
          small
          @update:model-value="updateCategory(ui.activeItem!, $event)"
        />
      </div>
    </div>
    <div v-if="detailError" class="flex flex-wrap items-center gap-2 border-b border-hairline px-4 py-2 text-sm" role="alert">
      <span>{{ detailError }}</span><button class="min-h-11 px-2 font-medium underline underline-offset-4" @click="loadFull(ui.activeItem.id)">重試</button>
    </div>
    <div :id="'panel-' + ui.detailTab" data-reader-scroll role="tabpanel" :aria-labelledby="'tab-' + ui.detailTab" tabindex="0" :aria-busy="fetchingFull" class="mobile-scroll relative min-h-0 flex-1 overflow-x-hidden overflow-y-auto">
      <ReadingProgress />
      <div v-if="fetchingFull && !ui.activeItem.citations && !ui.activeItem.deep_analysis" class="mx-auto max-w-3xl space-y-4 p-6 lg:p-8" aria-label="正在載入完整內容">
        <Skeleton class="h-7 w-3/4" /><Skeleton class="h-4 w-1/2" />
        <div class="space-y-2 pt-6"><Skeleton v-for="i in 4" :key="i" class="h-4 w-full" /></div>
      </div>
      <AnalysisTab v-else-if="ui.detailTab === 'analysis'" /><ReaderTab v-else />
    </div>
  </section>
</template>
