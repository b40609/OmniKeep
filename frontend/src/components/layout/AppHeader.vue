<script setup lang="ts">
import { ref, computed, nextTick, onUnmounted, watch } from 'vue'
import { useDebounceFn, onClickOutside } from '@vueuse/core'
import {
  Search, Download, List, LayoutGrid, Loader2, Menu, Plus, ChevronDown, Check,
  Bot, Link2, FileText, FolderInput,
} from 'lucide-vue-next'
import {
  DropdownMenuRoot, DropdownMenuTrigger, DropdownMenuPortal, DropdownMenuContent, DropdownMenuItem,
  DropdownMenuRadioGroup, DropdownMenuRadioItem, DropdownMenuItemIndicator,
} from 'reka-ui'
import { useUiStore } from '@/stores/ui'
import { useItemsStore, type SortOrder } from '@/stores/items'
import { useMutations } from '@/composables/useMutations'
import { useMenuAction } from '@/composables/useMenuAction'

const ui = useUiStore()
const items = useItemsStore()

const { quickIngest } = useMutations()

const quickInput = ref<HTMLInputElement | null>(null)
const searchInput = ref<HTMLInputElement | null>(null)
const quickPanel = ref<HTMLElement | null>(null)
const quickUrl = ref('')
const quickError = ref('')
const showQuick = ref(false)
const showMobileSearch = ref(false)
const submitting = ref(false)
onClickOutside(quickPanel, () => {
  showQuick.value = false
})

defineExpose({ focusQuickInput, focusSearchInput })

/** Open the paste-a-link panel under 新增 and put the caret in it (also the N shortcut). */
async function focusQuickInput() {
  showQuick.value = true
  await nextTick()
  quickInput.value?.focus()
}
async function focusSearchInput() {
  showMobileSearch.value = true
  await nextTick()
  searchInput.value?.focus()
}
// The mobile bottom bar has no handle on this component; it asks through the store.
watch(() => ui.searchFocusRequests, (count) => {
  if (count) void focusSearchInput()
})

// 新增 menu: each item opens its panel or dialog once the menu has closed (see useMenuAction).
const addMenu = useMenuAction()

async function submitQuick() {
  const content = quickUrl.value.trim()
  if (!content || ui.isIngesting || submitting.value) return
  submitting.value = true
  quickError.value = ''
  try {
    if (await quickIngest(content)) {
      quickUrl.value = ''
      showQuick.value = false
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
    case 'radar': return '雷達'
    case 'starred': return '加星'
    case 'archived': return '封存'
    default: return '全部'
  }
})

const SORT_LABELS: Record<SortOrder, string> = { newest: '最新收錄', oldest: '最早收錄' }
// A search comes back ranked by relevance and is shown in that order.
const sortLabel = computed(() => (items.ranked ? '最相關' : SORT_LABELS[items.sortOrder]))

/** One button for both: the drawer on a phone, the sidebar (full or icon rail) on wider screens. */
function toggleSidebar() {
  if (window.matchMedia('(min-width: 768px)').matches) ui.sidebarOpen = !ui.sidebarOpen
  else ui.sidebarMobileOpen = !ui.sidebarMobileOpen
}

function goInbox() {
  items.triageView = 'inbox'
  items.currentCategory = '全部'
  items.loadItems()
}
</script>

