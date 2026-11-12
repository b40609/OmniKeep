<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { toast } from 'vue-sonner'
import { initTheme } from '@/composables/useTheme'
import { useKeyboard } from '@/composables/useKeyboard'
import { useItemsStore } from '@/stores/items'
import { useUiStore } from '@/stores/ui'
import { useExperimentsStore } from '@/stores/experiments'
import { getSessionStatus, getStats, setApiKey, logBehaviorEvent, checkLocalAuth, redeemPairingCode, type SessionBridgeSnapshot } from '@/lib/api'
import { asPairingCode } from '@/lib/pairing'
import { linkedPanel, OPEN_LINK_MESSAGE } from '@/lib/push'
import { readClipRequest } from '@/lib/bookmarklet'
import { readSettingsLink } from '@/lib/settingsLink'
import { WATCH_CATEGORIES } from '@/lib/experiments'
import AppHeader from '@/components/layout/AppHeader.vue'
import AppSidebar from '@/components/layout/AppSidebar.vue'
import MobileBottomBar from '@/components/layout/MobileBottomBar.vue'
import ItemList from '@/components/items/ItemList.vue'
import ReaderPane from '@/components/reader/ReaderPane.vue'
import NoteDialog from '@/components/modals/NoteDialog.vue'
import CategoryDialog from '@/components/modals/CategoryDialog.vue'
import ShortcutsDialog from '@/components/modals/ShortcutsDialog.vue'
import RadarDialog from '@/components/modals/RadarDialog.vue'
import WatchDialog from '@/components/modals/WatchDialog.vue'
import ImportDialog from '@/components/modals/ImportDialog.vue'
import DeckDialog from '@/components/modals/DeckDialog.vue'
import SettingsPage from '@/components/settings/SettingsPage.vue'
import SetupWizard from '@/components/modals/SetupWizard.vue'
import ServiceStatusBanner from '@/components/layout/ServiceStatusBanner.vue'
import DailyDeckDialog from '@/components/modals/DailyDeckDialog.vue'
import BrainDialog from '@/components/modals/BrainDialog.vue'
import CommandPalette from '@/components/modals/CommandPalette.vue'
import SnapshotDialog from '@/components/modals/SnapshotDialog.vue'
import * as api from '@/lib/api'
import { Toaster } from '@/components/ui/sonner'
import { useMutations } from '@/composables/useMutations'

initTheme()

const items = useItemsStore()
const ui = useUiStore()
const experiments = useExperimentsStore()
const signedIn = ref(false)
const isCheckingAuth = ref(true)
const credential = ref('')
const loginError = ref('')
const loggingIn = ref(false)

const STORAGE_KEY = 'omnikeep_api_key'
// An agent's omnikeep_open_settings link (`#settings=ai`); read before sign-in clears the fragment.
let pendingSettingsLink = readSettingsLink(window.location.hash)
const rememberKey = ref(true)

function requireLogin(clearSaved = false) {
  signedIn.value = false
  setApiKey('')
  if (clearSaved) {
    localStorage.removeItem(STORAGE_KEY)
  }
  ui.activeItem = null
  items.items = []
  items.categories = []
  items.stats = { inbox: 0, starred: 0, archived: 0, radar: 0, total: 0 }
  ui.snapshotView = null
}

function handleLogout() {
  requireLogin(true)
}

async function login(explicitKey?: string, isAuto = false): Promise<boolean> {
  loggingIn.value = true
  loginError.value = ''
  const targetKey = (explicitKey ?? credential.value).trim()
  if (!targetKey) {
    loggingIn.value = false
    return false
  }
  setApiKey(targetKey)
  try {
    await getStats()
    if (rememberKey.value) {
      localStorage.setItem(STORAGE_KEY, targetKey)
    } else {
      localStorage.removeItem(STORAGE_KEY)
    }
    credential.value = ''
    signedIn.value = true
    void experiments.load()
    await items.refreshAll()
    await maybeShowSessionHint()
    await checkUrlParamIngest()
    if (openLinkedPanel(window.location.href)) {
      window.history.replaceState({}, document.title, window.location.pathname)
    }
    if (pendingSettingsLink) {
      ui.openSettings(pendingSettingsLink.tab, pendingSettingsLink.card)
      pendingSettingsLink = null
      window.history.replaceState({}, document.title, window.location.pathname + window.location.search)
    }
    return true
  } catch (error) {
    if (!isAuto) {
      requireLogin(true)
      loginError.value = error instanceof Error ? error.message : '登入失敗，請確認存取金鑰'
    } else {
      requireLogin(false)
    }
    return false
  } finally {
    loggingIn.value = false
  }
}

