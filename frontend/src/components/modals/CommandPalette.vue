<script setup lang="ts">
import { ref, computed, watch, nextTick } from 'vue'
import {
  Search, MessageCircleQuestion, Inbox, Star, Archive, Compass, FilePlus, Layers, Upload, Eye, Settings,
  SlidersHorizontal, SunMoon, ExternalLink, Tag, CornerDownLeft, GalleryHorizontalEnd, Bell,
} from 'lucide-vue-next'
import { useUiStore } from '@/stores/ui'
import { useItemsStore, type TriageView } from '@/stores/items'
import { useExperimentsStore } from '@/stores/experiments'
import { WATCH_CATEGORIES } from '@/lib/experiments'
import { useTheme } from '@/composables/useTheme'
import { cleanHost, sourceMeta } from '@/lib/format'

const ui = useUiStore()
const itemsStore = useItemsStore()
const experiments = useExperimentsStore()
const { mode, labels, toggle: toggleTheme } = useTheme()

const searchQuery = ref('')
const selectedIndex = ref(0)
const inputRef = ref<HTMLInputElement | null>(null)
const listRef = ref<HTMLElement | null>(null)

interface PaletteAction {
  id: string
  title: string
  subtitle?: string
  category: 'actions' | 'views' | 'items'
  icon: any
  badge?: string
  run: () => void
}

const closeThen = (run: () => void) => () => {
  ui.showCommandPalette = false
  run()
}
const showView = (view: TriageView) => closeThen(() => {
  itemsStore.triageView = view
  itemsStore.currentCategory = '全部'
  void itemsStore.loadItems()
})

const staticActions = computed<PaletteAction[]>(() => {
  const actions: PaletteAction[] = [
    { id: 'action-brain', title: '提問', subtitle: '用收藏的內容回答問題', category: 'actions', icon: MessageCircleQuestion, run: closeThen(() => (ui.showBrainModal = true)) },
    { id: 'action-new-note', title: '新增筆記', subtitle: '寫一則文字筆記', category: 'actions', icon: FilePlus, run: closeThen(() => (ui.showNoteModal = true)) },
    { id: 'action-import', title: '匯入書籤', subtitle: '從瀏覽器的書籤檔或一批連結匯入', category: 'actions', icon: Upload, run: closeThen(() => ui.openImport('file')) },
    { id: 'action-settings', title: '設定', subtitle: '外觀、收錄管道、AI 連線、通知、備份', category: 'actions', icon: Settings, run: closeThen(() => ui.openSettings()) },
    { id: 'action-push', title: '通知設定', subtitle: '這台裝置要不要收通知', category: 'actions', icon: Bell, run: closeThen(() => ui.openSettings('notifications')) },
    { id: 'action-theme', title: '切換主題', subtitle: `目前：${labels[mode.value]}`, category: 'actions', icon: SunMoon, run: () => toggleTheme() },
    // Views
    { id: 'view-inbox', title: '收件匣', subtitle: `${itemsStore.stats.inbox} 則還沒看`, category: 'views', icon: Inbox, run: showView('inbox') },
    { id: 'view-starred', title: '加星', subtitle: `${itemsStore.stats.starred} 則`, category: 'views', icon: Star, run: showView('starred') },
    { id: 'view-archived', title: '封存', subtitle: `${itemsStore.stats.archived} 則`, category: 'views', icon: Archive, run: showView('archived') },
  ]
  // Experimental features are listed only while they are switched on (設定 › 實驗功能).
  if (experiments.flags.radar) {
    actions.push(
      { id: 'view-radar', title: '探索', subtitle: `${itemsStore.stats.radar || 0} 則還沒處理`, category: 'views', icon: Compass, badge: '實驗', run: showView('radar') },
      { id: 'action-radar-deck', title: '逐則篩選', subtitle: '一則一則決定探索找到的內容要不要留', category: 'actions', icon: GalleryHorizontalEnd, badge: '實驗', run: closeThen(() => (ui.showDeckModal = true)) },
      { id: 'action-radar', title: '探索設定', subtitle: '探索來源、排程與通知', category: 'actions', icon: SlidersHorizontal, badge: '實驗', run: closeThen(() => (ui.showRadarModal = true)) },
    )
  }
  if (experiments.flags.watch) {
    actions.push({ id: 'action-watch', title: '專案監看', subtitle: '本機專案與給它們的建議', category: 'actions', icon: Eye, badge: '實驗', run: closeThen(() => (ui.showWatchModal = true)) })
  }
  if (experiments.flags.daily) {
    actions.push({ id: 'action-daily-deck', title: '每日回顧', subtitle: '看過今天挑出來的未讀和舊收藏', category: 'actions', icon: Layers, badge: '實驗', run: closeThen(() => (ui.showDailyDeckModal = true)) })
  }
  return actions
})

