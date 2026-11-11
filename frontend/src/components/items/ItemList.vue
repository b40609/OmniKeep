<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { VList } from 'virtua/vue'
import { Inbox, Sparkles, FolderInput, Bookmark, Copy, Check, ChevronDown, LayoutGrid, List, Loader2, ListChecks, SlidersHorizontal } from 'lucide-vue-next'
import {
  DropdownMenuRoot, DropdownMenuTrigger, DropdownMenuPortal, DropdownMenuContent,
  DropdownMenuRadioGroup, DropdownMenuRadioItem, DropdownMenuItemIndicator,
} from 'reka-ui'
import * as api from '@/lib/api'
import type { Item } from '@/lib/api'
import { toast } from 'vue-sonner'
import ItemRow from './ItemRow.vue'
import ItemCards from './ItemCards.vue'
import SwipeableRow from './SwipeableRow.vue'
import Skeleton from '@/components/ui/skeleton/Skeleton.vue'
import { KIND_LABELS, KIND_TABS, groupByDay, type WallSection } from '@/lib/wall'
import { useItemsStore, type SortOrder } from '@/stores/items'
import { useUiStore } from '@/stores/ui'
import { useRadarStore } from '@/stores/radar'

const items = useItemsStore()
const ui = useUiStore()
const radar = useRadarStore()

function openRadarSettings() {
  ui.showRadarModal = true
  void radar.ensureLoaded()
}

const vlist = ref<InstanceType<typeof VList> | null>(null)
const wall = ref<HTMLElement | null>(null)

const firstLoad = ref(true)
watch(
  () => items.loading,
  (loading, was) => {
    if (was && !loading) firstLoad.value = false
  },
)

const activeId = computed(() => ui.activeItem?.id ?? -1)
const firstUse = computed(() => !items.error && !items.searchQuery.trim() && items.currentCategory === '全部' && items.stats.total === 0 && ['inbox', 'all'].includes(items.triageView))
const emptyState = computed(() => {
  if (items.error) return { title: '無法載入收藏', body: items.error, action: '重新載入' }
  if (items.searchQuery.trim()) return { title: '找不到符合的收藏', body: '換個關鍵字，或清除搜尋條件。', action: '清除搜尋條件' }
  if (items.currentCategory !== '全部') return { title: '這個分類沒有項目', body: '可以改看所有分類的收藏。', action: '顯示所有分類' }
  if (firstUse.value) return { title: '還沒有任何收藏', body: '按上方的「新增」貼上連結，或寫一則筆記。', action: '新增筆記' }
  if (items.triageView === 'inbox') return { title: '收件匣已清空', body: '封存的項目可以在「封存」或「全部」找到。', action: '查看全部' }
  if (items.triageView === 'starred') return { title: '還沒有加星的項目', body: '在項目上按星號，就會出現在這裡。', action: '查看全部' }
  if (items.triageView === 'archived') return { title: '還沒有封存的項目', body: '在項目上按封存，就會收到這裡。', action: '查看全部' }
  return { title: '目前沒有收藏', body: '貼上連結或新增筆記，開始收錄。', action: '新增筆記' }
})
function recoverEmpty() {
  if (items.error) return void items.loadItems()
  if (firstUse.value || (!items.searchQuery.trim() && items.triageView === 'all' && items.currentCategory === '全部')) {
    ui.showNoteModal = true
    return
  }
  if (items.searchQuery.trim()) items.searchQuery = ''
  else if (items.currentCategory === '全部') items.triageView = 'all'
  items.currentCategory = '全部'
  void items.loadItems()
}

/**
 * Date sections ("今天", "昨天", ...) for both views, over everything loaded so far:
 * a day that spans two pages is still one section. Search results are ranked by
 * relevance, not by date, so they stay one untitled section.
 */
const sections = computed<WallSection<Item>[]>(() =>
  items.ranked ? [{ key: 'ranked', label: '', items: items.visibleItems }] : groupByDay(items.visibleItems),
)