/** A one-time pairing code from a signed-in screen is traded for the key first. */
async function signInWithCode(code: string): Promise<boolean> {
  loggingIn.value = true
  loginError.value = ''
  let key = ''
  try {
    key = await redeemPairingCode(code)
  } catch (error) {
    loginError.value = error instanceof Error ? error.message : '配對碼無效'
    return false
  } finally {
    loggingIn.value = false
  }
  credential.value = ''
  return login(key)
}

function submitLogin() {
  const code = asPairingCode(credential.value)
  return code ? signInWithCode(code) : login()
}

async function checkUrlParamIngest() {
  const clip = readClipRequest(window.location.search)
  if (clip) {
    window.history.replaceState({}, document.title, window.location.pathname)
    const { quickIngest } = useMutations()
    toast.info('正在收錄這個網址…')
    const ok = await quickIngest(clip.url, { pageTitle: clip.title, pageDescription: clip.description })
    if (clip.autoClose) {
      if (ok) {
        toast.success('收錄完成，視窗即將關閉', { duration: 1200 })
        setTimeout(() => {
          window.close()
        }, 1200)
      } else {
        toast.error('沒有收錄成功，視窗先留著')
      }
    }
  }
}

/** Notifications about a new suggestion link to `/?open=proposals`: show 專案監看 on its 建議 tab. */
function openLinkedPanel(href: string): boolean {
  if (linkedPanel(href, window.location.origin) !== 'proposals') return false
  ui.watchTab = 'proposals'
  ui.showWatchModal = true
  return true
}

// A notification clicked while this window is already open arrives here instead of as a page load.
function onWorkerMessage(event: MessageEvent) {
  if (signedIn.value && event.data?.type === OPEN_LINK_MESSAGE) openLinkedPanel(String(event.data.url))
}

