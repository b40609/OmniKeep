<script setup lang="ts">
import { ref, watch } from 'vue'
import {
  ArrowLeft, X, Star, Copy, ExternalLink, Trash2, ChevronUp, ChevronDown, Ban,
  Sparkles, BookOpen, CheckCircle2, Maximize2, Minimize2,
} from 'lucide-vue-next'
import Badge from '@/components/ui/badge/Badge.vue'
import Skeleton from '@/components/ui/skeleton/Skeleton.vue'
import AnalysisTab from './AnalysisTab.vue'
import ReaderTab from './ReaderTab.vue'
import ReadingProgress from './ReadingProgress.vue'
import * as api from '@/lib/api'
import { sourceMeta } from '@/lib/format'
import { useUiStore } from '@/stores/ui'
import { useItemsStore } from '@/stores/items'
import { useMutations } from '@/composables/useMutations'
import { useSignal } from '@/composables/useSignal'
import { toast } from 'vue-sonner'

const ui = useUiStore()
const itemsStore = useItemsStore()
const { toggleStar, toggleRead, updateCategory, removeItem } = useMutations()
const { tuneItem } = useSignal()

const fetchingFull = ref(false)

/* Mobile bottom-sheet: drag the header down to dismiss. */
const sheetDy = ref(0)
let sheetStartY = 0
let sheetDragging = false

function onSheetTouchStart(e: TouchEvent) {
  const scroll = (e.currentTarget as HTMLElement).closest('[data-reader-root]')?.querySelector('[data-reader-scroll]')
  // Only engage when the content is scrolled to the top (native over-scroll feel)
  if (scroll && scroll.scrollTop > 4) return
  sheetStartY = e.touches[0].clientY
  sheetDragging = true
}
function onSheetTouchMove(e: TouchEvent) {
  if (!sheetDragging) return
  const dy = e.touches[0].clientY - sheetStartY
  if (dy > 0) {
    e.preventDefault()
    sheetDy.value = dy * 0.9
  }
}
function onSheetTouchEnd() {
  if (!sheetDragging) return
  sheetDragging = false
  if (sheetDy.value > 110) {
    ui.activeItem = null
    ui.focusMode = false
  }
  sheetDy.value = 0
}

// Fetch the full item (citations, sub-entities, raw content) once selected.
watch(
  () => ui.activeItem?.id,
  async (id) => {
    if (id == null) return
    fetchingFull.value = true
    try {
      const full = await api.getItem(id)
      // Only apply if the user hasn't moved on to another item.
      if (ui.activeItem?.id === full.id) {
        ui.activeItem = full
      }
    } catch {
      /* list-level fields already render */
    } finally {
      fetchingFull.value = false
    }
  },
  { immediate: true },
)

function copyTakeaway() {
  const it = ui.activeItem
  if (!it) return
  const text = `${it.title_l1}\n\n【核心論點】\n${it.summary_l1}\n\n原始連結: ${it.url}`
  navigator.clipboard.writeText(text).then(() => toast.success('已複製白話重點')).catch(() => toast.error('複製失敗'))
}
</script>