/** A section's count, once it is final: the last one may still grow while more pages are to come. */
function sectionCount(section: WallSection<Item>): number | null {
  return items.hasMore && section === sections.value[sections.value.length - 1] ? null : section.items.length
}

type ListRow =
  | { type: 'heading'; key: string; label: string; count: number | null }
  | { type: 'item'; key: string; item: Item }
  | { type: 'end'; key: string }

/** The virtual list takes one flat array, so headings and the end-of-list status are rows of their own. */
const rows = computed<ListRow[]>(() => [
  ...sections.value.flatMap((section): ListRow[] => [
    ...(section.label ? [{ type: 'heading' as const, key: 'h-' + section.key, label: section.label, count: sectionCount(section) }] : []),
    ...section.items.map((item) => ({ type: 'item' as const, key: 'i-' + item.id, item })),
  ]),
  { type: 'end', key: 'end' },
])

/** A kind tab that matches nothing in this view. */
const kindEmpty = computed(() => !items.loading && !items.error && items.kindFilter !== 'all' && items.visibleItems.length === 0)
const kindLabel = computed(() => (items.kindFilter === 'all' ? '' : KIND_LABELS[items.kindFilter]))
/** Everything the view holds, not just what is loaded; a semantic search only knows what it returned. */
const totalCount = computed(() => items.total ?? items.visibleItems.length)

const SORT_LABELS: Record<SortOrder, string> = { newest: '最新收錄', oldest: '最早收錄' }
// A search comes back ranked by relevance and is shown in that order.
const sortLabel = computed(() => (items.ranked ? '最相關' : SORT_LABELS[items.sortOrder]))

/* Scrolling near the end asks for the next page. */
const LOAD_AHEAD = 1200
function nearEnd(): boolean {
  if (items.viewMode === 'list') {
    const list = vlist.value
    return !!list && list.scrollSize - list.scrollOffset - list.viewportSize < LOAD_AHEAD
  }
  const el = wall.value
  return !!el && el.scrollHeight - el.scrollTop - el.clientHeight < LOAD_AHEAD
}
function loadMoreIfNearEnd() {
  // After a failure the next page waits for the retry button instead of looping.
  if (items.hasMore && !items.loadingMore && !items.moreError && nearEnd()) void items.loadMore()
}
// A page that does not fill the screen (tall window, short page) leads straight to the next one.
watch(
  () => [items.items.length, items.viewMode, items.loading] as const,
  () => void nextTick(loadMoreIfNearEnd),
)

/** Scroll a row into view by its position in the virtual list. */
function scrollToIndex(index: number) {
  vlist.value?.scrollToIndex(index)
}

/** Bring an item into view in whichever view is showing — used by J/K keyboard navigation. */
function scrollToItem(id: number) {
  if (items.viewMode === 'list') {
    const index = rows.value.findIndex((row) => row.type === 'item' && row.item.id === id)
    if (index >= 0) vlist.value?.scrollToIndex(index, { align: 'nearest' })
  } else {
    wall.value?.querySelector(`[data-item-id="${id}"]`)?.scrollIntoView({ block: 'nearest' })
  }
}

const bookmarkletHref = computed(() => {
  const origin = typeof window !== 'undefined' ? window.location.origin : 'http://localhost:5000'
  return `javascript:(function(){const u=encodeURIComponent(window.location.href);const t=encodeURIComponent(document.querySelector('title')?.textContent||document.querySelector("meta[property='og:title']")?.getAttribute('content')||'');const d=encodeURIComponent(document.querySelector("meta[name='description']")?.getAttribute('content')||document.querySelector("meta[property='og:description']")?.getAttribute('content')||'');window.open('${origin}/?url='+u+'&title='+t+'&description='+d+'&auto_close=1','_blank','width=520,height=620');})();`
})

const copied = ref(false)
async function copyBookmarklet() {
  try {
    await navigator.clipboard.writeText(bookmarkletHref.value)
    copied.value = true
    toast.success('已複製書籤小工具的程式碼')
    setTimeout(() => (copied.value = false), 2000)
  } catch {
    toast.error('無法複製，請允許剪貼簿存取後重試。')
  }
}

