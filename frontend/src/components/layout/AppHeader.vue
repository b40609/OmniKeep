<script setup lang="ts">
import { ref, computed } from 'vue'
import { useDebounceFn, onClickOutside } from '@vueuse/core'
import {
  Search, Download, Sun, Moon, List, LayoutGrid, Loader2,
  Sparkles, Palette, Check, PanelLeft, Plus,
} from 'lucide-vue-next'

import Button from '@/components/ui/button/Button.vue'
import { useUiStore } from '@/stores/ui'
import { useItemsStore } from '@/stores/items'
import { useTheme } from '@/composables/useTheme'
import { useMutations } from '@/composables/useMutations'

const ui = useUiStore()
const items = useItemsStore()
const { mode, accent, accents, set: setTheme, setAccent } = useTheme()
const showThemeMenu = ref(false)
const themeMenuRef = ref<HTMLDivElement | null>(null)
onClickOutside(themeMenuRef, () => {
  showThemeMenu.value = false
})

const { quickIngest } = useMutations()

const quickInput = ref<HTMLInputElement | null>(null)
const searchInput = ref<HTMLInputElement | null>(null)
const quickUrl = ref('')

defineExpose({ focusQuickInput, focusSearchInput })

function focusQuickInput() {
  quickInput.value?.focus()
}
function focusSearchInput() {
  searchInput.value?.focus()
}

async function submitQuick() {
  const content = quickUrl.value.trim()
  if (!content || ui.isIngesting) return
  await quickIngest(content)
  quickUrl.value = ''
}

const debouncedSearch = useDebounceFn(() => items.loadItems(), 250)

/* PWA install prompt */
const deferredPrompt = ref<unknown>(null)
window.addEventListener('beforeinstallprompt', (e: Event) => {
  e.preventDefault()
  deferredPrompt.value = e
})
async function installPWA() {
  const p = deferredPrompt.value as { prompt: () => Promise<void>; userChoice: Promise<{ outcome: string }> } | null
  if (!p) return
  await p.prompt()
  if ((await p.userChoice).outcome === 'accepted') deferredPrompt.value = null
}

const viewTitle = computed(() => {
  switch (items.triageView) {
    case 'inbox': return '收件匣'
    case 'starred': return '星標收藏'
    case 'archived': return '已封存'
    default: return '全部項目'
  }
})
</script>