<template>
  <section
    v-if="ui.activeItem"
    data-reader-root
    class="safe-top safe-bottom fixed inset-0 z-40 flex flex-col backdrop-blur-2xl max-lg:bg-white/45 max-lg:dark:bg-black/45 lg:static lg:z-auto lg:flex-1 lg:bg-white/30 lg:dark:bg-white/[0.04]"
    :class="ui.focusMode ? 'lg:inset-0 lg:z-30 lg:fixed' : ''"
    :style="sheetDy ? { transform: `translateY(${sheetDy}px)`, transition: 'none' } : { transition: 'transform 300ms cubic-bezier(0.22, 1, 0.36, 1)' }"
    aria-label="閱讀面板"
  >
    <!-- Mobile drag handle -->
    <div class="flex h-1.5 shrink-0 items-center justify-center bg-white/40 dark:bg-white/[0.08] lg:hidden" aria-hidden="true">
      <div class="h-1 w-10 rounded-full bg-white/60 dark:bg-white/20" />
    </div>
    <!-- Reader header -->
    <div
      class="ios-blur flex h-14 shrink-0 items-center justify-between gap-2 border-b border-hairline px-3 sm:px-4"
      @touchstart="onSheetTouchStart"
      @touchmove="onSheetTouchMove"
      @touchend="onSheetTouchEnd"
    >
      <div class="flex min-w-0 items-center gap-1.5 sm:gap-2">
        <button
          class="mr-0.5 flex h-9 items-center gap-1 rounded-lg border border-border bg-card px-2.5 text-xs font-semibold text-foreground shadow-sm transition-all active:scale-95 lg:hidden"
          aria-label="返回清單"
          @click="ui.activeItem = null"
        >
          <ArrowLeft class="size-4 text-primary-soft-foreground" />
          <span>清單</span>
        </button>

        <Badge :class="sourceMeta(ui.activeItem.source_type).badgeClass" class="shrink-0">
          {{ ui.activeItem.source_type }}
        </Badge>

        <!-- Category switcher -->
        <div class="relative">
          <select
            :value="ui.activeItem.category_name"
            class="h-8 cursor-pointer appearance-none rounded-full bg-muted pr-7 pl-3 text-xs font-semibold text-foreground transition-all hover:text-primary focus:outline-none focus:ring-2 focus:ring-primary/30"
            aria-label="切換分類"
            @change="updateCategory(ui.activeItem!, ($event.target as HTMLSelectElement).value)"
          >
            <option v-for="c in itemsStore.categories" :key="c.id" :value="c.name">{{ c.name }}</option>
            <option value="Inbox">Inbox</option>
          </select>
          <svg class="pointer-events-none absolute right-2.5 top-1/2 size-3 -translate-y-1/2 text-subtle-foreground" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m6 9 6 6 6-6"/></svg>
        </div>

        <!-- Triage status -->
        <button
          class="flex h-8 shrink-0 items-center gap-1.5 rounded-full px-3 text-xs font-semibold transition-all active:scale-[0.96]"
          :class="ui.activeItem.is_read
            ? 'bg-success-soft text-success'
            : 'bg-primary-soft text-primary'"
          :title="ui.activeItem.is_read ? '移回待讀（E）' : '封存歸檔（E）'"
          @click="toggleRead(ui.activeItem)"
        >
          <CheckCircle2 class="size-3.5" />
          <span class="max-sm:hidden">{{ ui.activeItem.is_read ? '已封存' : '待消化' }}</span>
        </button>
      </div>

      <!-- Actions -->
      <div class="flex shrink-0 items-center gap-0.5">
        <!-- Signal equalizer -->
        <div class="mr-1 flex items-center rounded-full bg-muted p-0.5" role="group" aria-label="訊號調諧">
          <button class="rounded-full p-1.5 text-muted-foreground transition-colors hover:bg-card hover:text-primary" title="增強此類關注（+）" aria-label="增強訊號" @click="tuneItem({ item: ui.activeItem!, action: 'boost' })">
            <ChevronUp class="size-3.5" />
          </button>
          <button class="rounded-full p-1.5 text-muted-foreground transition-colors hover:bg-card hover:text-danger" title="降低此類頻率（-）" aria-label="降低頻率" @click="tuneItem({ item: ui.activeItem!, action: 'dampen' })">
            <ChevronDown class="size-3.5" />
          </button>
          <button class="rounded-full p-1.5 text-subtle-foreground transition-colors hover:bg-card hover:text-danger" title="徹底屏蔽核心標籤" aria-label="靜音" @click="tuneItem({ item: ui.activeItem!, action: 'mute' })">
            <Ban class="size-3.5" />
          </button>
        </div>

        <button class="rounded-lg p-2 transition-colors hover:bg-accent" :class="ui.activeItem.is_starred ? 'text-warning' : 'text-muted-foreground hover:text-warning'" :title="ui.activeItem.is_starred ? '取消星標（S）' : '加星標（S）'" aria-label="星標" @click="toggleStar(ui.activeItem)">
          <Star class="size-4" :class="ui.activeItem.is_starred ? 'fill-warning' : ''" />
        </button>
        <button class="rounded-lg p-2 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground" title="複製白話重點" aria-label="複製重點" @click="copyTakeaway">
          <Copy class="size-4" />
        </button>
        <a :href="ui.activeItem.url" target="_blank" rel="noopener" class="rounded-lg p-2 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground" title="前往原始網址" aria-label="原始網址">
          <ExternalLink class="size-4" />
        </a>
        <button
          class="rounded-lg p-2 text-subtle-foreground transition-colors hover:bg-danger-soft hover:text-danger"
          title="刪除項目"
          aria-label="刪除項目"
          @click="removeItem(ui.activeItem)"
        >
          <Trash2 class="size-4" />
        </button>
        <button
          class="ml-1 hidden rounded-lg p-2 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground lg:flex"
          :title="ui.focusMode ? '退出沉浸模式' : '沉浸全寬閱讀'"
          aria-label="沉浸模式"
          @click="ui.focusMode = !ui.focusMode"
        >
          <Minimize2 v-if="ui.focusMode" class="size-4" />
          <Maximize2 v-else class="size-4" />
        </button>
        <button class="ml-1 hidden rounded-lg p-2 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground lg:flex" title="關閉（Esc）" aria-label="關閉面板" @click="ui.activeItem = null; ui.focusMode = false">
          <X class="size-4" />
        </button>
      </div>
    </div>

    <!-- Tabs: iOS segmented control -->
    <div class="flex h-12 shrink-0 items-center justify-between border-b border-hairline px-3 sm:px-4">
      <div class="flex items-center rounded-[10px] bg-muted p-0.5" role="tablist" aria-label="閱讀模式">
        <button
          v-for="t in [
            { id: 'analysis', label: '深度解構', icon: Sparkles },
            { id: 'reader', label: '純淨閱讀', icon: BookOpen },
          ]"
          :key="t.id"
          role="tab"
          :aria-selected="ui.detailTab === t.id"
          class="flex h-8 items-center gap-1.5 rounded-[8px] px-3.5 text-xs transition-all duration-200"
          :class="ui.detailTab === t.id
            ? 'bg-card text-foreground shadow-sm font-semibold'
            : 'text-muted-foreground active:opacity-70'"
          @click="ui.detailTab = t.id as 'analysis' | 'reader'"
        >
          <component :is="t.icon" class="size-3.5" :class="ui.detailTab === t.id ? 'text-primary' : ''" />
          {{ t.label }}
        </button>
      </div>

      <!-- Reader font size -->
      <div v-if="ui.detailTab === 'reader'" class="flex items-center gap-1">
        <button class="size-7 rounded-full bg-muted text-xs font-semibold text-muted-foreground transition-all hover:text-foreground active:scale-90" aria-label="縮小字級" @click="ui.readerFontSize = Math.max(13, ui.readerFontSize - 1)">A-</button>
        <span class="w-7 text-center text-2xs tabular-nums text-subtle-foreground">{{ ui.readerFontSize }}</span>
        <button class="size-7 rounded-full bg-muted text-xs font-semibold text-muted-foreground transition-all hover:text-foreground active:scale-90" aria-label="放大字級" @click="ui.readerFontSize = Math.min(20, ui.readerFontSize + 1)">A+</button>
      </div>
    </div>

    <!-- Content -->
    <div data-reader-scroll class="relative min-h-0 flex-1 overflow-y-auto">
      <ReadingProgress />
      <div v-if="fetchingFull && !ui.activeItem.citations && !ui.activeItem.deep_analysis" class="mx-auto max-w-3xl space-y-4 p-6 lg:p-8">
        <Skeleton class="h-7 w-3/4" />
        <Skeleton class="h-3.5 w-1/2" />
        <div class="space-y-2 pt-6">
          <Skeleton class="h-4 w-full" />
          <Skeleton class="h-4 w-11/12" />
          <Skeleton class="h-4 w-4/5" />
          <Skeleton class="h-4 w-2/3" />
        </div>
      </div>
      <AnalysisTab v-else-if="ui.detailTab === 'analysis'" />
      <ReaderTab v-else />
    </div>
  </section>
</template>