const categoryActions = computed<PaletteAction[]>(() => {
  return itemsStore.categories
    .filter((c) => c.name !== 'Inbox' && (experiments.flags.watch || !WATCH_CATEGORIES.includes(c.name)))
    .map((c) => ({
      id: `cat-${c.id}`,
      title: `分類：${c.name}`,
      subtitle: `${c.item_count ?? 0} 則`,
      category: 'views' as const,
      icon: Tag,
      run: closeThen(() => {
        itemsStore.currentCategory = c.name
        void itemsStore.loadItems()
      }),
    }))
})

const itemActions = computed<PaletteAction[]>(() => {
  const q = searchQuery.value.trim().toLowerCase()
  if (!q) return []
  return itemsStore.items
    .filter(
      (item) =>
        item.title_l1?.toLowerCase().includes(q) ||
        item.summary_l1?.toLowerCase().includes(q) ||
        (item.tech_tags && item.tech_tags.some((t: string) => t.toLowerCase().includes(q))) ||
        item.url?.toLowerCase().includes(q),
    )
    .slice(0, 10)
    .map((item) => ({
      id: `item-${item.id}`,
      title: item.title_l1,
      subtitle: [cleanHost(item.url), item.summary_l1?.slice(0, 50)].filter(Boolean).join('・'),
      category: 'items' as const,
      icon: ExternalLink,
      badge: sourceMeta(item.source_type).label,
      run: () => {
        ui.activeItem = item
        ui.detailTab = 'analysis'
        ui.showCommandPalette = false
      },
    }))
})

const filteredEntries = computed<PaletteAction[]>(() => {
  const q = searchQuery.value.trim().toLowerCase()
  if (!q) {
    return [...staticActions.value, ...categoryActions.value]
  }
  const matchedActions = [...staticActions.value, ...categoryActions.value].filter(
    (a) =>
      a.title.toLowerCase().includes(q) ||
      (a.subtitle && a.subtitle.toLowerCase().includes(q)),
  )
  return [...matchedActions, ...itemActions.value]
})

watch(
  () => ui.showCommandPalette,
  (open) => {
    if (open) {
      searchQuery.value = ''
      selectedIndex.value = 0
      nextTick(() => {
        inputRef.value?.focus()
      })
    }
  },
)

watch(filteredEntries, () => {
  selectedIndex.value = 0
})

function handleKeyNavigation(e: KeyboardEvent) {
  if (filteredEntries.value.length === 0) return

  if (e.key === 'ArrowDown') {
    e.preventDefault()
    selectedIndex.value = (selectedIndex.value + 1) % filteredEntries.value.length
    scrollActiveIntoView()
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    selectedIndex.value =
      (selectedIndex.value - 1 + filteredEntries.value.length) % filteredEntries.value.length
    scrollActiveIntoView()
  } else if (e.key === 'Enter') {
    e.preventDefault()
    const current = filteredEntries.value[selectedIndex.value]
    if (current) current.run()
  }
}