const isSeeding = ref(false)
async function handleSeedDemos() {
  isSeeding.value = true
  const t = toast.loading('正在載入範例資料…')
  try {
    await api.seedDemoItems()
    toast.success('已載入範例資料', {
      id: t,
      description: '示範 YouTube、Bilibili 與開源專案的呈現方式；內容是範例，沒有經過即時分析。',
    })
    await items.refreshAll()
  } catch (e) {
    toast.error('範例資料載入失敗：' + (e as Error).message, { id: t })
  } finally {
    isSeeding.value = false
  }
}

defineExpose({ scrollToIndex, scrollToItem })
</script>

<template>
  <div class="@container flex min-h-0 flex-1 flex-col bg-shell" :aria-busy="items.loading">
    <!-- Filter row: kind tabs on the left; how many, the order and the view on the right -->
    <div class="wall-bar" :class="{ 'wall-column': items.viewMode === 'list' }">
      <div class="no-scrollbar -my-1 flex min-w-0 gap-3 overflow-x-auto py-1" role="group" aria-label="類型">
        <button
          v-for="tab in KIND_TABS"
          :key="tab.id"
          type="button"
          class="kind-chip"
          :aria-pressed="items.kindFilter === tab.id"
          @click="items.kindFilter = tab.id"
        >{{ tab.label }}</button>
      </div>
      <p class="ml-auto min-w-0 shrink truncate text-sm tabular-nums text-muted-foreground max-sm:hidden" aria-live="polite">
        <template v-if="items.loading">載入中…</template>
        <template v-else>
          <span v-if="items.searchQuery.trim()">搜尋「{{ items.searchQuery.trim() }}」　</span>
          <!-- A server that reports no total only lets us say how far we have got -->
          <template v-if="items.total == null && items.hasMore">已載入 {{ totalCount }} 則</template>
          <template v-else>{{ totalCount }} 則</template>
        </template>
      </p>
      <DropdownMenuRoot>
        <DropdownMenuTrigger class="top-button max-sm:ml-auto" :disabled="items.ranked" :title="items.ranked ? '搜尋結果依相關性排列' : '排序'" aria-label="排序">
          <strong>{{ sortLabel }}</strong><ChevronDown v-if="!items.ranked" />
        </DropdownMenuTrigger>
        <DropdownMenuPortal>
          <DropdownMenuContent class="app-menu !min-w-40" align="end" :side-offset="8" :collision-padding="12">
            <DropdownMenuRadioGroup :model-value="items.sortOrder" @update:model-value="items.sortOrder = $event as SortOrder">
              <DropdownMenuRadioItem v-for="(label, order) in SORT_LABELS" :key="order" :value="order" class="app-menu__item">
                {{ label }}
                <span class="app-menu__end"><DropdownMenuItemIndicator><Check aria-hidden="true" /></DropdownMenuItemIndicator></span>
              </DropdownMenuRadioItem>
            </DropdownMenuRadioGroup>
          </DropdownMenuContent>
        </DropdownMenuPortal>
      </DropdownMenuRoot>
      <div class="view-switch" role="group" aria-label="檢視方式">
        <button type="button" aria-label="格狀檢視" title="格狀檢視" :aria-pressed="items.viewMode === 'cards'" @click="items.viewMode = 'cards'"><LayoutGrid /></button>
        <button type="button" aria-label="清單檢視" title="清單檢視" :aria-pressed="items.viewMode === 'list'" @click="items.viewMode = 'list'"><List /></button>
      </div>
    </div>

    <!-- The sidebar's single 雷達 entry lands here; its settings and the quick review are one step away -->
    <div v-if="items.triageView === 'radar'" class="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-2 px-4 pb-3 text-sm text-muted-foreground sm:px-6" :class="{ 'wall-column': items.viewMode === 'list' }">
      <span class="mr-auto">雷達自動找到、還沒處理的內容。</span>
      <button type="button" class="top-button" title="快速篩選　D" @click="ui.showDeckModal = true"><ListChecks /><strong>快速篩選</strong></button>
      <button type="button" class="top-button" title="雷達設定　R" @click="openRadarSettings"><SlidersHorizontal /><strong>雷達設定</strong></button>
    </div>

    <div v-if="items.error && items.items.length" class="flex flex-wrap items-center gap-2 border-b border-hairline px-4 py-2 text-sm sm:px-6" role="alert">
      <span>{{ items.error }}目前顯示上次載入的內容。</span>
      <button class="min-h-10 px-2 font-medium underline underline-offset-4" @click="items.loadItems()">重試</button>
    </div>

    <!-- First-load placeholders, shaped like the view they stand in for -->
    <div v-if="items.loading && firstLoad" class="flex-1 overflow-hidden" aria-label="載入中">
      <div v-if="items.viewMode === 'list'" class="wall-column px-2 sm:px-4">
        <div v-for="i in 5" :key="i" class="list-row">
          <div class="item-cover item-cover--thumb list-row__thumb" />
          <div class="flex-1 space-y-3 pt-1">
            <Skeleton class="h-5 w-3/5" />
            <Skeleton class="h-4 w-1/3" />
            <Skeleton class="h-4 w-4/5" />
          </div>
        </div>
      </div>
      <div v-else class="wall-grid px-4 pt-3 sm:px-6">
        <div v-for="i in 8" :key="i">
          <div class="item-cover" />
          <Skeleton class="mt-3 h-5 w-4/5" />
          <Skeleton class="mt-2 h-4 w-2/5" />
        </div>
      </div>
    </div>

    <!-- A kind tab with nothing in this view -->
    <div v-else-if="kindEmpty" class="flex flex-1 flex-col items-center justify-center gap-5 px-6 py-16 text-center">
      <div>
        <p class="text-lg font-semibold text-foreground">這裡沒有{{ kindLabel }}</p>
        <p class="mt-1 max-w-md text-sm leading-relaxed text-muted-foreground">換一個類型，或看全部類型。</p>
      </div>
      <button class="min-h-10 rounded-lg bg-primary px-4 text-sm font-semibold text-primary-foreground hover:bg-primary-hover" @click="items.kindFilter = 'all'">顯示全部類型</button>
    </div>

    <!-- Empty state -->
    <div v-else-if="!items.loading && items.items.length === 0" class="flex flex-1 flex-col items-center justify-center gap-5 px-6 py-16 text-center">
      <Inbox class="size-8 text-muted-foreground" aria-hidden="true" />
      <div>
        <p class="text-lg font-semibold text-foreground">{{ emptyState.title }}</p>
        <p class="mt-1 max-w-md text-sm leading-relaxed text-muted-foreground">
          {{ emptyState.body }}
        </p>
      </div>
      <button class="min-h-10 rounded-lg bg-primary px-4 text-sm font-semibold text-primary-foreground hover:bg-primary-hover" @click="recoverEmpty">{{ emptyState.action }}</button>

      <!-- Other ways in, for a first visit -->
      <details v-if="firstUse" class="w-full max-w-md text-left text-sm">
        <summary class="min-h-10 cursor-pointer py-3 text-center text-muted-foreground">其他收錄方式與範例</summary>
        <div class="mt-3 border-t border-hairline pt-4 text-left">
          <div class="mb-2 flex items-center gap-2 font-semibold text-foreground">
            <Bookmark class="size-4" aria-hidden="true" />
            <span>書籤小工具（不需安裝外掛）</span>
          </div>
          <p class="mb-3 text-sm leading-relaxed text-muted-foreground">
            把下面的按鈕拖到瀏覽器的書籤列。之後在任何網頁按一下，就會收錄那個網址。
          </p>
          <div class="flex items-center gap-2">
            <a
              :href="bookmarkletHref"
              class="inline-flex min-h-10 cursor-grab select-none items-center rounded-lg bg-primary px-3 text-sm font-semibold text-primary-foreground hover:bg-primary-hover active:cursor-grabbing"
              title="拖到瀏覽器的書籤列"
              @click.prevent="toast.info('請把這個按鈕拖到瀏覽器的書籤列。')"
            >存入 OmniKeep</a>
            <button
              class="inline-flex min-h-10 cursor-pointer items-center gap-1.5 rounded-lg border border-border px-3 text-sm font-medium text-foreground transition-colors hover:bg-accent"
              @click="copyBookmarklet"
            >
              <Check v-if="copied" class="size-4" aria-hidden="true" />
              <Copy v-else class="size-4 text-muted-foreground" aria-hidden="true" />
              <span>{{ copied ? '已複製' : '複製程式碼' }}</span>
            </button>
          </div>
        </div>
        <div class="flex flex-wrap items-center justify-center gap-2 pt-4">
          <button
            class="flex min-h-10 cursor-pointer items-center gap-1.5 rounded-lg border border-border px-3 text-sm font-medium text-foreground transition-colors hover:bg-accent disabled:opacity-50"
            :disabled="isSeeding"
            @click="handleSeedDemos"
          >
            <Sparkles class="size-4" aria-hidden="true" />
            <span>{{ isSeeding ? '載入中…' : '載入範例資料' }}</span>
          </button>
          <button
            class="flex min-h-10 cursor-pointer items-center gap-1.5 rounded-lg border border-border px-3 text-sm font-medium text-foreground transition-colors hover:bg-accent"
            @click="ui.showImportModal = true"
          >
            <FolderInput class="size-4 text-muted-foreground" aria-hidden="true" />
            <span>匯入書籤</span>
          </button>
        </div>
      </details>
    </div>

    <!-- List mode: virtualized rows (ssrCount renders the first page even
         before/without ResizeObserver measurement, e.g. embedded webviews) -->
    <VList
      v-else-if="items.viewMode === 'list'"
      ref="vlist"
      :data="rows"
      :item-size="220"
      :ssr-count="8"
      class="min-h-0 flex-1 max-md:pb-20"
      :buffer-size="8"
      @scroll="loadMoreIfNearEnd"
    >
      <!-- One centred column, wide enough for a large thumbnail and about 45 characters of summary -->
      <template #default="{ item: row }">
        <div :key="row.key" class="wall-column px-2 sm:px-4">
          <h2 v-if="row.type === 'heading'" class="wall-section-title wall-section-title--row">
            {{ row.label }}<span v-if="row.count != null">{{ row.count }} 則</span>
          </h2>
          <SwipeableRow v-else-if="row.type === 'item'" :item="row.item">
            <ItemRow :item="row.item" :active="row.item.id === activeId" />
          </SwipeableRow>
          <div v-else class="wall-end" role="status">
            <template v-if="items.loadingMore"><Loader2 class="animate-spin" aria-hidden="true" />正在載入更多</template>
            <template v-else-if="items.moreError">{{ items.moreError }}<button type="button" class="wall-end__retry" @click="items.loadMore()">重試</button></template>
            <template v-else-if="!items.hasMore">已顯示全部 {{ totalCount }} 則</template>
          </div>
        </div>
      </template>
    </VList>

    <!-- Cover wall: one grid per date section, straight on the page -->
    <div v-else ref="wall" class="min-h-0 flex-1 overflow-y-auto px-4 pb-24 sm:px-6 md:pb-10" @scroll.passive="loadMoreIfNearEnd">
      <section v-for="section in sections" :key="section.key" class="wall-section" :aria-label="section.label || '搜尋結果'">
        <h2 v-if="section.label" class="wall-section-title">{{ section.label }}<span v-if="sectionCount(section) != null">{{ sectionCount(section) }} 則</span></h2>
        <div class="wall-grid">
          <ItemCards v-for="item in section.items" :key="item.id" :item="item" />
        </div>
      </section>
      <div class="wall-end" role="status">
        <template v-if="items.loadingMore"><Loader2 class="animate-spin" aria-hidden="true" />正在載入更多</template>
        <template v-else-if="items.moreError">{{ items.moreError }}<button type="button" class="wall-end__retry" @click="items.loadMore()">重試</button></template>
        <template v-else-if="!items.hasMore">已顯示全部 {{ totalCount }} 則</template>
      </div>
    </div>
  </div>
</template>
