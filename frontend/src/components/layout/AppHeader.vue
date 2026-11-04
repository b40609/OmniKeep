<script setup lang="ts">
import { ref, computed, nextTick, onUnmounted } from 'vue'
import { useDebounceFn, onClickOutside } from '@vueuse/core'
import {
  Search, Download, Sun, Moon, List, LayoutGrid, Loader2,
  Palette, Check, PanelLeft, Plus, Sparkles, Bot,
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
const quickError = ref('')
const showMobileSearch = ref(false)
const submitting = ref(false)

defineExpose({ focusQuickInput, focusSearchInput })

function focusQuickInput() {
  quickInput.value?.focus()
}
async function focusSearchInput() {
  showMobileSearch.value = true
  await nextTick()
  searchInput.value?.focus()
}

async function submitQuick() {
  const content = quickUrl.value.trim()
  if (!content || ui.isIngesting || submitting.value) return
  submitting.value = true
  quickError.value = ''
  try {
    if (await quickIngest(content)) {
      quickUrl.value = ''
    } else {
      quickError.value = '收錄失敗，內容已保留。請確認連線後重試。'
    }
  } catch {
    quickError.value = '收錄失敗，內容已保留。請稍後重試。'
  } finally {
    submitting.value = false
  }
}

const debouncedSearch = useDebounceFn(() => items.loadItems(), 250)

/* PWA install prompt */
const deferredPrompt = ref<unknown>(null)
function onInstallPrompt(e: Event) {
  e.preventDefault()
  deferredPrompt.value = e
}
window.addEventListener('beforeinstallprompt', onInstallPrompt)
onUnmounted(() => window.removeEventListener('beforeinstallprompt', onInstallPrompt))
async function installPWA() {
  const p = deferredPrompt.value as { prompt: () => Promise<void>; userChoice: Promise<{ outcome: string }> } | null
  if (!p) return
  await p.prompt()
  if ((await p.userChoice).outcome === 'accepted') deferredPrompt.value = null
}

const viewTitle = computed(() => {
  switch (items.triageView) {
    case 'inbox': return '收件匣'
    case 'radar': return '雷達發現匣'
    case 'starred': return '星標收藏'
    case 'archived': return '已封存'
    default: return '全部項目'
  }
})
</script>

<template>
  <header class="safe-top z-30 shrink-0 border-b border-hairline bg-card px-3 py-2 sm:px-4">
    <div class="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-x-2 gap-y-1 lg:grid-cols-[auto_minmax(10rem,1fr)_minmax(14rem,20rem)_auto]">
      <div class="flex items-center">
        <button class="item-action md:hidden" aria-label="切換選單" :aria-expanded="ui.sidebarMobileOpen" @click="ui.sidebarMobileOpen = !ui.sidebarMobileOpen"><PanelLeft class="size-5" /></button>
        <button v-if="!ui.sidebarOpen" class="item-action hidden md:flex" title="展開側邊欄（Ctrl/Cmd+B）" aria-label="展開側邊欄" @click="ui.sidebarOpen = true"><PanelLeft class="size-5" /></button>
        <span class="hidden text-sm font-semibold lg:block lg:pr-3">{{ viewTitle }}</span>
      </div>
      <form class="flex min-w-0 items-center rounded-lg border border-border bg-input" :aria-busy="ui.isIngesting || submitting" @submit.prevent="submitQuick">
        <input ref="quickInput" v-model="quickUrl" type="text" aria-label="收錄網址或筆記" :aria-invalid="!!quickError" :aria-describedby="quickError ? 'quick-ingest-error' : undefined"
          :disabled="ui.isIngesting || submitting" placeholder="貼上網址或筆記"
          class="h-11 min-w-0 flex-1 rounded-l-lg bg-transparent px-3 text-base text-foreground placeholder:text-subtle-foreground focus:outline-none lg:text-sm" @input="quickError = ''" />
        <button class="flex min-h-11 shrink-0 items-center justify-center gap-1 rounded-r-lg bg-primary px-3 text-sm font-medium text-primary-foreground disabled:opacity-50"
          :disabled="!quickUrl.trim() || ui.isIngesting || submitting" type="submit">
          <Loader2 v-if="ui.isIngesting || submitting" class="size-4 animate-spin" />
          <Plus v-else class="size-4" />
          <span>{{ ui.isIngesting || submitting ? '收錄中' : '收錄' }}</span>
        </button>
      </form>
      <button class="item-action lg:hidden" aria-label="展開或收合搜尋" :aria-expanded="showMobileSearch" aria-controls="collection-search" @click="showMobileSearch ? showMobileSearch = false : focusSearchInput()"><Search class="size-5" /></button>
      <div id="collection-search" class="order-4 col-span-3 min-w-0 items-center gap-1 rounded-lg border border-border bg-input lg:order-none lg:col-span-1" :class="showMobileSearch ? 'flex' : 'hidden lg:flex'">
        <Search class="ml-3 size-4 shrink-0 text-subtle-foreground" aria-hidden="true" />
        <input ref="searchInput" v-model="items.searchQuery" type="search" aria-label="搜尋收藏"
          :placeholder="items.searchMode === 'semantic' ? '依意思搜尋' : '搜尋關鍵字或網址'"
          class="h-11 min-w-0 flex-1 bg-transparent px-1 text-base placeholder:text-subtle-foreground lg:text-sm" @input="debouncedSearch" />
        <button type="button" class="m-1 min-h-9 shrink-0 rounded-md px-2 text-xs font-medium"
          :class="items.searchMode === 'semantic' ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground'"
          aria-label="依意思搜尋" :aria-pressed="items.searchMode === 'semantic'" @click="items.toggleSearchMode()">{{ items.searchMode === 'semantic' ? '依意思' : '關鍵字' }}</button>
        <button
          type="button"
          class="mr-1.5 hidden items-center gap-1 rounded border border-border/80 bg-muted/40 px-1.5 py-0.5 text-2xs font-mono text-muted-foreground hover:bg-accent hover:text-foreground lg:flex"
          title="開啟全域命令列 (Cmd+K)"
          @click="ui.showCommandPalette = true"
        >
          <kbd class="text-3xs">⌘</kbd>K
        </button>
      </div>
      <div class="order-3 col-span-3 flex min-w-0 items-center justify-between lg:order-none lg:col-span-1 lg:justify-end">
        <p class="min-w-0 truncate text-xs text-muted-foreground lg:hidden">{{ viewTitle }}<span v-if="items.currentCategory !== '全部'"> / {{ items.currentCategory }}</span></p>
        <div class="flex shrink-0 items-center gap-1.5">
          <!-- Quick Brain Q&A -->
          <Button
            variant="ghost"
            size="sm"
            class="hidden md:inline-flex items-center gap-1.5 text-xs font-semibold text-primary bg-primary/10 hover:bg-primary/20 h-9 px-2.5 rounded-lg"
            title="對話大腦 (B)"
            @click="ui.showBrainModal = true"
          >
            <Bot class="size-3.5" />
            <span>對話大腦</span>
          </Button>

          <!-- Quick Daily Deck -->
          <Button
            variant="ghost"
            size="sm"
            class="hidden md:inline-flex items-center gap-1.5 text-xs font-medium text-foreground bg-muted/60 hover:bg-accent h-9 px-2.5 rounded-lg"
            title="每日回顧 Deck (D)"
            @click="ui.showDailyDeckModal = true"
          >
            <Sparkles class="size-3.5 text-amber-500" />
            <span>每日回顧</span>
          </Button>

          <div class="flex items-center rounded-lg bg-muted" role="group" aria-label="顯示方式">
            <button class="item-action rounded-lg" :class="items.viewMode === 'list' ? 'bg-accent text-foreground' : ''" aria-label="清單顯示" :aria-pressed="items.viewMode === 'list'" @click="items.viewMode = 'list'"><List class="size-4" /></button>
            <button class="item-action rounded-lg" :class="items.viewMode === 'cards' ? 'bg-accent text-foreground' : ''" aria-label="卡片顯示" :aria-pressed="items.viewMode === 'cards'" @click="items.viewMode = 'cards'"><LayoutGrid class="size-4" /></button>
          </div>
      <!-- Theme & Accent Palette Menu -->
      <div ref="themeMenuRef" class="relative">
        <Button
          variant="ghost"
          size="icon"
          title="外觀風格與強調色"
          aria-label="外觀設定"
          class="relative size-11 transition-colors cursor-pointer" :aria-expanded="showThemeMenu" aria-controls="theme-settings" @keydown.esc.stop="showThemeMenu = false"
          :class="showThemeMenu ? 'bg-accent text-foreground' : ''"
          @click="showThemeMenu = !showThemeMenu"
        >
          <Palette class="size-4.5" />
          <span class="absolute top-1.5 right-1.5 size-2 rounded-full bg-primary ring-1 ring-background shadow-xs" />
        </Button>

        <!-- Dropdown Card -->
        <div
          v-if="showThemeMenu" id="theme-settings" @keydown.esc.stop="showThemeMenu = false"
          class="absolute right-0 top-full mt-2 z-50 w-[min(18rem,calc(100vw-2rem))] rounded-xl border border-border bg-popover p-3.5 shadow-2xl text-foreground text-xs duration-200 animate-in fade-in-0 zoom-in-95"
        >
          <div class="mb-3 flex items-center justify-between border-b border-border/50 pb-2">
            <span class="font-semibold text-foreground">外觀與色彩</span>
          </div>

          <!-- Mode Selector -->
          <div class="mb-3 space-y-1.5">
            <span class="text-2xs text-subtle-foreground font-medium">主題模式</span>
            <div class="grid grid-cols-2 gap-1.5 rounded-lg bg-muted/60 p-1">
              <button
                type="button"
                class="flex min-h-11 items-center justify-center gap-1.5 rounded-md px-2 font-medium transition-colors cursor-pointer"
                :class="mode === 'dark' ? 'bg-background shadow-xs text-foreground font-semibold' : 'text-muted-foreground hover:text-foreground'"
                :aria-pressed="mode === 'dark'" @click="setTheme('dark')"
              >
                <Moon class="size-3.5" />
                <span>深色</span>
              </button>
              <button
                type="button"
                class="flex min-h-11 items-center justify-center gap-1.5 rounded-md px-2 font-medium transition-colors cursor-pointer"
                :class="mode === 'oled' ? 'bg-black text-white shadow-xs ring-1 ring-white/20 font-semibold' : 'text-muted-foreground hover:text-foreground'"
                :aria-pressed="mode === 'oled'" @click="setTheme('oled')"
              >
                <span class="size-2 rounded-full bg-white" />
                <span>OLED 純黑</span>
              </button>
              <button
                type="button"
                class="flex min-h-11 items-center justify-center gap-1.5 rounded-md px-2 font-medium transition-colors cursor-pointer"
                :class="mode === 'light' ? 'bg-background shadow-xs text-foreground font-semibold' : 'text-muted-foreground hover:text-foreground'"
                :aria-pressed="mode === 'light'" @click="setTheme('light')"
              >
                <Sun class="size-3.5" />
                <span>淺色</span>
              </button>
              <button
                type="button"
                class="flex min-h-11 items-center justify-center gap-1.5 rounded-md px-2 font-medium transition-colors cursor-pointer"
                :class="mode === 'system' ? 'bg-background shadow-xs text-foreground font-semibold' : 'text-muted-foreground hover:text-foreground'"
                :aria-pressed="mode === 'system'" @click="setTheme('system')"
              >
                <span>跟隨系統</span>
              </button>
            </div>
          </div>

          <!-- Accent Color Swatches -->
          <div class="space-y-1.5">
            <div class="flex items-center justify-between">
              <span class="text-2xs text-subtle-foreground font-medium">強調色</span>
              <span class="text-2xs text-primary font-semibold">
                {{ accents.find(a => a.id === accent)?.label }}
              </span>
            </div>
            <div class="grid grid-cols-3 gap-2 pt-0.5">
              <button
                v-for="opt in accents" :aria-pressed="accent === opt.id"
                :key="opt.id"
                type="button"
                :title="opt.label"
                :aria-label="opt.label"
                class="relative flex min-h-11 items-center justify-center rounded-lg cursor-pointer"
                :style="{ backgroundColor: opt.color }"
                @click="setAccent(opt.id)"
              >
                <Check
                  v-if="accent === opt.id"
                  class="size-5 rounded-full bg-white p-0.5 text-black"
                />
                <span
                  v-if="accent === opt.id"
                  class="absolute inset-0 rounded-lg ring-2 ring-foreground ring-offset-2 ring-offset-background"
                />
              </button>
            </div>
          </div>
        </div>
      </div>


          <Button v-if="deferredPrompt" variant="secondary" class="min-h-11" aria-label="安裝 OmniKeep" @click="installPWA"><Download class="size-4" /><span class="hidden xl:inline">安裝</span></Button>
        </div>
      </div>
    </div>
    <p v-if="quickError" id="quick-ingest-error" class="py-2 text-sm text-danger" role="alert">{{ quickError }}</p>
  </header>
</template>