<template>
  <header class="safe-top ios-blur z-30 flex h-14 shrink-0 items-center justify-between border-b border-hairline px-3 sm:px-4">
    <!-- Left: Sidebar toggle + Current Breadcrumb -->
    <div class="flex items-center gap-2.5 min-w-0">
      <!-- Desktop sidebar toggle (only visible when sidebar is collapsed) -->
      <button
        v-if="!ui.sidebarOpen"
        class="hidden md:flex size-8 items-center justify-center rounded-lg text-muted-foreground hover:bg-accent hover:text-foreground active:scale-95 transition cursor-pointer"
        title="展開側邊欄 (Cmd+B)"
        aria-label="展開側邊欄"
        @click="ui.sidebarOpen = true"
      >
        <PanelLeft class="size-4.5" />
      </button>

      <!-- Mobile drawer toggle -->
      <button
        class="flex md:hidden size-8 items-center justify-center rounded-lg text-muted-foreground hover:bg-accent hover:text-foreground active:scale-95 transition cursor-pointer"
        title="切換選單"
        aria-label="切換選單"
        @click="ui.sidebarMobileOpen = !ui.sidebarMobileOpen"
      >
        <PanelLeft class="size-4.5" />
      </button>

      <div class="flex items-center gap-1.5 text-xs font-semibold text-foreground truncate max-sm:hidden">
        <span class="text-subtle-foreground">OmniKeep</span>
        <span class="text-muted-foreground">/</span>
        <span>{{ viewTitle }}</span>
        <template v-if="items.currentCategory !== '全部'">
          <span class="text-muted-foreground">/</span>
          <span class="text-primary font-bold">{{ items.currentCategory }}</span>
        </template>
      </div>
    </div>

    <!-- Center: Quick Ingest Omnibox & Search -->
    <div class="flex flex-1 items-center justify-center max-w-2xl px-2 gap-2">
      <!-- Quick Ingest input (paste & press enter) -->
      <div class="relative flex-1 min-w-0 max-w-md">
        <input
          ref="quickInput"
          v-model="quickUrl"
          type="text"
          :disabled="ui.isIngesting"
          placeholder="擷取網址或建立筆記... (支援 Enter 快速擷取)"
          class="h-8.5 w-full rounded-full border border-border bg-input pl-3 pr-16 text-xs text-foreground shadow-2xs transition placeholder:text-subtle-foreground focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary/40 disabled:opacity-50"
          @keyup.enter="submitQuick"
        />
        <button
          class="absolute right-1 top-1/2 -translate-y-1/2 flex h-6.5 items-center gap-1 rounded-full bg-primary px-2.5 text-2xs font-semibold text-primary-foreground shadow-xs transition active:scale-95 disabled:opacity-40 cursor-pointer"
          :disabled="!quickUrl.trim() || ui.isIngesting"
          aria-label="擷取"
          @click="submitQuick"
        >
          <Loader2 v-if="ui.isIngesting" class="size-2.5 animate-spin" />
          <Plus v-else class="size-2.5" />
          <span>{{ ui.isIngesting ? '解析中' : '擷取' }}</span>
        </button>
      </div>

      <!-- Search Box with Semantic / Keyword switcher -->
      <div class="relative hidden sm:flex items-center w-52 shrink-0">
        <component
          :is="items.searchMode === 'semantic' ? Sparkles : Search"
          class="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 transition-colors"
          :class="items.searchMode === 'semantic' ? 'text-violet-500' : 'text-subtle-foreground'"
        />
        <input
          ref="searchInput"
          v-model="items.searchQuery"
          type="text"
          :placeholder="items.searchMode === 'semantic' ? '語意向量搜尋 (Semantic)...' : '搜尋關鍵字或 URL...'"
          class="h-8.5 w-full rounded-full border border-border bg-input pl-8 pr-14 text-xs text-foreground shadow-2xs transition placeholder:text-subtle-foreground focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary/40"
          :class="items.searchMode === 'semantic' ? 'border-violet-500/40 focus:ring-violet-500/30' : ''"
          @input="debouncedSearch"
        />
        <button
          type="button"
          class="absolute right-1 flex h-6 items-center gap-0.5 rounded-full px-1.5 text-2xs font-semibold transition active:scale-95 cursor-pointer"
          :class="items.searchMode === 'semantic'
            ? 'bg-violet-500 text-white shadow-2xs'
            : 'bg-muted text-muted-foreground hover:text-foreground'"
          :title="items.searchMode === 'semantic' ? '目前為語意搜尋，點擊切換為關鍵字搜尋' : '目前為關鍵字搜尋，點擊切換為語意搜尋'"
          @click="items.toggleSearchMode()"
        >
          <Sparkles v-if="items.searchMode === 'semantic'" class="size-2" />
          <span>{{ items.searchMode === 'semantic' ? '語意' : '關鍵字' }}</span>
        </button>
      </div>
    </div>

    <!-- Right Controls: View Switcher & Theme Palette -->
    <div class="flex items-center gap-1 shrink-0">
      <!-- Density switcher (segmented list/cards) -->
      <div class="flex items-center rounded-lg bg-muted/60 p-0.5">
        <button
          class="flex size-7 items-center justify-center rounded-md transition cursor-pointer"
          :class="items.viewMode === 'list' ? 'bg-background shadow-2xs text-foreground font-semibold' : 'text-muted-foreground hover:text-foreground'"
          title="切換為清單視圖"
          aria-label="清單視圖"
          @click="items.viewMode = 'list'"
        >
          <List class="size-3.5" />
        </button>
        <button
          class="flex size-7 items-center justify-center rounded-md transition cursor-pointer"
          :class="items.viewMode === 'cards' ? 'bg-background shadow-2xs text-foreground font-semibold' : 'text-muted-foreground hover:text-foreground'"
          title="切換為卡片視圖"
          aria-label="卡片視圖"
          @click="items.viewMode = 'cards'"
        >
          <LayoutGrid class="size-3.5" />
        </button>
      </div>

      <!-- Theme & Accent Palette Menu -->
      <div ref="themeMenuRef" class="relative">
        <Button
          variant="ghost"
          size="icon"
          title="外觀風格與輔色色票"
          aria-label="外觀設定"
          class="relative transition-colors cursor-pointer"
          :class="showThemeMenu ? 'bg-accent text-foreground' : ''"
          @click="showThemeMenu = !showThemeMenu"
        >
          <Palette class="size-4.5" />
          <span class="absolute top-1.5 right-1.5 size-2 rounded-full bg-primary ring-1 ring-background shadow-xs" />
        </Button>

        <!-- Dropdown Card -->
        <div
          v-if="showThemeMenu"
          class="absolute right-0 top-full mt-2 z-50 w-64 rounded-2xl border border-border bg-popover p-3.5 shadow-2xl text-foreground text-xs duration-200 animate-in fade-in-0 zoom-in-95"
        >
          <div class="mb-3 flex items-center justify-between border-b border-border/50 pb-2">
            <span class="font-semibold text-foreground">外觀與色彩</span>
            <span class="font-mono text-2xs text-muted-foreground uppercase">THEME</span>
          </div>

          <!-- Mode Selector -->
          <div class="mb-3 space-y-1.5">
            <span class="text-2xs text-subtle-foreground font-medium">主題模式</span>
            <div class="grid grid-cols-2 gap-1.5 rounded-lg bg-muted/60 p-1">
              <button
                type="button"
                class="flex items-center justify-center gap-1.5 rounded-md px-2 py-1.5 font-medium transition cursor-pointer"
                :class="mode === 'dark' ? 'bg-background shadow-xs text-foreground font-semibold' : 'text-muted-foreground hover:text-foreground'"
                @click="setTheme('dark')"
              >
                <Moon class="size-3.5" />
                <span>深色</span>
              </button>
              <button
                type="button"
                class="flex items-center justify-center gap-1.5 rounded-md px-2 py-1.5 font-medium transition cursor-pointer"
                :class="mode === 'oled' ? 'bg-black text-white shadow-xs ring-1 ring-white/20 font-semibold' : 'text-muted-foreground hover:text-foreground'"
                @click="setTheme('oled')"
              >
                <span class="size-2 rounded-full bg-white" />
                <span>OLED 純黑</span>
              </button>
              <button
                type="button"
                class="flex items-center justify-center gap-1.5 rounded-md px-2 py-1.5 font-medium transition cursor-pointer"
                :class="mode === 'light' ? 'bg-background shadow-xs text-foreground font-semibold' : 'text-muted-foreground hover:text-foreground'"
                @click="setTheme('light')"
              >
                <Sun class="size-3.5" />
                <span>淺色</span>
              </button>
              <button
                type="button"
                class="flex items-center justify-center gap-1.5 rounded-md px-2 py-1.5 font-medium transition cursor-pointer"
                :class="mode === 'system' ? 'bg-background shadow-xs text-foreground font-semibold' : 'text-muted-foreground hover:text-foreground'"
                @click="setTheme('system')"
              >
                <span class="text-2xs font-mono">SYS</span>
                <span>跟隨系統</span>
              </button>
            </div>
          </div>

          <!-- Accent Color Swatches -->
          <div class="space-y-1.5">
            <div class="flex items-center justify-between">
              <span class="text-2xs text-subtle-foreground font-medium">輔色色票</span>
              <span class="text-2xs font-mono text-primary font-semibold">
                {{ accents.find(a => a.id === accent)?.label }}
              </span>
            </div>
            <div class="grid grid-cols-6 gap-1.5 pt-0.5">
              <button
                v-for="opt in accents"
                :key="opt.id"
                type="button"
                :title="opt.label"
                :aria-label="opt.label"
                class="group relative flex size-8 items-center justify-center rounded-full transition-transform active:scale-90 cursor-pointer"
                :style="{ backgroundColor: opt.color }"
                @click="setAccent(opt.id)"
              >
                <Check
                  v-if="accent === opt.id"
                  class="size-4 text-white drop-shadow-sm"
                />
                <span
                  v-if="accent === opt.id"
                  class="absolute inset-0 rounded-full ring-2 ring-primary ring-offset-2 ring-offset-background"
                />
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- PWA Install Button -->
      <Button v-if="deferredPrompt" variant="secondary" size="sm" class="ml-1" @click="installPWA">
        <Download class="size-3.5" />
        <span class="max-lg:hidden">安裝</span>
      </Button>
    </div>
  </header>
</template>
