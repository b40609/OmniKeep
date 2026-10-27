<script setup lang="ts">
import { computed } from 'vue'
import {
  BrainCircuit, PanelLeftClose, Plus, FileText,
  Inbox, Star, Archive, Layers, Radar, ScanEye,
  FolderInput, KeyRound, Keyboard, LogOut, Tag,
} from 'lucide-vue-next'
import { useItemsStore, type TriageView } from '@/stores/items'
import { useUiStore } from '@/stores/ui'
import { useRadarStore } from '@/stores/radar'

const emit = defineEmits<{ (e: 'logout'): void }>()

const items = useItemsStore()
const ui = useUiStore()
const radar = useRadarStore()

const views = computed(() => [
  { id: 'inbox' as TriageView, label: '收件匣', icon: Inbox, count: items.stats.inbox },
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
    class="fixed inset-0 z-40 bg-black/60 backdrop-blur-xs md:hidden"
    @click="ui.sidebarMobileOpen = false"
  />

  <aside
    class="safe-top z-40 flex h-full shrink-0 flex-col border-r border-hairline bg-card/95 backdrop-blur-2xl transition-all duration-300 max-md:fixed max-md:inset-y-0 max-md:left-0 max-md:shadow-2xl"
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
          <p class="text-2xs text-muted-foreground/70 font-medium">Knowledge Base • v2.4</p>
        </div>
      </div>
      <button
        class="rounded-lg p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground active:scale-95 transition cursor-pointer"
        title="收合側邊欄 (Cmd+B)"
        @click="ui.sidebarOpen = false; ui.sidebarMobileOpen = false"
      >
        <PanelLeftClose class="size-4" />
      </button>
    </div>

    <!-- Quick Action: New Note -->
    <div class="p-3">
      <button
        class="flex w-full items-center justify-center gap-2 rounded-xl bg-primary py-2 px-3 text-xs font-semibold text-primary-foreground shadow-sm transition hover:opacity-95 active:scale-[0.98] cursor-pointer"
        @click="ui.showNoteModal = true"
      >
        <FileText class="size-3.5" />
        <span>新增筆記</span>
        <kbd class="ml-auto rounded-md bg-black/15 px-1.5 py-0.5 font-mono text-3xs opacity-80">Shift+N</kbd>
      </button>
    </div>

    <!-- Scrollable Navigation Area -->
    <div class="flex-1 space-y-5 overflow-y-auto px-3 py-1 text-xs [&::-webkit-scrollbar]:w-1.5">
      <!-- 1. Triage Views -->
      <div>
        <p class="mb-1.5 px-2 text-2xs font-semibold uppercase tracking-wider text-muted-foreground/75">
          情報狀態
        </p>
        <div class="space-y-0.5">
          <button
            v-for="v in views"
            :key="v.id"
            class="group flex w-full items-center justify-between rounded-lg px-2.5 py-1.5 font-medium transition cursor-pointer"
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
        <p class="mb-1.5 px-2 text-2xs font-semibold uppercase tracking-wider text-muted-foreground/75">
          情報引擎
        </p>
        <div class="space-y-0.5">
          <button
            class="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 font-medium text-muted-foreground hover:bg-accent/60 hover:text-foreground transition cursor-pointer"
            @click="ui.showRadarModal = true; radar.ensureLoaded()"
          >
            <Radar class="size-4 text-violet-500" />
            <span>訂閱雷達排程</span>
            <kbd class="ml-auto font-mono text-3xs text-subtle-foreground">R</kbd>
          </button>
          <button
            class="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 font-medium text-muted-foreground hover:bg-accent/60 hover:text-foreground transition cursor-pointer"
            @click="ui.showWatchModal = true"
          >
            <ScanEye class="size-4 text-emerald-500" />
            <span>本地專案監控</span>
          </button>
        </div>
      </div>

      <!-- 3. Category Taxonomy -->
      <div>
        <div class="mb-1.5 flex items-center justify-between px-2">
          <p class="text-2xs font-semibold uppercase tracking-wider text-muted-foreground/75">
            分類目錄
          </p>
          <button
            class="rounded p-0.5 text-subtle-foreground hover:bg-accent hover:text-foreground transition cursor-pointer"
            title="新增分類"
            @click="ui.showCategoryModal = true"
          >
            <Plus class="size-3.5" />
          </button>
        </div>
        <div class="space-y-0.5">
          <button
            class="flex w-full items-center justify-between rounded-lg px-2.5 py-1.5 font-medium transition cursor-pointer"
            :class="items.currentCategory === '全部'
              ? 'bg-accent text-foreground font-semibold'
              : 'text-muted-foreground hover:bg-accent/60 hover:text-foreground'"
            @click="selectCategory('全部')"
          >
            <div class="flex items-center gap-2.5">
              <span class="size-1.5 rounded-full bg-primary" />
              <span>全部分類</span>
            </div>
            <span class="text-2xs tabular-nums text-muted-foreground/70">{{ items.stats.total }}</span>
          </button>
          <button
            v-for="cat in items.categories"
            :key="cat.id"
            class="flex w-full items-center justify-between rounded-lg px-2.5 py-1.5 font-medium transition cursor-pointer"
            :class="items.currentCategory === cat.name
              ? 'bg-accent text-foreground font-semibold'
              : 'text-muted-foreground hover:bg-accent/60 hover:text-foreground'"
            @click="selectCategory(cat.name)"
          >
            <div class="flex items-center gap-2.5 min-w-0">
              <Tag class="size-3.5 shrink-0 text-subtle-foreground" />
              <span class="truncate">{{ cat.name }}</span>
            </div>
            <span class="shrink-0 text-2xs tabular-nums text-muted-foreground/70">{{ cat.item_count ?? 0 }}</span>
          </button>
        </div>
      </div>
    </div>

    <!-- Bottom Utility Row -->
    <div class="shrink-0 border-t border-hairline p-2 text-xs">
      <div class="grid grid-cols-4 gap-1">
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
