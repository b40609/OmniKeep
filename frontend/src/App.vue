<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import { toast } from 'vue-sonner'
import { initTheme } from '@/composables/useTheme'
import { useKeyboard } from '@/composables/useKeyboard'
import { useItemsStore } from '@/stores/items'
import { useUiStore } from '@/stores/ui'
import { getSessionStatus, getStats, setApiKey, logBehaviorEvent, checkLocalAuth, type SessionBridgeSnapshot } from '@/lib/api'
import AppHeader from '@/components/layout/AppHeader.vue'
import AppSidebar from '@/components/layout/AppSidebar.vue'
import ItemList from '@/components/items/ItemList.vue'
import ReaderPane from '@/components/reader/ReaderPane.vue'
import NoteDialog from '@/components/modals/NoteDialog.vue'
import CategoryDialog from '@/components/modals/CategoryDialog.vue'
import ShortcutsDialog from '@/components/modals/ShortcutsDialog.vue'
import RadarDialog from '@/components/modals/RadarDialog.vue'
import SessionDialog from '@/components/modals/SessionDialog.vue'
import WatchDialog from '@/components/modals/WatchDialog.vue'
import ImportDialog from '@/components/modals/ImportDialog.vue'
import { Toaster } from '@/components/ui/sonner'
import { useMutations } from '@/composables/useMutations'


initTheme()

const items = useItemsStore()
const ui = useUiStore()
const signedIn = ref(false)
const isCheckingAuth = ref(true)
const credential = ref('')
const loginError = ref('')
const loggingIn = ref(false)

const STORAGE_KEY = 'omnikeep_api_key'
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
  items.stats = { inbox: 0, starred: 0, archived: 0, total: 0 }
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
    await items.refreshAll()
    await maybeShowSessionHint()
    await checkUrlParamIngest()
    return true
  } catch (error) {
    if (!isAuto) {
      requireLogin(true)
      loginError.value = error instanceof Error ? error.message : '登入失敗'
    } else {
      requireLogin(false)
    }
    return false
  } finally {
    loggingIn.value = false
  }
}


async function checkUrlParamIngest() {
  const params = new URLSearchParams(window.location.search)
  const incomingUrl = params.get('url')
  if (incomingUrl) {
    const autoClose = params.get('auto_close') === '1' || params.has('auto_close')
    window.history.replaceState({}, document.title, window.location.pathname)
    const { quickIngest } = useMutations()
    toast.info('偵測到隨手收錄網址，正在啟動多模態解析…')
    const ok = await quickIngest(incomingUrl)
    if (autoClose) {
      if (ok) {
        toast.success('收錄完成！視窗即將自動關閉…', { duration: 1200 })
        setTimeout(() => {
          window.close()
        }, 1200)
      } else {
        toast.error('收錄未完成，保留視窗以供檢視')
      }
    }
  }
}

async function bootstrapAuth() {
  isCheckingAuth.value = true
  try {
    // 1. Check local browser storage first
    const savedKey = localStorage.getItem(STORAGE_KEY)
    if (savedKey) {
      rememberKey.value = true
      const ok = await login(savedKey, true)
      if (ok) return
    }

    // 2. Local loopback auto-auth (zero friction for localhost)
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

// J/K navigation keeps the active row in view.
watch(
  () => ui.activeItem?.id,
  (id) => {
    if (id == null || items.viewMode !== 'list') return
    const idx = items.items.findIndex((i) => i.id === id)
    if (idx >= 0) listRef.value?.scrollToIndex(idx)
  },
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
    toast.info('提升 Reel / 社群內容解析成功率', {
      description: '偵測到尚未連結任何平台會話。登入一次 Instagram 或 Facebook，解析即可帶入會員狀態。',
      duration: 10000,
      action: {
        label: '前往設定',
        onClick: () => {
          ui.showSessionModal = true
        },
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
  bootstrapAuth()
})
onUnmounted(() => window.removeEventListener('omnikeep-auth-required', onAuthRequired))
</script>

<template>
  <!-- Liquid glass backdrop: colorful aurora the panels blur against -->
  <div class="aurora" aria-hidden="true">
    <i /><i /><i /><i />
  </div>

  <!-- Auth initializing spinner (avoids login modal flashing on localhost) -->
  <div v-if="isCheckingAuth" class="relative z-10 flex h-screen w-screen items-center justify-center">
    <div class="flex flex-col items-center gap-3">
      <div class="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
      <span class="text-xs text-muted-foreground tracking-wide">載入 OmniKeep...</span>
    </div>
  </div>

  <form v-else-if="!signedIn" class="relative z-10 mx-auto mt-24 flex max-w-sm flex-col gap-4 rounded-xl border bg-background p-8 text-foreground" @submit.prevent="login()">
    <h1 class="text-xl font-semibold">登入 OmniKeep</h1>
    <label for="api-key">存取金鑰</label>
    <input id="api-key" v-model="credential" type="password" autocomplete="off" required class="rounded border bg-background p-3" />
    
    <div class="flex items-center gap-2">
      <input
        id="remember-key"
        v-model="rememberKey"
        type="checkbox"
        class="h-4 w-4 rounded border-border text-primary focus:ring-primary cursor-pointer accent-primary"
      />
      <label for="remember-key" class="text-sm cursor-pointer select-none">
        記住金鑰（儲存於本機瀏覽器）
      </label>
    </div>

    <p class="text-sm text-muted-foreground">
      {{ rememberKey ? '金鑰將保存於本機 localStorage，下次開啟自動登入。' : '金鑰僅保留於本頁記憶體，重新整理後需再次登入。' }}
    </p>
    <p v-if="loginError" role="alert" class="text-sm text-red-500">{{ loginError }}</p>
    <button type="submit" :disabled="loggingIn" class="rounded bg-primary p-3 text-primary-foreground font-medium transition disabled:opacity-50">
      {{ loggingIn ? '驗證中…' : '登入' }}
    </button>
  </form>
  <div v-else class="relative z-10 flex h-screen w-screen overflow-hidden text-foreground">
    <!-- Collapsible Modern Sidebar -->
    <AppSidebar @logout="handleLogout" />

    <!-- Main Workspace (Top Header + Master Stream + Reader) -->
    <div class="flex min-w-0 flex-1 flex-col overflow-hidden">
      <AppHeader ref="headerRef" />

      <!-- Master–detail workbench body -->
      <div class="relative flex min-h-0 flex-1 overflow-hidden">
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
    <SessionDialog />
    <WatchDialog />
    <ImportDialog />
  </div>

  <Toaster />
</template>
