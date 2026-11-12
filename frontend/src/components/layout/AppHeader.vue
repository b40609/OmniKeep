<script setup lang="ts">
import { ref, computed, nextTick, onUnmounted, watch } from 'vue'
import { Search, Download, Loader2, Menu, Plus, Bell } from 'lucide-vue-next'
import AccountMenu from './AccountMenu.vue'
import SearchBox from './SearchBox.vue'
import { useUiStore } from '@/stores/ui'
import { useItemsStore } from '@/stores/items'

const emit = defineEmits<{ (e: 'logout'): void }>()

const ui = useUiStore()
const items = useItemsStore()

const searchBox = ref<InstanceType<typeof SearchBox> | null>(null)
/** Below the wide layout the box is a row of its own that opens on demand. */
const showMobileSearch = ref(false)

defineExpose({ focusSearchInput, focusAsk })

/** `/`, Ctrl/Cmd+K and the search buttons: the box, ready to search. */
async function focusSearchInput() {
  showMobileSearch.value = true
  await nextTick()
  await searchBox.value?.focus('search')
}
/** B: the same box, switched to asking a question. */
async function focusAsk() {
  showMobileSearch.value = true
  await nextTick()
  await searchBox.value?.focus('ask')
}
// The mobile bottom bar has no handle on this component; it asks through the store.
watch(() => ui.searchFocusRequests, (count) => {
  if (count) void focusSearchInput()
})

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
    case 'radar': return '探索'
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

      <!-- One box for search, questions, filters and actions: centred on wide screens, a row of its own on narrower ones once opened -->
      <SearchBox
        id="collection-search"
        ref="searchBox"
        class="max-lg:order-last max-lg:col-span-3 max-lg:mx-2 max-lg:mb-2"
        :class="showMobileSearch ? 'block' : 'hidden lg:block'"
        @dismiss="showMobileSearch = false"
      />

      <!-- Add, notifications, settings -->
      <div class="flex items-center justify-end gap-1 max-lg:col-start-3 md:gap-2">
        <button class="icon-button lg:hidden" aria-label="搜尋或提問" title="搜尋　/" :aria-expanded="showMobileSearch" aria-controls="collection-search" @click="focusSearchInput()"><Search /></button>

        <!-- 新增: the one place to add things, whether a link, a note or a bookmark file -->
        <button type="button" class="top-button top-button--primary max-sm:px-2.5" title="新增　N" aria-label="新增" @click="ui.openAdd()">
          <Loader2 v-if="ui.isIngesting" class="animate-spin" />
          <Plus v-else />
          <strong class="max-sm:hidden">新增</strong>
        </button>

        <button v-if="deferredPrompt" type="button" class="icon-button max-md:hidden" aria-label="安裝 OmniKeep" title="安裝成應用程式" @click="installPWA"><Download /></button>

        <!-- There is no list of notifications yet: the bell opens their settings, and shows no badge -->
        <button type="button" class="icon-button max-md:hidden" aria-label="通知設定" title="通知設定" @click="ui.openSettings('notifications')"><Bell /></button>

        <AccountMenu @logout="emit('logout')" />
      </div>
    </div>
  </header>
</template>
