<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch, type Component } from 'vue'
import { useMediaQuery } from '@vueuse/core'
import { toast } from 'vue-sonner'
import {
  ArrowLeft, Bell, ChevronRight, Copy, Cpu, FlaskConical, HardDrive, Send, SlidersHorizontal, Wrench,
} from 'lucide-vue-next'
import ConfirmDialog from '@/components/ui/confirm/ConfirmDialog.vue'
import GeneralSection from './GeneralSection.vue'
import ChannelsSection from './ChannelsSection.vue'
import AiSection from './AiSection.vue'
import NotificationsSection from './NotificationsSection.vue'
import DataSection from './DataSection.vue'
import AdvancedSection from './AdvancedSection.vue'
import LabsSection from './LabsSection.vue'
import { provideSettingsForm } from '@/composables/useSettingsForm'
import { getApiKey } from '@/lib/api'
import { SETTINGS_SECTIONS, type SettingsSectionId } from '@/lib/settingsSections'
import { useUiStore } from '@/stores/ui'

/**
 * Settings as a full page over the workspace: groups on the left, the group's
 * settings on the right. On a phone the groups are a list of their own and a
 * group opens over it. Esc, the 返回 button and the browser's back all leave,
 * after asking when something typed has not been saved.
 */
const ui = useUiStore()
const form = provideSettingsForm()

const SECTION_VIEW: Record<SettingsSectionId, { icon: Component; view: Component }> = {
  general: { icon: SlidersHorizontal, view: GeneralSection },
  channels: { icon: Send, view: ChannelsSection },
  ai: { icon: Cpu, view: AiSection },
  notifications: { icon: Bell, view: NotificationsSection },
  data: { icon: HardDrive, view: DataSection },
  advanced: { icon: Wrench, view: AdvancedSection },
  labs: { icon: FlaskConical, view: LabsSection },
}
const current = computed(() => SETTINGS_SECTIONS.find((s) => s.id === ui.settingsTab) ?? SETTINGS_SECTIONS[0])

/* Phone: the list of groups first, unless a link asked for a particular group. */
const phone = useMediaQuery('(max-width: 767px)')
const level = computed({ get: () => ui.settingsLevel, set: (value) => (ui.settingsLevel = value) })
const main = ref<HTMLElement | null>(null)

function open(section: SettingsSectionId) {
  ui.settingsTab = section
  ui.settingsBlock = ''
  level.value = 'detail'
}

/** Bring the block a link named into view, once the section is drawn. */
async function reveal() {
  if (!form.snapshot.value) return
  await nextTick()
  const block = ui.settingsBlock
  ui.settingsBlock = ''
  const target = block ? document.getElementById(`settings-${block}`) : null
  if (target) target.scrollIntoView({ block: 'start' })
  else if (main.value) main.value.scrollTop = 0
}
watch(() => [ui.settingsTab, ui.settingsBlock, !!form.snapshot.value], ([, block], previous) => {
  // Only a new section or a named block moves the page; clearing the block must not.
  if (block || !previous || previous[0] !== ui.settingsTab || !previous[2]) void reveal()
})

/* Leaving */
const unsaved = computed(() => form.dirty.value || form.extraDirty.value)
const confirmingLeave = ref(false)
/** Our entry is on top of the browser history, so its back button closes the page. */
let inHistory = false

function close() {
  confirmingLeave.value = false
  ui.showSettingsModal = false
}

function requestClose() {
  if (unsaved.value) confirmingLeave.value = true
  else close()
}

function back() {
  if (phone.value && level.value === 'detail') level.value = 'list'
  else requestClose()
}

function pushHistory() {
  window.history.pushState({ ...window.history.state, omnikeepSettings: true }, '')
  inHistory = true
}

function onPopState() {
  if (!inHistory) return
  inHistory = false
  if (phone.value && level.value === 'detail') {
    level.value = 'list'
    pushHistory()
  } else if (unsaved.value) {
    pushHistory()
    confirmingLeave.value = true
  } else {
    close()
  }
}

watch(() => ui.settingsCloseRequests, back)

onMounted(() => {
  void form.refresh()
  pushHistory()
  window.addEventListener('popstate', onPopState)
})
onBeforeUnmount(() => {
  window.removeEventListener('popstate', onPopState)
  // Closed from the page itself: take our entry off the history again.
  if (inHistory && window.history.state?.omnikeepSettings) window.history.back()
})

