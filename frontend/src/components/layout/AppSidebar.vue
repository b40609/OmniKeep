<script setup lang="ts">
import { computed } from 'vue'
import { useMediaQuery } from '@vueuse/core'
import {
  BrainCircuit, PanelLeftClose, Plus, FileText,
  Inbox, Star, Archive, Layers, Radar, ScanEye, GalleryHorizontalEnd,
  FolderInput, KeyRound, Keyboard, LogOut, Tag, Bell, Settings,
  Radio, Sparkles, Bot,
} from 'lucide-vue-next'
import { useItemsStore, type TriageView } from '@/stores/items'
import { useUiStore } from '@/stores/ui'
import { useRadarStore } from '@/stores/radar'

const emit = defineEmits<{ (e: 'logout'): void }>()

const items = useItemsStore()
const ui = useUiStore()
const radar = useRadarStore()
const appVersion = __APP_VERSION__
const desktop = useMediaQuery('(min-width: 768px)')

const views = computed(() => [
  { id: 'inbox' as TriageView, label: '收件匣', icon: Inbox, count: items.stats.inbox },
  { id: 'radar' as TriageView, label: '雷達發現匣', icon: Radio, count: items.stats.radar },
  { id: 'starred' as TriageView, label: '星標收藏', icon: Star, count: items.stats.starred },
  { id: 'archived' as TriageView, label: '已封存', icon: Archive, count: items.stats.archived },
  { id: 'all' as TriageView, label: '全部項目', icon: Layers, count: items.stats.total },
])

function setView(v: TriageView) {
  items.triageView = v
  items.loadItems()
  ui.sidebarMobileOpen = false
}

function selectCategory(catName: string) {
  items.currentCategory = catName
  items.loadItems()
  ui.sidebarMobileOpen = false
}
</script>

