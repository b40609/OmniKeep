<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { VList } from 'virtua/vue'
import { Inbox, Sparkles, FolderInput, Bookmark, Copy, Check } from 'lucide-vue-next'
import * as api from '@/lib/api'
import type { Item } from '@/lib/api'
import { toast } from 'vue-sonner'
import ItemRow from './ItemRow.vue'
import ItemCards from './ItemCards.vue'
import SwipeableRow from './SwipeableRow.vue'
import Skeleton from '@/components/ui/skeleton/Skeleton.vue'
import { KIND_LABELS, KIND_TABS, groupByDay, type WallSection } from '@/lib/wall'
import { useItemsStore, PAGE_SIZE } from '@/stores/items'
import { useUiStore } from '@/stores/ui'

const items = useItemsStore()
const ui = useUiStore()

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
  if (items.searchQuery.trim()) return { title: '找不到符合的收藏', body: '試試其他關鍵字，或清除搜尋與分類條件。', action: '清除搜尋條件' }
  if (items.currentCategory !== '全部') return { title: '這個分類沒有項目', body: '可以改看所有分類的收藏。', action: '顯示所有分類' }
  if (firstUse.value) return { title: '收下值得再讀的內容', body: '按上方的「收錄」貼上網址或筆記，就會存進來。', action: '新增第一則筆記' }
  if (items.triageView === 'inbox') return { title: '待讀項目已清空', body: '已封存的內容仍可在全部項目中找到。', action: '查看全部項目' }
  if (items.triageView === 'starred') return { title: '還沒有加星的收藏', body: '在想留下的項目按「留著」，就能在這裡找到。', action: '查看全部項目' }
  if (items.triageView === 'archived') return { title: '還沒有封存項目', body: '看完按「知道了」，內容會收到這裡。', action: '查看全部項目' }
  return { title: '目前沒有收藏', body: '貼上網址或新增筆記，開始收錄內容。', action: '新增筆記' }
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
 * Date sections ("今天收的", "昨天", ...) for both views. Search results are ranked
 * by relevance, not by date, so they stay one untitled section.
 */
const sections = computed<WallSection<Item>[]>(() =>
  items.ranked ? [{ key: 'ranked', label: '', items: items.visibleItems }] : groupByDay(items.visibleItems),
)

type ListRow =
  | { type: 'heading'; key: string; label: string; count: number }
  | { type: 'item'; key: string; item: Item }

/** The virtual list takes one flat array, so a section heading is a row of its own. */
const rows = computed<ListRow[]>(() =>
  sections.value.flatMap((section): ListRow[] => [
    ...(section.label ? [{ type: 'heading' as const, key: 'h-' + section.key, label: section.label, count: section.items.length }] : []),
    ...section.items.map((item) => ({ type: 'item' as const, key: 'i-' + item.id, item })),
  ]),
)

/** The kind tabs only filter the page that is loaded; the empty tab says so. */
const kindEmpty = computed(() => items.items.length > 0 && items.visibleItems.length === 0)
const kindLabel = computed(() => (items.kindFilter === 'all' ? '' : KIND_LABELS[items.kindFilter]))
/** The API hands back one page and the list does not fetch the next: say where it stops. */
const truncated = computed(() => items.items.length >= PAGE_SIZE)

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
    toast.success('已複製書籤小工具代碼')
    setTimeout(() => (copied.value = false), 2000)
  } catch {
    toast.error('無法複製，請允許剪貼簿存取後重試。')
  }
}

const isSeeding = ref(false)
async function handleSeedDemos() {
  isSeeding.value = true
  const t = toast.loading('正在載入新手示範資料…')
  try {
    await api.seedDemoItems()
    toast.success('已載入範例資料', {
      id: t,
      description: '示範 YouTube、B站與開源專案的呈現格式；內容為範例，未執行即時分析',
    })
    await items.refreshAll()
  } catch (e) {
    toast.error('示範資料載入失敗: ' + (e as Error).message, { id: t })
  } finally {
    isSeeding.value = false
  }
}

defineExpose({ scrollToIndex, scrollToItem })
</script>

