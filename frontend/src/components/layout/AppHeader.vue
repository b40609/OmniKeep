<script setup lang="ts">
import { ref, computed, nextTick, onUnmounted, watch } from 'vue'
import { useDebounceFn, onClickOutside } from '@vueuse/core'
import { Search, Download, Loader2, Menu, Plus, MessageCircleQuestion, Bell, Link2, FileText, FolderInput } from 'lucide-vue-next'
import { DropdownMenuRoot, DropdownMenuTrigger, DropdownMenuPortal, DropdownMenuContent, DropdownMenuItem } from 'reka-ui'
import AccountMenu from './AccountMenu.vue'
import { useUiStore } from '@/stores/ui'
import { useItemsStore } from '@/stores/items'
import { useMutations } from '@/composables/useMutations'
import { useMenuAction } from '@/composables/useMenuAction'

const emit = defineEmits<{ (e: 'logout'): void }>()

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
    case 'radar': return '雷達收件匣'
    case 'starred': return '加星'
    case 'archived': return '封存'
    default: return '全部'
  }
})

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
    <div class="grid grid-cols-[auto_minmax(0,1fr)_auto] grid-rows-[3.5rem] items-center gap-x-2 px-2 md:px-4 lg:grid-cols-[minmax(max-content,1fr)_minmax(0,640px)_minmax(max-content,1fr)] lg:gap-x-4">
      <!-- Sidebar toggle + product name (on a phone: the view being shown) -->
      <div class="flex min-w-0 items-center gap-2">
        <button
          type="button"
          class="icon-button"
          aria-label="收合或展開側邊欄"
          title="側邊欄　Ctrl/Cmd+B"
          @click="toggleSidebar"
        ><Menu /></button>
        <button type="button" class="flex min-w-0 items-center gap-2.5 rounded-lg py-1 pr-1 text-lg font-bold tracking-[-0.01em] text-foreground" title="回到收件匣" @click="goInbox">
          <svg class="size-7 shrink-0" viewBox="0 0 24 24" aria-hidden="true">
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
        <Search aria-hidden="true" />
        <input
          ref="searchInput"
          v-model="items.searchQuery"
          type="search"
          aria-label="搜尋收藏"
          :placeholder="items.searchMode === 'semantic' ? '用一句話描述想找的內容' : '搜尋標題、標籤或內容'"
          @input="debouncedSearch"
        />
        <button
          type="button"
          class="shrink-0 rounded px-1.5 text-xs leading-5 transition-colors hover:text-foreground"
          :class="items.searchMode === 'semantic' ? 'bg-surface-2 text-foreground' : ''"
          title="切換關鍵字搜尋與語意搜尋"
          :aria-pressed="items.searchMode === 'semantic'"
          @click="items.toggleSearchMode()"
        >{{ items.searchMode === 'semantic' ? '語意' : '關鍵字' }}</button>
        <kbd class="key-hint max-lg:hidden" title="按 / 開始搜尋">/</kbd>
      </div>

      <!-- Ask, add, notifications, settings -->
      <div class="flex items-center justify-end gap-1 max-lg:col-start-3 md:gap-2">
        <button class="icon-button lg:hidden" aria-label="搜尋收藏" title="搜尋　/" :aria-expanded="showMobileSearch" aria-controls="collection-search" @click="showMobileSearch ? (showMobileSearch = false) : focusSearchInput()"><Search /></button>

        <button type="button" class="top-button max-md:hidden max-xl:px-2.5" title="用收藏的內容回答問題　B" aria-label="問答" @click="ui.showBrainModal = true">
          <MessageCircleQuestion /><strong class="max-xl:hidden">問答</strong>
        </button>

        <!-- 新增: the one place to add things. 貼上連結 opens the panel below this button. -->
        <div ref="quickPanel" class="sm:relative">
          <DropdownMenuRoot>
            <DropdownMenuTrigger class="top-button top-button--primary max-sm:px-2.5" title="新增" aria-label="新增">
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
            class="absolute top-full z-50 rounded-xl border border-border bg-popover p-4 text-popover-foreground shadow-float max-sm:inset-x-3 max-sm:mt-1 sm:right-0 sm:mt-2 sm:w-[28rem]"
            :aria-busy="ui.isIngesting || submitting"
            @submit.prevent="submitQuick"
            @keydown.esc.stop="showQuick = false"
          >
            <label for="quick-url" class="text-sm text-muted-foreground">貼上網址或一段文字，讀完會寫成摘要。</label>
            <div class="mt-3 flex items-center gap-2">
              <input
                id="quick-url"
                ref="quickInput"
                v-model="quickUrl"
                type="text"
                :aria-invalid="!!quickError"
                :aria-describedby="quickError ? 'quick-ingest-error' : undefined"
                :disabled="ui.isIngesting || submitting"
                placeholder="https://"
                class="h-10 min-w-0 flex-1 rounded-lg border border-border bg-input px-3 text-base text-foreground transition-colors placeholder:text-muted-foreground focus:border-ring focus:outline-none"
                @input="quickError = ''"
              />
              <button type="submit" class="h-10 shrink-0 rounded-lg bg-primary px-4 text-sm font-semibold text-primary-foreground transition-colors hover:bg-primary-hover disabled:opacity-50" :disabled="!quickUrl.trim() || ui.isIngesting || submitting">
                {{ ui.isIngesting || submitting ? '收錄中' : '收錄' }}
              </button>
            </div>
            <p v-if="quickError" id="quick-ingest-error" class="pt-2 text-sm text-danger" role="alert">{{ quickError }}</p>
          </form>
        </div>

        <button v-if="deferredPrompt" type="button" class="icon-button max-md:hidden" aria-label="安裝 OmniKeep" title="安裝成應用程式" @click="installPWA"><Download /></button>

        <!-- The existing dialog behind the bell is the push settings, not a list of notifications: say so, and show no badge -->
        <button type="button" class="icon-button max-md:hidden" aria-label="通知設定" title="通知設定" @click="ui.showPushModal = true"><Bell /></button>

        <AccountMenu @logout="emit('logout')" />
      </div>
    </div>
  </header>
</template>
