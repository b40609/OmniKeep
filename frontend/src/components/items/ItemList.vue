<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { VList } from 'virtua/vue'
import { Inbox, Sparkles, FolderInput, Bookmark, Copy, Check } from 'lucide-vue-next'
import * as api from '@/lib/api'
import { toast } from 'vue-sonner'
import ItemRow from './ItemRow.vue'
import ItemCards from './ItemCards.vue'
import SwipeableRow from './SwipeableRow.vue'
import Skeleton from '@/components/ui/skeleton/Skeleton.vue'
import { useItemsStore } from '@/stores/items'
import { useUiStore } from '@/stores/ui'

const items = useItemsStore()
const ui = useUiStore()

const vlist = ref<InstanceType<typeof VList> | null>(null)

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
  if (firstUse.value) return { title: '收下值得再讀的內容', body: '在上方貼上網址或筆記，按「收錄」即可儲存。', action: '新增第一則筆記' }
  if (items.triageView === 'inbox') return { title: '待讀項目已清空', body: '已封存的內容仍可在全部項目中找到。', action: '查看全部項目' }
  if (items.triageView === 'starred') return { title: '還沒有星標收藏', body: '為想保留的項目加上星標，就能在這裡找到。', action: '查看全部項目' }
  if (items.triageView === 'archived') return { title: '還沒有封存項目', body: '讀完後按「封存」，內容會保留在這裡。', action: '查看全部項目' }
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

/** Scroll a row into view — used by J/K keyboard navigation. */
function scrollToIndex(index: number) {
  vlist.value?.scrollToIndex(index)
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



defineExpose({ scrollToIndex })
</script>

<template>
  <div class="@container flex min-h-0 flex-1 flex-col bg-card [&::-webkit-scrollbar]:bg-transparent" :aria-busy="items.loading">
    <!-- Stream meta toolbar -->
    <div class="flex h-9 shrink-0 items-center justify-between px-4 text-2xs text-subtle-foreground">
      <div>
        <span>{{ items.loading ? '載入中…' : `${items.items.length} 個收錄項目` }}</span>
        <span v-if="items.searchQuery" class="ml-2 font-medium text-primary">搜尋："{{ items.searchQuery }}"</span>
      </div>
    </div>

    <div v-if="items.error && items.items.length" class="flex flex-wrap items-center gap-2 border-b border-hairline px-4 py-2 text-sm" role="alert">
      <span>{{ items.error }}目前顯示上次載入的內容。</span>
      <button class="min-h-11 px-2 font-medium underline underline-offset-4" @click="items.loadItems()">重試</button>
    </div>

    <!-- First-load skeletons -->
    <div v-if="items.loading && firstLoad" class="flex-1 space-y-0 overflow-hidden" aria-label="載入中">
      <div v-for="i in 9" :key="i" class="flex items-start gap-3 border-b border-border/40 px-4 py-3.5">
        <Skeleton class="mt-1.5 size-2.5 rounded-full" />
        <div class="flex-1 space-y-2">
          <div class="flex gap-2">
            <Skeleton class="h-3.5 w-14" />
            <Skeleton class="h-3.5 w-16" />
            <Skeleton class="h-3.5 w-12 opacity-50" />
          </div>
          <Skeleton class="h-4 w-3/4" />
          <Skeleton class="h-3 w-1/2 opacity-60" />
        </div>
      </div>
    </div>

    <!-- Empty state -->
    <div v-else-if="!items.loading && items.items.length === 0" class="flex flex-1 flex-col items-center justify-center gap-5 px-6 py-16 text-center animate-in fade-in duration-300">
      <div class="flex size-14 items-center justify-center rounded-2xl border border-border/60 bg-card text-primary shadow-xs">
        <Inbox class="size-6" />
      </div>
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

    <!-- List mode: virtualized rows (ssrCount renders the first page even
         before/without ResizeObserver measurement, e.g. embedded webviews) -->
    <VList
      v-else-if="items.viewMode === 'list'"
      ref="vlist"
      :data="items.items"
      :item-size="160"
      :ssr-count="12"
      class="min-h-0 flex-1"
      :buffer-size="8"
    >
      <template #default="{ item }">
        <div :key="item.id" class="contents">
          <SwipeableRow :item="item">
            <ItemRow :item="item" :active="item.id === activeId" />
          </SwipeableRow>
        </div>
      </template>
    </VList>

    <!-- Cards mode: responsive grid with FLIP enter/leave -->
    <div v-else class="min-h-0 flex-1 overflow-y-auto bg-background p-4 sm:p-6 pb-20 md:pb-6">
      <div class="mx-auto max-w-[1600px]">
        <TransitionGroup
          name="cards"
          tag="div"
          class="grid grid-cols-1 content-start gap-4 @min-[38rem]:grid-cols-2 @min-[64rem]:grid-cols-3"
        >
          <ItemCards v-for="item in items.items" :key="item.id" :item="item" />
        </TransitionGroup>
      </div>
    </div>
  </div>
</template>

<style scoped>
.cards-enter-active {
  transition: opacity 240ms cubic-bezier(0.22, 1, 0.36, 1), transform 240ms cubic-bezier(0.22, 1, 0.36, 1);
}
.cards-enter-from {
  opacity: 0;
  transform: translateY(10px) scale(0.98);
}
.cards-leave-active {
  transition: opacity 160ms ease, transform 160ms ease;
}
.cards-leave-to {
  opacity: 0;
  transform: scale(0.96);
}
.cards-move {
  transition: transform 280ms cubic-bezier(0.22, 1, 0.36, 1);
}
@media (prefers-reduced-motion: reduce) {
  .cards-enter-active, .cards-leave-active, .cards-move { transition: none; }
  .cards-enter-from, .cards-leave-to { transform: none; }
}
</style>