function scrollActiveIntoView() {
  nextTick(() => {
    const activeEl = listRef.value?.querySelector('[data-selected="true"]')
    if (activeEl) {
      activeEl.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
    }
  })
}

function close() {
  ui.showCommandPalette = false
}
</script>

<template>
  <Teleport to="body">
    <div
      v-if="ui.showCommandPalette"
      class="fixed inset-0 z-50 flex items-start justify-center bg-black/60 p-4 pt-[12vh] backdrop-blur-md transition-opacity"
      role="dialog"
      aria-modal="true"
      aria-label="命令列"
      @click.self="close"
    >
      <div
        class="relative flex w-full max-w-xl flex-col overflow-hidden rounded-2xl border border-white/[0.12] bg-card/95 shadow-2xl backdrop-blur-2xl transition-all"
        @keydown="handleKeyNavigation"
      >
        <!-- Top Search Box -->
        <div class="flex items-center gap-3 border-b border-border/80 px-4 py-3.5">
          <Search class="size-4 shrink-0 text-muted-foreground" />
          <input
            ref="inputRef"
            v-model="searchQuery"
            type="text"
            placeholder="搜尋收藏，或輸入要做的事"
            class="min-w-0 flex-1 bg-transparent text-sm text-foreground placeholder:text-muted-foreground focus:outline-none"
            autocomplete="off"
            spellcheck="false"
          />
          <kbd
            class="rounded border border-border bg-muted/60 px-1.5 py-0.5 text-2xs font-mono text-muted-foreground cursor-pointer hover:bg-muted"
            title="關閉"
            @click="close"
          >
            ESC
          </kbd>
        </div>

        <!-- Filtered List -->
        <div
          ref="listRef"
          class="max-h-[60vh] min-h-[140px] overflow-y-auto p-2 text-sm select-none"
        >
          <div
            v-if="filteredEntries.length === 0"
            class="flex flex-col items-center justify-center py-10 text-center text-sm text-muted-foreground"
          >
            <p>找不到符合「{{ searchQuery }}」的收藏或動作。</p>
          </div>

          <button
            v-for="(item, idx) in filteredEntries"
            :key="item.id"
            type="button"
            :data-selected="idx === selectedIndex"
            class="group flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left transition-colors"
            :class="[
              idx === selectedIndex
                ? 'bg-primary/10 text-primary-soft-foreground shadow-sm ring-1 ring-primary/20'
                : 'text-foreground hover:bg-accent hover:text-foreground',
            ]"
            @click="item.run()"
            @mouseenter="selectedIndex = idx"
          >
            <component
              :is="item.icon"
              class="size-5 shrink-0 text-muted-foreground"
            />
            <div class="min-w-0 flex-1">
              <div class="flex items-center gap-2">
                <span class="truncate text-sm font-medium">{{ item.title }}</span>
                <span
                  v-if="item.badge"
                  class="rounded bg-muted px-1.5 py-0.5 text-2xs font-mono text-muted-foreground"
                >
                  {{ item.badge }}
                </span>
              </div>
              <p
                v-if="item.subtitle"
                class="truncate text-sm text-muted-foreground"
              >
                {{ item.subtitle }}
              </p>
            </div>
            <CornerDownLeft
              v-if="idx === selectedIndex"
              class="size-3.5 shrink-0 text-primary/60"
            />
          </button>
        </div>

        <!-- Helper Footer Bar -->
        <div
          class="flex items-center justify-between border-t border-border/80 bg-muted/40 px-4 py-2 text-2xs text-muted-foreground"
        >
          <div class="flex items-center gap-3">
            <span class="flex items-center gap-1">
              <kbd class="rounded border border-border bg-card px-1 py-0.2 font-mono">↑</kbd>
              <kbd class="rounded border border-border bg-card px-1 py-0.2 font-mono">↓</kbd>
              移動
            </span>
            <span class="flex items-center gap-1">
              <kbd class="rounded border border-border bg-card px-1.5 py-0.2 font-mono">↵</kbd>
              執行
            </span>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>
