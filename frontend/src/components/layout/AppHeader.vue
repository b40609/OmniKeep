<script setup lang="ts">
import { ref } from 'vue'
import { useDebounceFn } from '@vueuse/core'
import {
  BrainCircuit, Search, FileText, Radar, Keyboard, Download,
  Sun, Moon, List, LayoutGrid, Loader2, X, KeyRound, ScanEye,
} from 'lucide-vue-next'
import Button from '@/components/ui/button/Button.vue'
import { useUiStore } from '@/stores/ui'
import { useItemsStore } from '@/stores/items'
import { useRadarStore } from '@/stores/radar'
import { useTheme } from '@/composables/useTheme'
import { useMutations } from '@/composables/useMutations'

const ui = useUiStore()
const items = useItemsStore()
const radar = useRadarStore()
const { mode, toggle } = useTheme()
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
</script>

<template>
  <header class="safe-top ios-blur z-30 shrink-0 border-b border-hairline px-3 py-2 sm:px-4">
    <div class="flex items-center gap-2">
      <!-- Brand -->
      <div class="flex shrink-0 items-center gap-2">
        <div class="flex size-8 items-center justify-center rounded-[10px] bg-primary text-primary-foreground shadow-sm">
          <BrainCircuit class="size-4.5" />
        </div>
        <div class="leading-tight max-sm:hidden">
          <p class="text-sm font-bold tracking-tight">OmniKeep</p>
          <p class="text-2xs text-subtle-foreground">第二大腦</p>
        </div>
      </div>

      <!-- Quick-add omnibox (iOS search field style) -->
      <div class="relative mx-1 flex min-w-0 flex-1 items-center">
        <Search class="pointer-events-none absolute left-3 text-subtle-foreground size-4" />
        <input
          ref="quickInput"
          v-model="quickUrl"
          type="text"
          :disabled="ui.isIngesting"
          placeholder="貼上網址或段落，Enter 存入"
          class="h-9 w-full rounded-full border border-white/60 bg-white/55 px-9 text-xs text-foreground shadow-sm transition-all duration-200 placeholder:text-subtle-foreground focus:border-white/80 focus:bg-white/80 focus:outline-none focus:ring-2 focus:ring-primary/30 disabled:opacity-50 dark:border-white/10 dark:bg-white/[0.08] dark:focus:bg-white/[0.12]"
          @keyup.enter="submitQuick"
        />
        <button
          v-if="quickUrl && !ui.isIngesting"
          class="absolute right-2.5 rounded-full bg-border-strong/60 p-0.5 text-background"
          aria-label="清除"
          @click="quickUrl = ''"
        >
          <X class="size-3" />
        </button>
        <button
          class="absolute right-1 flex h-7 items-center gap-1 rounded-full bg-primary px-3 text-2xs font-semibold text-primary-foreground shadow-sm transition-all active:scale-95 disabled:opacity-40"
          :disabled="!quickUrl.trim() || ui.isIngesting"
          aria-label="存入"
          @click="submitQuick"
        >
          <Loader2 v-if="ui.isIngesting" class="size-3 animate-spin" />
          {{ ui.isIngesting ? '解析中' : '存入' }}
        </button>
      </div>

      <!-- Right toolbar: iOS icon row -->
      <div class="flex shrink-0 items-center gap-0.5">
        <!-- Search (desktop) -->
        <div class="relative hidden xl:block">
          <Search class="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-subtle-foreground" />
          <input
            ref="searchInput"
            v-model="items.searchQuery"
            type="text"
            placeholder="搜尋"
            class="h-8 w-40 rounded-full border border-white/60 bg-white/55 pl-8 pr-3 text-xs text-foreground shadow-sm transition-all placeholder:text-subtle-foreground focus:bg-white/80 focus:outline-none focus:ring-2 focus:ring-primary/30 dark:border-white/10 dark:bg-white/[0.08]"
            @input="debouncedSearch"
          >
        </div>

        <Button variant="ghost" size="icon" title="搜尋（/）" aria-label="搜尋" class="xl:hidden" @click="focusSearchInput()">
          <Search class="size-4.5" />
        </Button>

        <!-- Density switcher (segmented) -->
        <div class="mx-1 hidden items-center rounded-full bg-white/50 p-0.5 shadow-sm dark:bg-white/[0.08] sm:flex">
          <button
            v-for="m in [{ id: 'list', icon: List, label: '清單視圖' }, { id: 'cards', icon: LayoutGrid, label: '卡片視圖' }]"
            :key="m.id"
            class="flex size-7 items-center justify-center rounded-full transition-all duration-200"
            :class="items.viewMode === m.id ? 'bg-white/90 shadow-md dark:bg-white/[0.16]' : 'text-muted-foreground'"
            :aria-label="m.label"
            :title="m.label"
            @click="items.viewMode = m.id as 'list' | 'cards'"
          >
            <component :is="m.icon" class="size-3.5" />
          </button>
        </div>

        <Button variant="ghost" size="icon" title="情報雷達（R）" aria-label="情報雷達" @click="ui.showRadarModal = true; radar.ensureLoaded()">
          <Radar class="size-4.5" />
        </Button>

        <Button variant="ghost" size="icon" title="會話連結" aria-label="會話連結" @click="ui.showSessionModal = true">
          <KeyRound class="size-4.5" />
        </Button>

        <Button variant="ghost" size="icon" title="監看中心（本地提案引擎）" aria-label="監看中心" @click="ui.showWatchModal = true">
          <ScanEye class="size-4.5" />
        </Button>

        <Button variant="ghost" size="icon" :title="mode === 'dark' ? '切換淺色' : '切換深色'" aria-label="切換主題" @click="toggle()">
          <Sun v-if="mode === 'dark'" class="size-4.5" />
          <Moon v-else class="size-4.5" />
        </Button>

        <Button variant="ghost" size="icon" title="快捷鍵（?）" aria-label="快捷鍵指南" class="max-md:hidden" @click="ui.showShortcutsModal = true">
          <Keyboard class="size-4.5" />
        </Button>

        <!-- Long note: primary pill -->
        <Button size="sm" class="ml-1" title="長文筆記（Shift+N）" @click="ui.showNoteModal = true">
          <FileText class="size-3.5" />
          <span class="max-lg:hidden">筆記</span>
        </Button>

        <Button v-if="deferredPrompt" variant="secondary" size="sm" class="ml-1" @click="installPWA">
          <Download class="size-3.5" />
          <span class="max-lg:hidden">安裝</span>
        </Button>
      </div>
    </div>
  </header>
</template>