/* Switching 這台電腦免登入 off: the owner gets the key first, or this computer is locked out next time. */
const shownKey = ref('')
async function copyAccessKey() {
  const key = getApiKey()
  try {
    await navigator.clipboard.writeText(key)
    toast.success('已複製存取金鑰')
  } catch {
    // No clipboard access (not a secure context, or permission refused): show it for copying by hand.
    shownKey.value = key
  }
}
function cancelLocalLogin() {
  shownKey.value = ''
  form.cancelLocalLogin()
}
async function confirmLocalLogin() {
  await form.confirmLocalLogin()
  if (!form.localLoginPending.value) shownKey.value = ''
}
</script>

<template>
  <div
    class="settings"
    :class="phone ? (level === 'list' ? 'settings--list' : 'settings--detail') : undefined"
    role="region"
    aria-label="設定"
  >
    <header class="settings__top">
      <button v-if="phone" type="button" class="icon-button" :aria-label="level === 'detail' ? '回到設定' : '返回'" @click="back"><ArrowLeft /></button>
      <button v-else type="button" class="set-button set-button--text" title="返回　Esc" @click="back"><ArrowLeft aria-hidden="true" />返回</button>
      <h1>{{ phone && level === 'detail' ? current.label : '設定' }}</h1>
    </header>

    <div class="settings__body">
      <nav class="settings__nav" aria-label="設定分組">
        <template v-for="section in SETTINGS_SECTIONS" :key="section.id">
          <div v-if="section.id === 'labs'" class="nav-divider" />
          <button
            type="button"
            class="nav-row"
            :aria-current="!phone && ui.settingsTab === section.id ? 'page' : undefined"
            @click="open(section.id)"
          >
            <component :is="SECTION_VIEW[section.id].icon" aria-hidden="true" />
            <span class="nav-row__label">{{ section.label }}</span>
            <ChevronRight v-if="phone" class="!size-5 text-muted-foreground" aria-hidden="true" />
          </button>
        </template>
      </nav>

      <main ref="main" class="settings__main">
        <div class="settings__content">
          <h2 class="settings__title">{{ current.label }}</h2>
          <p class="settings__lead">{{ current.lead }}</p>

          <div v-if="form.loadError.value" class="mt-6 space-y-3">
            <p class="set-notice set-notice--bad" role="alert">無法讀取設定：{{ form.loadError.value }}</p>
            <button type="button" class="set-button" @click="form.refresh()">再試一次</button>
          </div>
          <p v-else-if="!form.snapshot.value" class="set-text mt-6">讀取中…</p>

          <template v-else>
            <p v-if="form.unreadable.value.length" class="set-notice set-notice--bad mt-6" role="alert">
              有 {{ form.unreadable.value.length }} 個金鑰無法解密（{{ form.snapshot.value.secret_key.exists ? '主金鑰和當初加密時不同' : '找不到主金鑰' }}）。請重新輸入：{{ form.unreadable.value.join('、') }}。
            </p>
            <KeepAlive include="AiSection">
              <component :is="SECTION_VIEW[current.id].view" :key="current.id" />
            </KeepAlive>
          </template>
        </div>
      </main>
    </div>

    <ConfirmDialog
      :open="confirmingLeave"
      title="還有變更沒儲存"
      description="現在離開，剛才輸入的內容不會保留。"
      confirm-label="放棄變更"
      cancel-label="繼續編輯"
      danger
      @update:open="confirmingLeave = $event"
      @confirm="close"
    />

    <ConfirmDialog
      :open="!!form.localLoginPending.value"
      title="關閉這台電腦的免登入？"
      description="關閉後，在這台電腦開啟 OmniKeep 也要輸入存取金鑰或配對碼。先複製存取金鑰，存到密碼管理工具之類安全的地方；沒有金鑰，登出或清除瀏覽資料之後就進不來。"
      confirm-label="關閉免登入"
      danger
      @update:open="(open: boolean) => { if (!open) cancelLocalLogin() }"
      @confirm="confirmLocalLogin"
    >
      <div class="mt-4 space-y-3">
        <button type="button" class="set-button" @click="copyAccessKey"><Copy aria-hidden="true" />複製存取金鑰</button>
        <template v-if="shownKey">
          <p class="set-notice set-notice--warn">這個瀏覽器不允許自動複製，請手動選取下面的金鑰並複製。</p>
          <input :value="shownKey" readonly aria-label="存取金鑰" class="set-input set-mono" @focus="($event.target as HTMLInputElement).select()">
        </template>
        <p class="set-text">另一個方法：在還登入著的裝置開啟「設定 › 收錄管道 › 手機登入」產生配對碼，在登入頁輸入配對碼也能登入。</p>
      </div>
    </ConfirmDialog>
  </div>
</template>