<template>
  <header class="safe-top relative z-30 shrink-0 bg-shell">
    <div class="grid grid-cols-[auto_minmax(0,1fr)_auto] grid-rows-[3.5rem] items-center gap-x-2 px-2 md:pl-4 md:pr-6 lg:grid-cols-[minmax(max-content,1fr)_minmax(0,560px)_minmax(max-content,1fr)] lg:gap-x-4">
      <!-- Sidebar toggle + product name (on a phone: the view being shown) -->
      <div class="flex min-w-0 items-center gap-2">
        <button
          type="button"
          class="item-action !size-10 shrink-0"
          aria-label="收合或展開側邊欄"
          title="側邊欄　Ctrl/Cmd+B"
          @click="toggleSidebar"
        ><Menu class="size-5" /></button>
        <button type="button" class="flex min-w-0 items-center gap-2.5 rounded-lg py-1 pr-1 text-[17px] font-bold tracking-[-0.01em] text-foreground" title="回到收件匣" @click="goInbox">
          <svg class="size-6 shrink-0" viewBox="0 0 24 24" aria-hidden="true">
            <rect width="24" height="24" rx="6" fill="var(--primary)" />
            <path d="M8 6h8v12l-4-3-4 3z" fill="var(--primary-foreground)" />
          </svg>
          <span class="max-md:hidden">OmniKeep</span>
          <span class="truncate md:hidden">{{ viewTitle }}<span v-if="items.currentCategory !== '全部'" class="font-normal text-muted-foreground"> / {{ items.currentCategory }}</span></span>
        </button>
      </div>

      <!-- Search: centred on wide screens, a row of its own on narrower ones once opened -->
      <div
        id="collection-search"
        class="search-box max-lg:order-last max-lg:col-span-3 max-lg:mx-2 max-lg:mb-2"
        :class="showMobileSearch ? 'flex' : 'hidden lg:flex'"
      >
        <Search class="size-[18px] shrink-0" aria-hidden="true" />
        <input
          ref="searchInput"
          v-model="items.searchQuery"
          type="search"
          aria-label="搜尋收藏"
          :placeholder="items.searchMode === 'semantic' ? '用一句話描述想找的內容' : '搜尋標題、標籤或內容'"
          class="text-base lg:text-sm"
          @input="debouncedSearch"
        />
        <button
          type="button"
          class="shrink-0 rounded px-1.5 text-xs leading-5 hover:text-foreground"
          :class="items.searchMode === 'semantic' ? 'bg-surface-2 text-foreground' : ''"
          title="切換：依關鍵字，或依意思搜尋"
          :aria-pressed="items.searchMode === 'semantic'"
          @click="items.toggleSearchMode()"
        >{{ items.searchMode === 'semantic' ? '依意思' : '關鍵字' }}</button>
        <kbd class="key-hint max-lg:hidden" title="按 / 開始搜尋">/</kbd>
      </div>

      <!-- Ask, add, sort, view -->
      <div class="flex items-center justify-end gap-1 max-lg:col-start-3 md:gap-2">
        <button class="item-action !size-10 lg:hidden" aria-label="搜尋收藏" title="搜尋　/" :aria-expanded="showMobileSearch" aria-controls="collection-search" @click="showMobileSearch ? (showMobileSearch = false) : focusSearchInput()"><Search class="size-5" /></button>

        <button type="button" class="top-button max-md:hidden max-xl:px-[9px]" title="問大腦　B" aria-label="問大腦" @click="ui.showBrainModal = true">
          <Bot /><strong class="max-xl:hidden">問大腦</strong>
        </button>

        <!-- 新增: the one place to add things. 貼上連結 opens the panel below this button. -->
        <div ref="quickPanel" class="sm:relative">
          <DropdownMenuRoot>
            <DropdownMenuTrigger class="top-button top-button--primary max-sm:px-[9px]" title="新增" aria-label="新增">
              <Loader2 v-if="ui.isIngesting || submitting" class="animate-spin" />
              <Plus v-else />
              <strong class="max-sm:hidden">新增</strong>
            </DropdownMenuTrigger>
            <DropdownMenuPortal>
              <DropdownMenuContent class="app-menu" align="end" :side-offset="8" :collision-padding="12" @close-auto-focus="addMenu.flush">
                <DropdownMenuItem class="app-menu__item" title="貼上連結　N" @select="addMenu.defer(() => void focusQuickInput())"><Link2 aria-hidden="true" />貼上連結</DropdownMenuItem>
                <DropdownMenuItem class="app-menu__item" title="新增筆記　Shift+N" @select="addMenu.defer(() => (ui.showNoteModal = true))"><FileText aria-hidden="true" />新增筆記</DropdownMenuItem>
                <DropdownMenuItem class="app-menu__item" title="匯入書籤　I" @select="addMenu.defer(() => (ui.showImportModal = true))"><FolderInput aria-hidden="true" />匯入書籤</DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenuPortal>
          </DropdownMenuRoot>
          <form
            v-if="showQuick"
            id="quick-ingest"
            class="absolute top-full z-50 rounded-xl border border-border bg-popover p-3 text-popover-foreground shadow-float max-sm:inset-x-3 max-sm:mt-1 sm:right-0 sm:mt-2 sm:w-[26rem]"
            :aria-busy="ui.isIngesting || submitting"
            @submit.prevent="submitQuick"
            @keydown.esc.stop="showQuick = false"
          >
            <label for="quick-url" class="text-xs text-muted-foreground">貼上網址或一段文字，讀完會寫成摘要</label>
            <div class="mt-2 flex items-center gap-2">
              <input
                id="quick-url"
                ref="quickInput"
                v-model="quickUrl"
                type="text"
                :aria-invalid="!!quickError"
                :aria-describedby="quickError ? 'quick-ingest-error' : undefined"
                :disabled="ui.isIngesting || submitting"
                placeholder="https://"
                class="h-10 min-w-0 flex-1 rounded-lg border border-border bg-input px-3 text-base text-foreground placeholder:text-muted-foreground focus:border-ring focus:outline-none md:text-sm"
                @input="quickError = ''"
              />
              <button type="submit" class="h-10 shrink-0 rounded-lg bg-primary px-4 text-sm font-semibold text-primary-foreground hover:bg-primary-hover disabled:opacity-50" :disabled="!quickUrl.trim() || ui.isIngesting || submitting">
                {{ ui.isIngesting || submitting ? '收錄中' : '收錄' }}
              </button>
            </div>
            <p v-if="quickError" id="quick-ingest-error" class="pt-2 text-sm text-danger" role="alert">{{ quickError }}</p>
          </form>
        </div>

        <DropdownMenuRoot>
          <DropdownMenuTrigger class="top-button max-sm:hidden" :disabled="items.ranked" :title="items.ranked ? '搜尋結果依相關性排列' : '排序'">
            <span class="max-xl:hidden">排序</span><strong>{{ sortLabel }}</strong><ChevronDown v-if="!items.ranked" />
          </DropdownMenuTrigger>
          <DropdownMenuPortal>
            <DropdownMenuContent class="app-menu !min-w-40" align="end" :side-offset="8" :collision-padding="12">
              <DropdownMenuRadioGroup :model-value="items.sortOrder" @update:model-value="items.sortOrder = $event as SortOrder">
                <DropdownMenuRadioItem v-for="(label, order) in SORT_LABELS" :key="order" :value="order" class="app-menu__item">
                  {{ label }}
                  <span class="app-menu__end"><DropdownMenuItemIndicator><Check aria-hidden="true" /></DropdownMenuItemIndicator></span>
                </DropdownMenuRadioItem>
              </DropdownMenuRadioGroup>
            </DropdownMenuContent>
          </DropdownMenuPortal>
        </DropdownMenuRoot>

        <div class="view-switch" role="group" aria-label="檢視方式">
          <button type="button" aria-label="格狀" title="格狀" :aria-pressed="items.viewMode === 'cards'" @click="items.viewMode = 'cards'"><LayoutGrid /></button>
          <button type="button" aria-label="清單" title="清單" :aria-pressed="items.viewMode === 'list'" @click="items.viewMode = 'list'"><List /></button>
        </div>

        <button v-if="deferredPrompt" type="button" class="top-button max-lg:px-[9px]" aria-label="安裝 OmniKeep" title="安裝成應用程式" @click="installPWA"><Download /><strong class="max-xl:hidden">安裝</strong></button>
      </div>
    </div>
  </header>
</template>