<template>
  <div class="@container flex min-h-0 flex-1 flex-col bg-shell" :aria-busy="items.loading">
    <!-- Kind tabs, and how many items are showing -->
    <div class="flex shrink-0 items-center gap-3 px-4 pb-2 pt-2 sm:px-6">
      <div class="no-scrollbar -my-1 flex min-w-0 gap-2.5 overflow-x-auto py-1" role="group" aria-label="類型">
        <button
          v-for="tab in KIND_TABS"
          :key="tab.id"
          type="button"
          class="kind-chip"
          :aria-pressed="items.kindFilter === tab.id"
          @click="items.kindFilter = tab.id"
        >{{ tab.label }}</button>
      </div>
      <p class="ml-auto min-w-0 shrink-0 truncate text-xs tabular-nums text-muted-foreground max-sm:max-w-[40%]" aria-live="polite">
        <template v-if="items.loading">載入中…</template>
        <template v-else>
          <span v-if="items.searchQuery.trim()">搜尋「{{ items.searchQuery.trim() }}」</span>
          {{ items.visibleItems.length }} 則
        </template>
      </p>
    </div>

    <div v-if="items.error && items.items.length" class="flex flex-wrap items-center gap-2 border-b border-hairline px-4 py-2 text-sm sm:px-6" role="alert">
      <span>{{ items.error }}目前顯示上次載入的內容。</span>
      <button class="min-h-11 px-2 font-medium underline underline-offset-4" @click="items.loadItems()">重試</button>
    </div>

    <!-- First-load placeholders, shaped like the view they stand in for -->
    <div v-if="items.loading && firstLoad" class="flex-1 overflow-hidden" aria-label="載入中">
      <div v-if="items.viewMode === 'list'" class="max-w-[56rem]">
        <div v-for="i in 9" :key="i" class="flex items-center gap-3 border-b border-hairline px-4 py-3 sm:px-6">
          <div class="item-cover item-cover--thumb w-24 shrink-0 @min-[26rem]:w-[120px]" />
          <div class="flex-1 space-y-2">
            <Skeleton class="h-4 w-3/4" />
            <Skeleton class="h-3 w-1/3" />
          </div>
        </div>
      </div>
      <div v-else class="wall-grid px-4 pt-3 sm:px-6">
        <div v-for="i in 8" :key="i">
          <div class="item-cover" />
          <Skeleton class="mt-3 h-4 w-4/5" />
          <Skeleton class="mt-2 h-3 w-2/5" />
        </div>
      </div>
    </div>

    <!-- Empty state -->
    <div v-else-if="!items.loading && items.items.length === 0" class="flex flex-1 flex-col items-center justify-center gap-5 px-6 py-16 text-center animate-in fade-in duration-300">
      <Inbox class="size-8 text-muted-foreground" aria-hidden="true" />
      <div>
        <p class="text-lg font-semibold text-foreground">{{ emptyState.title }}</p>
        <p class="mt-1 max-w-md text-sm leading-relaxed text-muted-foreground">
          {{ emptyState.body }}
        </p>
      </div>
      <button class="min-h-11 rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary-hover" @click="recoverEmpty">{{ emptyState.action }}</button>

      <!-- 1-Click Browser Bookmarklet Ribbon -->
      <details v-if="firstUse" class="w-full max-w-md text-left text-sm">
        <summary class="min-h-11 cursor-pointer py-3 text-center text-muted-foreground">其他收錄方式與範例</summary>
      <div class="mt-3 border-t border-hairline pt-4 text-left text-xs">
        <div class="flex items-center justify-between gap-2 mb-2">
          <div class="flex items-center gap-1.5 font-semibold text-foreground">
            <Bookmark class="size-3.5 text-primary" />
            <span>瀏覽器隨手存小工具 (無需外掛)</span>
          </div>
        </div>
        <p class="text-2xs text-muted-foreground leading-relaxed mb-3">
          使用電腦時，將下方連結拖到瀏覽器的書籤列。瀏覽文章或影片時點擊，即可收錄目前的網址。
        </p>
        <div class="flex items-center gap-2">
          <a
            :href="bookmarkletHref"
            class="inline-flex min-h-11 items-center gap-1.5 rounded-lg bg-primary px-3 text-xs font-medium text-primary-foreground hover:bg-primary-hover cursor-grab active:cursor-grabbing select-none"
            title="請將我拖曳至瀏覽器書籤列"
            @click.prevent="toast.info('請直接將此按鈕拖曳到瀏覽器的「書籤列（Bookmarks Bar）」中！')"
          >
            <span>存入 OmniKeep</span>
          </a>
          <button
            class="inline-flex min-h-11 items-center gap-1 rounded-lg border border-border bg-card px-3 text-xs font-medium text-foreground transition-colors hover:bg-accent cursor-pointer"
            @click="copyBookmarklet"
          >
            <Check v-if="copied" class="size-3 text-success" />
            <Copy v-else class="size-3 text-muted-foreground" />
            <span>{{ copied ? '已複製代碼' : '複製代碼' }}</span>
          </button>
        </div>
      </div>

      <!-- Actionable onboarding buttons -->
      <div class="flex flex-wrap items-center justify-center gap-2 pt-1">
        <button
          class="flex min-h-11 items-center gap-1.5 rounded-lg border border-border px-3 text-xs font-medium text-foreground transition-colors hover:bg-accent cursor-pointer disabled:opacity-50"
          :disabled="isSeeding"
          @click="handleSeedDemos"
        >
          <Sparkles class="size-3.5" />
          <span>{{ isSeeding ? '載入中…' : '載入範例資料（非即時分析）' }}</span>
        </button>
        <button
          class="flex min-h-11 items-center gap-1.5 rounded-lg border border-border px-3 text-xs font-medium text-foreground transition-colors hover:bg-accent cursor-pointer"
          @click="ui.showImportModal = true"
        >
          <FolderInput class="size-3.5 text-muted-foreground" />
          <span>匯入書籤 / 匯出</span>
        </button>
      </div>
      </details>
    </div>

    <!-- A kind tab with nothing in the loaded page -->
    <div v-else-if="kindEmpty" class="flex flex-1 flex-col items-center justify-center gap-5 px-6 py-16 text-center">
      <div>
        <p class="text-lg font-semibold text-foreground">這裡沒有{{ kindLabel }}</p>
        <p class="mt-1 max-w-md text-sm leading-relaxed text-muted-foreground">
          類型只篩選已載入的 {{ items.items.length }} 則。<template v-if="truncated">更早的收藏請用搜尋找。</template>
        </p>
      </div>
      <button class="min-h-11 rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary-hover" @click="items.kindFilter = 'all'">顯示全部類型</button>
    </div>

    <!-- List mode: virtualized rows (ssrCount renders the first page even
         before/without ResizeObserver measurement, e.g. embedded webviews) -->
    <VList
      v-else-if="items.viewMode === 'list'"
      ref="vlist"
      :data="rows"
      :item-size="93"
      :ssr-count="12"
      class="min-h-0 flex-1 max-md:pb-20"
      :buffer-size="8"
    >
      <!-- Rows stop at 56rem: thumbnail, about 40 characters of title, the actions. A wider
           screen leaves the rest to the reader, which opens on that side. -->
      <template #default="{ item: row }">
        <div :key="row.key" class="max-w-[56rem]">
          <h2 v-if="row.type === 'heading'" class="wall-section-title !m-0 border-b border-hairline px-4 pb-2.5 pt-5 sm:px-6">
            {{ row.label }}<span>{{ row.count }} 則</span>
          </h2>
          <SwipeableRow v-else :item="row.item">
            <ItemRow :item="row.item" :active="row.item.id === activeId" />
          </SwipeableRow>
        </div>
      </template>
    </VList>

    <!-- Cover wall: one grid per date section, straight on the page -->
    <div v-else ref="wall" class="min-h-0 flex-1 overflow-y-auto px-4 pb-24 sm:px-6 md:pb-10">
      <section v-for="section in sections" :key="section.key" :aria-label="section.label || '搜尋結果'">
        <h2 v-if="section.label" class="wall-section-title">{{ section.label }}<span>{{ section.items.length }} 則</span></h2>
        <div class="wall-grid" :class="section.label ? '' : 'pt-3'">
          <ItemCards v-for="item in section.items" :key="item.id" :item="item" />
        </div>
      </section>
      <p v-if="truncated" class="pt-8 text-center text-xs text-muted-foreground">
        只載入{{ items.ranked ? '最相關' : '最新' }}的 {{ items.items.length }} 則。更早的收藏請用搜尋找。
      </p>
    </div>
  </div>
</template>