<template>
  <!-- Mobile backdrop -->
  <div
    v-if="ui.sidebarMobileOpen"
    class="fixed inset-0 z-40 bg-black/60 md:hidden"
    @click="ui.sidebarMobileOpen = false"
  />

  <aside
    class="safe-top z-40 flex h-full shrink-0 flex-col border-r border-hairline bg-card transition-[width,transform] duration-200 motion-reduce:transition-none max-md:fixed max-md:inset-y-0 max-md:left-0 max-md:shadow-2xl"
    :inert="desktop ? !ui.sidebarOpen : !ui.sidebarMobileOpen"
    aria-label="主選單"
    :class="[
      ui.sidebarOpen ? 'w-64' : 'w-0 border-r-0 overflow-hidden md:w-0',
      ui.sidebarMobileOpen ? 'max-md:w-72 max-md:translate-x-0' : 'max-md:-translate-x-full',
    ]"
  >
    <!-- Brand & Workspace Header -->
    <div class="flex h-14 shrink-0 items-center justify-between border-b border-hairline px-4">
      <div class="flex items-center gap-2.5 min-w-0">
        <div class="flex size-8 shrink-0 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-sm">
          <BrainCircuit class="size-4.5" />
        </div>
        <div class="min-w-0 leading-tight">
          <p class="truncate text-sm font-bold tracking-tight text-foreground">OmniKeep</p>
          <p class="text-2xs text-muted-foreground font-medium">收藏與閱讀 • v{{ appVersion }}</p>
        </div>
      </div>
      <button
        class="item-action"
        title="收合側邊欄（Ctrl/Cmd+B）"
        aria-label="收合側邊欄"
        @click="ui.sidebarOpen = false; ui.sidebarMobileOpen = false"
      >
        <PanelLeftClose class="size-4" />
      </button>
    </div>

    <!-- Quick Action: Brain & Deck & New Note -->
    <div class="space-y-1.5 p-3">
      <button
        class="flex min-h-10 w-full items-center justify-center gap-2 rounded-lg bg-primary px-3 text-xs font-semibold text-primary-foreground shadow-sm transition-colors hover:bg-primary-hover cursor-pointer"
        @click="ui.showBrainModal = true"
      >
        <Bot class="size-3.5" />
        <span>對話大腦 (Ask Brain)</span>
        <kbd class="ml-auto font-mono text-3xs opacity-80">B</kbd>
      </button>

      <button
        class="flex min-h-9 w-full items-center justify-center gap-2 rounded-lg border border-primary/30 bg-primary/5 px-3 text-xs font-medium text-primary transition-colors hover:bg-primary/10 cursor-pointer"
        @click="ui.showDailyDeckModal = true"
      >
        <Sparkles class="size-3.5 text-amber-500" />
        <span>每日回顧 Deck</span>
        <kbd class="ml-auto font-mono text-3xs text-muted-foreground">Shift+D</kbd>
      </button>

      <button
        class="flex min-h-9 w-full items-center justify-center gap-2 rounded-lg border border-border bg-card px-3 text-xs font-medium text-foreground transition-colors hover:bg-accent cursor-pointer"
        @click="ui.showNoteModal = true"
      >
        <FileText class="size-3.5 text-muted-foreground" />
        <span>新增筆記</span>
        <kbd class="ml-auto font-mono text-3xs text-muted-foreground">Shift+N</kbd>
      </button>
    </div>

    <!-- Scrollable Navigation Area -->
    <div class="flex-1 space-y-5 overflow-y-auto px-3 py-1 text-xs [&::-webkit-scrollbar]:w-1.5">
      <!-- 1. Triage Views -->
      <div>
        <p class="mb-1.5 px-2 text-xs font-medium text-muted-foreground">
          收藏狀態
        </p>
        <div class="space-y-0.5">
          <button
            v-for="v in views"
            :key="v.id"
            class="group flex min-h-11 w-full items-center justify-between rounded-lg px-2.5 font-medium transition-colors cursor-pointer"
            :aria-pressed="items.triageView === v.id"
            :class="items.triageView === v.id
              ? 'bg-primary-soft text-primary-soft-foreground font-semibold'
              : 'text-muted-foreground hover:bg-accent/60 hover:text-foreground'"
            @click="setView(v.id)"
          >
            <div class="flex items-center gap-2.5">
              <component
                :is="v.icon"
                class="size-4 transition-colors"
                :class="items.triageView === v.id ? 'text-primary' : 'text-subtle-foreground group-hover:text-foreground'"
              />
              <span>{{ v.label }}</span>
            </div>
            <span
              class="rounded-full px-2 py-0.5 text-2xs font-semibold tabular-nums"
              :class="items.triageView === v.id ? 'bg-primary text-primary-foreground' : 'bg-muted text-subtle-foreground'"
            >
              {{ v.count }}
            </span>
          </button>
        </div>
      </div>

      <!-- 2. Intelligence & Surveillance -->
      <div>
        <p class="mb-1.5 px-2 text-xs font-medium text-muted-foreground">
          自動收錄
        </p>
        <div class="space-y-0.5">
          <button
            class="flex min-h-11 w-full items-center gap-2.5 rounded-lg px-2.5 font-medium text-muted-foreground hover:bg-accent hover:text-foreground transition-colors cursor-pointer"
            @click="ui.showRadarModal = true; radar.ensureLoaded()"
          >
            <Radar class="size-4" />
            <span>訂閱雷達排程</span>
            <kbd class="ml-auto font-mono text-3xs text-subtle-foreground">R</kbd>
          </button>
          <button
            class="flex min-h-11 w-full items-center gap-2.5 rounded-lg px-2.5 font-medium text-muted-foreground hover:bg-accent hover:text-foreground transition-colors cursor-pointer"
            @click="ui.showDeckModal = true; ui.sidebarMobileOpen = false"
          >
            <GalleryHorizontalEnd class="size-4" />
            <span>雷達滑卡</span>
            <kbd class="ml-auto font-mono text-3xs text-subtle-foreground">D</kbd>
          </button>
          <button
            class="flex min-h-11 w-full items-center gap-2.5 rounded-lg px-2.5 font-medium text-muted-foreground hover:bg-accent hover:text-foreground transition-colors cursor-pointer"
            @click="ui.showWatchModal = true"
          >
            <ScanEye class="size-4" />
            <span>本地專案監控</span>
          </button>
        </div>
      </div>

      <!-- 3. Category Taxonomy -->
      <div>
        <div class="mb-1.5 flex items-center justify-between px-2">
          <p class="text-xs font-medium text-muted-foreground">
            分類目錄
          </p>
          <button
            class="item-action"
            aria-label="新增分類"
            title="新增分類"
            @click="ui.showCategoryModal = true"
          >
            <Plus class="size-3.5" />
          </button>
        </div>
        <div class="space-y-0.5">
          <button
            class="flex min-h-11 w-full items-center justify-between rounded-lg px-2.5 font-medium transition-colors cursor-pointer"
            :aria-pressed="items.currentCategory === '全部'"
            :class="items.currentCategory === '全部'
              ? 'bg-accent text-foreground font-semibold'
              : 'text-muted-foreground hover:bg-accent/60 hover:text-foreground'"
            @click="selectCategory('全部')"
          >
            <div class="flex items-center gap-2.5">
              <span class="size-1.5 rounded-full bg-primary" />
              <span>全部分類</span>
            </div>
            <span class="text-xs tabular-nums text-muted-foreground">{{ items.stats.total }}</span>
          </button>
          <button
            v-for="cat in items.categories"
            :key="cat.id"
            class="flex min-h-11 w-full items-center justify-between rounded-lg px-2.5 font-medium transition-colors cursor-pointer"
            :aria-pressed="items.currentCategory === cat.name"
            :class="items.currentCategory === cat.name
              ? 'bg-accent text-foreground font-semibold'
              : 'text-muted-foreground hover:bg-accent/60 hover:text-foreground'"
            @click="selectCategory(cat.name)"
          >
            <div class="flex items-center gap-2.5 min-w-0">
              <Tag class="size-3.5 shrink-0 text-subtle-foreground" />
              <span class="truncate">{{ cat.name === 'Inbox' ? '收件匣' : cat.name }}</span>
            </div>
            <span class="shrink-0 text-xs tabular-nums text-muted-foreground">{{ cat.item_count ?? 0 }}</span>
          </button>
        </div>
      </div>
    </div>

    <!-- Bottom Utility Row -->
    <div class="shrink-0 border-t border-hairline p-2 text-xs">
      <div class="grid grid-cols-3 gap-1">
        <button
          class="flex flex-col items-center justify-center gap-1 rounded-lg py-2 text-muted-foreground hover:bg-accent hover:text-foreground transition cursor-pointer"
          title="AI 服務商、Bot 與備份設定"
          @click="ui.openSettings()"
        >
          <Settings class="size-4" />
          <span class="text-2xs font-medium">設定</span>
        </button>
        <button
          class="flex flex-col items-center justify-center gap-1 rounded-lg py-2 text-muted-foreground hover:bg-accent hover:text-foreground transition cursor-pointer"
          title="匯入書籤 (I)"
          @click="ui.showImportModal = true"
        >
          <FolderInput class="size-4" />
          <span class="text-2xs font-medium">匯入</span>
        </button>
        <button
          class="flex flex-col items-center justify-center gap-1 rounded-lg py-2 text-muted-foreground hover:bg-accent hover:text-foreground transition cursor-pointer"
          title="社群會話連結"
          @click="ui.showSessionModal = true"
        >
          <KeyRound class="size-4" />
          <span class="text-2xs font-medium">會話</span>
        </button>
        <button
          class="flex flex-col items-center justify-center gap-1 rounded-lg py-2 text-muted-foreground hover:bg-accent hover:text-foreground transition cursor-pointer"
          title="鍵盤快捷鍵指南 (?)"
          @click="ui.showShortcutsModal = true"
        >
          <Keyboard class="size-4" />
          <span class="text-2xs font-medium">鍵盤</span>
        </button>
        <button
          class="flex flex-col items-center justify-center gap-1 rounded-lg py-2 text-muted-foreground hover:bg-accent hover:text-foreground transition cursor-pointer"
          title="這台裝置的推播通知"
          @click="ui.showPushModal = true; ui.sidebarMobileOpen = false"
        >
          <Bell class="size-4" />
          <span class="text-2xs font-medium">通知</span>
        </button>
        <button
          class="flex flex-col items-center justify-center gap-1 rounded-lg py-2 text-muted-foreground hover:bg-red-500/10 hover:text-red-500 transition cursor-pointer"
          title="登出 OmniKeep"
          @click="emit('logout')"
        >
          <LogOut class="size-4" />
          <span class="text-2xs font-medium">登出</span>
        </button>
      </div>
    </div>
  </aside>
</template>