async function bootstrapAuth() {
  isCheckingAuth.value = true
  try {
    // 0. Key handed over in the URL fragment (#key=... or #api_key=...). A fragment is never
    //    sent to the server, so the key stays out of access logs and reverse proxies.
    const fragment = new URLSearchParams(window.location.hash.replace(/^#/, ''))
    const urlKey = fragment.get('key') || fragment.get('api_key')
    if (urlKey) {
      window.history.replaceState({}, document.title, window.location.pathname + window.location.search)
      rememberKey.value = true
      const ok = await login(urlKey, true)
      if (ok) return
    }
    // 0b. A one-time pairing code from the QR code on a signed-in screen (#pair=...).
    const urlCode = asPairingCode(fragment.get('pair') || '')
    if (urlCode) {
      window.history.replaceState({}, document.title, window.location.pathname + window.location.search)
      rememberKey.value = true
      if (await signInWithCode(urlCode)) return
    }

    // 1. Check local browser storage first
    const savedKey = localStorage.getItem(STORAGE_KEY)
    if (savedKey) {
      rememberKey.value = true
      const ok = await login(savedKey, true)
      if (ok) return
    }

    // 2. Local loopback auto-auth (zero friction for localhost; refused behind a reverse proxy)
    const local = await checkLocalAuth()
    if (local.authenticated && local.api_key) {
      rememberKey.value = true
      const ok = await login(local.api_key, true)
      if (ok) return
    }
  } finally {
    isCheckingAuth.value = false
  }
}

const headerRef = ref<InstanceType<typeof AppHeader> | null>(null)
const listRef = ref<InstanceType<typeof ItemList> | null>(null)
useKeyboard(() => headerRef.value, () => signedIn.value)

// J/K navigation keeps the open item — or, in the cover wall, the keyboard cursor — in view.
function revealItem(id: number | null | undefined) {
  if (id != null) listRef.value?.scrollToItem(id)
}
watch(() => ui.cursorId, (id) => nextTick(() => revealItem(id)))
watch(
  () => ui.activeItem?.id,
  (id, previous) => {
    if (id != null) ui.cursorId = id
    void nextTick(() => revealItem(id ?? ui.cursorId))
    // Opening or closing the reader changes the wall's width and column count;
    // look again once that transition has settled.
    if ((id == null) !== (previous == null)) setTimeout(() => revealItem(ui.activeItem?.id ?? ui.cursorId), 340)
  },
)

// An experimental view that has been switched off is not somewhere to be left in.
watch(
  () => experiments.flags.radar,
  (on) => {
    if (!on && items.triageView === 'radar') {
      items.triageView = 'inbox'
      if (signedIn.value) void items.loadItems()
    }
  },
  { immediate: true },
)
watch(
  () => experiments.flags.watch,
  (on) => {
    if (!on && WATCH_CATEGORIES.includes(items.currentCategory)) {
      items.currentCategory = '全部'
      if (signedIn.value) void items.loadItems()
    }
  },
  { immediate: true },
)

// P1 behavior fuel: opening an item counts as a view event (fire-and-forget).
watch(
  () => ui.activeItem?.id,
  (id) => {
    if (id != null) logBehaviorEvent({ event_type: 'view', item_id: String(id) }).catch(() => {})
  },
)

/** Non-intrusive first-run hint when no platform session is connected. */
async function maybeShowSessionHint() {
  const DISMISS_KEY = 'omnikeep-session-hint-dismissed'
  try {
    if (localStorage.getItem(DISMISS_KEY)) return
    const bridge: SessionBridgeSnapshot = (await getSessionStatus()).bridge
    const socialItems = items.items.some(
      (i) => ['instagram', 'facebook', 'reel'].includes(i.source_type.toLowerCase()),
    )
    const connected = bridge.platforms.some((p) => p.connected)
    if (connected || !socialItems) return
    toast.info('社群平台還沒登入', {
      description: '登入一次 Instagram 或 Facebook，Reels 和社群貼文比較讀得到內容。',
      duration: 10000,
      action: {
        label: '前往設定',
        onClick: () => ui.openSettings('channels', '', 'sessions'),
      },
      onDismiss: () => localStorage.setItem(DISMISS_KEY, '1'),
      onAutoClose: () => localStorage.setItem(DISMISS_KEY, '1'),
    })
  } catch {
    /* status endpoint unavailable — stay silent */
  }
}

function onAuthRequired() {
  requireLogin(true)
}

onMounted(() => {
  window.addEventListener('omnikeep-auth-required', onAuthRequired)
  navigator.serviceWorker?.addEventListener('message', onWorkerMessage)
  window.addEventListener('open-item', async (e: any) => {
    const itemId = e.detail?.itemId
    if (itemId) {
      const it = items.items.find((x: any) => String(x.id) === String(itemId))
      if (it) {
        ui.activeItem = it
        ui.detailTab = 'analysis'
      } else {
        try {
          const fetched = await api.getItem(String(itemId))
          if (fetched) {
            ui.activeItem = fetched
            ui.detailTab = 'analysis'
          }
        } catch {}
      }
    }
  })
  bootstrapAuth()
})
onUnmounted(() => {
  window.removeEventListener('omnikeep-auth-required', onAuthRequired)
  navigator.serviceWorker?.removeEventListener('message', onWorkerMessage)
})
</script>

<template>
  <!-- Auth initializing spinner (avoids login modal flashing on localhost) -->
  <div v-if="isCheckingAuth" class="relative z-10 flex h-screen w-screen items-center justify-center">
    <div class="flex flex-col items-center gap-3">
      <div class="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
      <span class="text-xs text-muted-foreground tracking-wide">載入 OmniKeep...</span>
    </div>
  </div>

  <form v-else-if="!signedIn" class="relative z-10 mx-auto mt-24 flex max-w-sm flex-col gap-4 rounded-xl border bg-background p-8 text-foreground shadow-2xl" @submit.prevent="submitLogin()">
    <div class="flex items-center justify-between">
      <h1 class="text-xl font-semibold">登入 OmniKeep</h1>
      <button
        type="button"
        title="重新嘗試本機自動登入"
        class="text-xs text-primary hover:underline"
        @click="bootstrapAuth()"
      >
        自動辨識登入
      </button>
    </div>
    <label for="api-key" class="text-xs font-medium text-muted-foreground">存取金鑰或配對碼</label>
    <!-- Shown while short enough to be an 8-letter pairing code; a pasted key is longer and stays hidden. -->
    <input
      id="api-key"
      v-model="credential"
      :type="credential.length <= 9 ? 'text' : 'password'"
      autocomplete="off"
      autocapitalize="off"
      autocorrect="off"
      spellcheck="false"
      placeholder="貼上存取金鑰，或輸入 8 碼配對碼"
      required
      class="rounded-lg border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
    />
    <p class="-mt-2 text-2xs text-muted-foreground">配對碼在電腦上的「設定 › 收錄管道 › 手機登入」產生，5 分鐘內有效。</p>

    <div class="flex items-center gap-2">
      <input
        id="remember-key"
        v-model="rememberKey"
        type="checkbox"
        class="h-4 w-4 rounded border-border text-primary focus:ring-primary cursor-pointer accent-primary"
      />
      <label for="remember-key" class="text-xs cursor-pointer select-none text-muted-foreground">
        記住金鑰（儲存於本機瀏覽器）
      </label>
    </div>

    <p class="text-xs text-muted-foreground">
      {{ rememberKey ? '金鑰將保存於本機 localStorage，下次開啟自動登入。' : '金鑰僅保留於本頁記憶體，重新整理後需再次登入。' }}
    </p>
    <p v-if="loginError" role="alert" class="text-xs text-red-500">{{ loginError }}</p>
    <button type="submit" :disabled="loggingIn" class="rounded-lg bg-primary py-2.5 text-sm text-primary-foreground font-medium transition hover:opacity-90 disabled:opacity-50">
      {{ loggingIn ? '驗證中…' : '登入' }}
    </button>
  </form>
  <div v-else class="relative z-10 flex h-[100dvh] w-screen flex-col overflow-hidden bg-shell text-foreground">
    <!-- Top bar spans the full width; the sidebar and the workspace sit under it -->
    <AppHeader ref="headerRef" :inert="ui.showSettingsModal" @logout="handleLogout" />
    <ServiceStatusBanner />

    <div class="flex min-h-0 flex-1" :inert="ui.showSettingsModal">
      <!-- Collapsible sidebar (a drawer on phones) -->
      <AppSidebar />

      <!-- Master–detail workbench body -->
      <div class="relative flex min-h-0 min-w-0 flex-1 overflow-hidden">
        <!-- Master stream -->
        <div
          class="flex h-full min-w-0 flex-col transition-[width] duration-300 ease-out max-lg:w-full"
          :class="ui.activeItem ? 'lg:w-1/2 xl:w-5/12' : 'w-full'"
        >
          <ItemList ref="listRef" />
        </div>

        <!-- Detail reader -->
        <ReaderPane v-if="ui.activeItem" />
      </div>
    </div>

    <!-- Modals -->
    <NoteDialog />
    <CategoryDialog />
    <ShortcutsDialog />
    <RadarDialog />
    <WatchDialog />
    <ImportDialog />
    <DeckDialog />
    <!-- Settings are a page over the workspace, not a dialog; dialogs opened from it sit above -->
    <SettingsPage v-if="ui.showSettingsModal" />
    <SetupWizard />
    <DailyDeckDialog />
    <BrainDialog />
    <CommandPalette />
    <SnapshotDialog />

    <!-- iOS Single-Handed Bottom Bar (Mobile only) -->
    <MobileBottomBar v-if="!ui.activeItem && !ui.showSettingsModal" />

  </div>

  <Toaster />
</template>
