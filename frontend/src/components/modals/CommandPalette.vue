<script setup lang="ts">
import { ref, computed, watch, nextTick } from 'vue'
import {
  Search,
  Sparkles,
  Inbox,
  Star,
  Archive,
  Radio,
  FilePlus,
  Layers,
  Upload,
  Eye,
  Settings,
  SunMoon,
  ExternalLink,
  Tag,
  CornerDownLeft,
  GalleryHorizontalEnd,
  Bell,
} from 'lucide-vue-next'
import { useUiStore } from '@/stores/ui'
import { useItemsStore } from '@/stores/items'
import { useTheme } from '@/composables/useTheme'
import { cleanHost, sourceMeta } from '@/lib/format'

const ui = useUiStore()
const itemsStore = useItemsStore()
const { mode, toggle: toggleTheme } = useTheme()

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
  iconColor?: string
  badge?: string
  run: () => void
}

const staticActions = computed<PaletteAction[]>(() => [
  {
    id: 'action-brain',
    title: '跨篇 AI 架構綜述 (Brain Synthesis)',
    subtitle: '彙總近期高價值技術情報生成宏觀分析',
    category: 'actions',
    icon: Sparkles,
    iconColor: 'text-violet-400',
    run: () => {
      ui.showCommandPalette = false
      ui.showBrainModal = true
    },
  },
  {
    id: 'action-daily-deck',
    title: '今日推薦卡片 (Daily Deck)',
    subtitle: '滑卡回顧待讀與值得重溫的舊收藏',
    category: 'actions',
    icon: Layers,
    iconColor: 'text-amber-400',
    run: () => {
      ui.showCommandPalette = false
      ui.showDailyDeckModal = true
    },
  },
  {
    id: 'action-radar-deck',
    title: '雷達滑卡 (Radar Deck)',
    subtitle: '逐張判定雷達候選情報：想看、略過、收藏、稍後',
    category: 'actions',
    icon: GalleryHorizontalEnd,
    iconColor: 'text-amber-400',
    run: () => {
      ui.showCommandPalette = false
      ui.showDeckModal = true
    },
  },
  {
    id: 'action-settings',
    title: '設定 (Settings)',
    subtitle: 'AI 服務商金鑰、Ask Brain、Telegram／LINE、備份',
    category: 'actions',
    icon: Settings,
    iconColor: 'text-slate-400',
    run: () => {
      ui.showCommandPalette = false
      ui.openSettings()
    },
  },
  {
    id: 'action-push',
    title: '推播通知設定 (Web Push)',
    subtitle: '這台裝置的通知與 Telegram 配對',
    category: 'actions',
    icon: Bell,
    iconColor: 'text-sky-400',
    run: () => {
      ui.showCommandPalette = false
      ui.showPushModal = true
    },
  },
  {
    id: 'action-new-note',
    title: '新增文字速記 (Quick Note)',
    subtitle: '建立快速手寫卡片',
    category: 'actions',
    icon: FilePlus,
    iconColor: 'text-emerald-400',
    run: () => {
      ui.showCommandPalette = false
      ui.showNoteModal = true
    },
  },
  {
    id: 'action-import',
    title: '匯入瀏覽器書籤 (Import HTML)',
    subtitle: '批量匯入 Chrome / Safari / Edge 書籤',
    category: 'actions',
    icon: Upload,
    iconColor: 'text-sky-400',
    run: () => {
      ui.showCommandPalette = false
      ui.showImportModal = true
    },
  },
  {
    id: 'action-watch',
    title: '檔案與目錄監看中心 (Watch Center)',
    subtitle: '檢視本機專案與提案卡片',
    category: 'actions',
    icon: Eye,
    iconColor: 'text-indigo-400',
    run: () => {
      ui.showCommandPalette = false
      ui.showWatchModal = true
    },
  },
  {
    id: 'action-radar',
    title: '雷達訂閱與巡檢設定 (Radar Settings)',
    subtitle: '管理 GitHub Trending、RSS 與 YouTube 訂閱源',
    category: 'actions',
    icon: Settings,
    iconColor: 'text-zinc-400',
    run: () => {
      ui.showCommandPalette = false
      ui.showRadarModal = true
    },
  },
  {
    id: 'action-theme',
    title: `切換外觀主題（目前：${mode.value}）`,
    subtitle: '在 Dark、OLED 與 Light 之間循環切換',
    category: 'actions',
    icon: SunMoon,
    iconColor: 'text-pink-400',
    run: () => {
      toggleTheme()
    },
  },
  // Quick Views
  {
    id: 'view-inbox',
    title: '收件匣 (Inbox)',
    subtitle: `${itemsStore.stats.inbox} 則待消化`,
    category: 'views',
    icon: Inbox,
    iconColor: 'text-blue-400',
    run: () => {
      itemsStore.triageView = 'inbox'
      itemsStore.currentCategory = '全部'
      void itemsStore.loadItems()
      ui.showCommandPalette = false
    },
  },
  {
    id: 'view-starred',
    title: '精選星標 (Starred)',
    subtitle: `${itemsStore.stats.starred} 則收藏`,
    category: 'views',
    icon: Star,
    iconColor: 'text-amber-400',
    run: () => {
      itemsStore.triageView = 'starred'
      itemsStore.currentCategory = '全部'
      void itemsStore.loadItems()
      ui.showCommandPalette = false
    },
  },
  {
    id: 'view-radar',
    title: '雷達自動捕獲 (Radar Items)',
    subtitle: `${itemsStore.stats.radar || 0} 則雷達捕獲`,
    category: 'views',
    icon: Radio,
    iconColor: 'text-emerald-400',
    run: () => {
      itemsStore.triageView = 'radar'
      itemsStore.currentCategory = '全部'
      void itemsStore.loadItems()
      ui.showCommandPalette = false
    },
  },
  {
    id: 'view-archived',
    title: '已讀封存庫 (Archived)',
    subtitle: `${itemsStore.stats.archived} 則已封存紀錄`,
    category: 'views',
    icon: Archive,
    iconColor: 'text-zinc-400',
    run: () => {
      itemsStore.triageView = 'archived'
      itemsStore.currentCategory = '全部'
      void itemsStore.loadItems()
      ui.showCommandPalette = false
    },
  },
])

