<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { VList } from 'virtua/vue'
import { Inbox, Sparkles, FolderInput, Radio, Bookmark, Copy, Check } from 'lucide-vue-next'
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
  await navigator.clipboard.writeText(bookmarkletHref.value)
  copied.value = true
  toast.success('已複製書籤小工具代碼至剪貼簿！')
  setTimeout(() => (copied.value = false), 2000)
}

const isSeeding = ref(false)
async function handleSeedDemos() {
  isSeeding.value = true
  const t = toast.loading('正在載入新手示範資料…')
  try {
    await api.seedDemoItems()
    toast.success('已注入示範卡片', {
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
  <div class="flex min-h-0 flex-1 flex-col backdrop-blur-2xl [&::-webkit-scrollbar]:bg-transparent">
    <!-- Stream meta toolbar -->
    <div class="flex h-9 shrink-0 items-center justify-between px-4 text-2xs text-subtle-foreground">
      <div>
        <span>{{ items.loading ? '載入中…' : `${items.items.length} 個收錄項目` }}</span>
        <span v-if="items.searchQuery" class="ml-2 font-medium text-primary">搜尋："{{ items.searchQuery }}"</span>
      </div>
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
        <p class="text-base font-semibold tracking-tight text-foreground">目前無任何收錄項目</p>
        <p class="mt-1 max-w-md text-xs leading-relaxed text-muted-foreground">
          可於上方輸入列貼上網址或筆記快速納庫，亦可透過下方隨手存小工具或範例資料快速上手。
        </p>
      </div>

      <!-- 1-Click Browser Bookmarklet Ribbon -->
      <div class="w-full max-w-md rounded-xl border border-primary/20 bg-primary/5 p-3.5 text-left text-xs shadow-xs">
        <div class="flex items-center justify-between gap-2 mb-2">
          <div class="flex items-center gap-1.5 font-semibold text-foreground">
            <Bookmark class="size-3.5 text-primary" />
            <span>瀏覽器隨手存小工具 (無需外掛)</span>
          </div>
          <span class="rounded bg-primary/10 px-1.5 py-0.5 text-2xs font-mono font-medium text-primary">推薦</span>
        </div>
        <p class="text-2xs text-muted-foreground leading-relaxed mb-3">
          拖曳下方按鈕至瀏覽器<b>「書籤列」</b>；平時瀏覽 YouTube、B站、Twitter 或文章時點擊即秒存並自動關閉！
        </p>
        <div class="flex items-center gap-2">
          <a
            :href="bookmarkletHref"
            class="inline-flex items-center gap-1.5 rounded-lg border border-primary bg-primary px-3 py-1.5 font-mono text-xs font-bold text-primary-foreground shadow-2xs hover:opacity-90 active:scale-95 cursor-grab active:cursor-grabbing select-none"
            title="請將我拖曳至瀏覽器書籤列"
            @click.prevent="toast.info('請直接將此按鈕拖曳到瀏覽器的「書籤列（Bookmarks Bar）」中！')"
          >
            <span>🔖 存入 OmniKeep</span>
          </a>
          <button
            class="inline-flex items-center gap-1 rounded-lg border border-border bg-card px-2.5 py-1.5 text-2xs font-medium text-foreground transition hover:bg-accent active:scale-95 cursor-pointer shadow-2xs"
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
          class="flex items-center gap-1.5 rounded-full border border-primary/30 bg-primary/10 px-3.5 py-1.5 text-xs font-semibold text-primary transition hover:bg-primary hover:text-primary-foreground active:scale-95 cursor-pointer shadow-2xs disabled:opacity-50"
          :disabled="isSeeding"
          @click="handleSeedDemos"
        >
          <Sparkles class="size-3.5" />
          <span>{{ isSeeding ? '載入中…' : '載入範例資料（非即時分析）' }}</span>
        </button>
        <button
          class="flex items-center gap-1.5 rounded-full border border-border bg-card px-3.5 py-1.5 text-xs font-medium text-foreground transition hover:bg-accent active:scale-95 cursor-pointer shadow-2xs"
          @click="ui.showImportModal = true"
        >
          <FolderInput class="size-3.5 text-muted-foreground" />
          <span>匯入書籤 / 匯出</span>
        </button>
        <button
          class="flex items-center gap-1.5 rounded-full border border-border bg-card px-3.5 py-1.5 text-xs font-medium text-foreground transition hover:bg-accent active:scale-95 cursor-pointer shadow-2xs"
          @click="ui.showRadarModal = true"
        >
          <Radio class="size-3.5 text-muted-foreground" />
          <span>情報雷達巡檢</span>
        </button>
      </div>
    </div>

    <!-- List mode: virtualized rows (ssrCount renders the first page even
         before/without ResizeObserver measurement, e.g. embedded webviews) -->
    <VList
      v-else-if="items.viewMode === 'list'"
      ref="vlist"
      :data="items.items"
      :item-size="92"
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
    <div v-else class="min-h-0 flex-1 overflow-y-auto p-4 sm:p-6">
      <div class="mx-auto max-w-[1600px]">
        <TransitionGroup
          name="cards"
          tag="div"
          class="grid grid-cols-1 content-start gap-4 sm:grid-cols-2 lg:grid-cols-2 xl:grid-cols-3"
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
  position: absolute;
  width: calc(50% - 6px);
}
.cards-leave-to {
  opacity: 0;
  transform: scale(0.96);
}
.cards-move {
  transition: transform 280ms cubic-bezier(0.22, 1, 0.36, 1);
}
</style>