const categoryActions = computed<PaletteAction[]>(() => {
  return itemsStore.categories
    .filter((c) => c.name !== 'Inbox')
    .map((c) => ({
      id: `cat-${c.id}`,
      title: `分類：${c.name}`,
      subtitle: `篩選 ${c.name} 分類下的所有技術情報`,
      category: 'views' as const,
      icon: Tag,
      iconColor: 'text-indigo-400',
      run: () => {
        itemsStore.currentCategory = c.name
        void itemsStore.loadItems()
        ui.showCommandPalette = false
      },
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
      subtitle: `${cleanHost(item.url)} · ${item.summary_l1?.slice(0, 50) || ''}...`,
      category: 'items' as const,
      icon: ExternalLink,
      iconColor: 'text-muted-foreground',
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
      aria-label="全域命令列"
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
            placeholder="搜尋情報、標籤、過濾或執行指令 (Cmd+K)..."
            class="min-w-0 flex-1 bg-transparent text-sm text-foreground placeholder:text-muted-foreground focus:outline-none"
            autocomplete="off"
            spellcheck="false"
          />
          <kbd
            class="rounded border border-border bg-muted/60 px-1.5 py-0.5 text-2xs font-mono text-muted-foreground cursor-pointer hover:bg-muted"
            title="關閉面板"
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
            class="flex flex-col items-center justify-center py-10 text-center text-xs text-muted-foreground"
          >
            <p>找不到符合「{{ searchQuery }}」的動作或情報</p>
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
              class="size-4 shrink-0 transition-transform group-hover:scale-110"
              :class="item.iconColor || 'text-muted-foreground'"
            />
            <div class="min-w-0 flex-1">
              <div class="flex items-center gap-2">
                <span class="truncate font-medium text-xs sm:text-sm">{{ item.title }}</span>
                <span
                  v-if="item.badge"
                  class="rounded bg-muted px-1.5 py-0.5 text-2xs font-mono text-muted-foreground"
                >
                  {{ item.badge }}
                </span>
              </div>
              <p
                v-if="item.subtitle"
                class="truncate text-2xs text-muted-foreground"
                :class="idx === selectedIndex ? 'text-primary/70' : ''"
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
              導航
            </span>
            <span class="flex items-center gap-1">
              <kbd class="rounded border border-border bg-card px-1.5 py-0.2 font-mono">↵</kbd>
              執行
            </span>
          </div>
          <span class="text-subtle-foreground">OmniKeep Command Palette</span>
        </div>
      </div>
    </div>
  </Teleport>
</template>
