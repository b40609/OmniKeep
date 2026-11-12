<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { toast } from 'vue-sonner'
import Switch from '@/components/ui/switch/Switch.vue'
import SettingBlock from './SettingBlock.vue'
import SettingRow from './SettingRow.vue'
import { getPushConfig, sendTestPush, subscribePush, unsubscribePush } from '@/lib/api'
import { pushEnvironment, sameKey, urlBase64ToUint8Array } from '@/lib/push'
import { useUiStore } from '@/stores/ui'

/** Web Push for this device: each device is switched on by itself. */
const ui = useUiStore()

type State = 'loading' | 'unsupported' | 'needs-install' | 'no-sw' | 'unconfigured' | 'denied' | 'off' | 'on' | 'error'
const state = ref<State>('loading')
const busy = ref(false)
const errorText = ref('')

let registration: ServiceWorkerRegistration | null = null
let serverKey: Uint8Array | null = null

function message(e: unknown) {
  return e instanceof Error ? e.message : String(e)
}

async function refresh() {
  state.value = 'loading'
  const env = pushEnvironment()
  if (env.iosNeedsInstall) return void (state.value = 'needs-install')
  if (!env.supported) return void (state.value = 'unsupported')
  try {
    const config = await getPushConfig()
    if (!config.configured) return void (state.value = 'unconfigured')
    serverKey = urlBase64ToUint8Array(config.public_key)
    registration = (await navigator.serviceWorker.getRegistration('/')) ?? null
    if (!registration) return void (state.value = 'no-sw')

    let sub = await registration.pushManager.getSubscription()
    if (sub && !sameKey(sub.options.applicationServerKey, serverKey)) {
      // The server's VAPID key changed; this subscription can never be delivered to.
      await sub.unsubscribe()
      sub = null
    }
    if (sub) await subscribePush(sub.toJSON()) // re-register in case the server lost it
    state.value = Notification.permission === 'denied' ? 'denied' : sub ? 'on' : 'off'
  } catch (e) {
    errorText.value = message(e)
    state.value = 'error'
  }
}

// Apple requires subscribe() to run straight from the tap handler, so nothing is awaited before it.
function enable() {
  if (!registration || !serverKey || busy.value) return
  busy.value = true
  registration.pushManager
    .subscribe({ userVisibleOnly: true, applicationServerKey: serverKey as BufferSource })
    .then((sub) => subscribePush(sub.toJSON()))
    .then(() => {
      state.value = 'on'
      toast.success('這台裝置已開啟通知')
    })
    .catch((e) => {
      if (Notification.permission === 'denied') state.value = 'denied'
      toast.error('無法開啟通知', { description: message(e) })
    })
    .finally(() => (busy.value = false))
}

async function disable() {
  if (!registration || busy.value) return
  busy.value = true
  try {
    const sub = await registration.pushManager.getSubscription()
    if (sub) {
      await unsubscribePush(sub.endpoint).catch(() => {})
      await sub.unsubscribe()
    }
    state.value = 'off'
    toast.success('這台裝置已關閉通知')
  } catch (e) {
    toast.error('無法關閉通知', { description: message(e) })
  } finally {
    busy.value = false
  }
}

async function test() {
  busy.value = true
  try {
    const res = await sendTestPush()
    if (res.sent > 0) toast.success(`已送出測試通知到 ${res.sent} 台裝置`)
    else toast.error('沒有送達任何裝置', { description: `失敗 ${res.failed}、已失效移除 ${res.removed}` })
  } catch (e) {
    toast.error('測試通知失敗', { description: message(e) })
  } finally {
    busy.value = false
  }
}

/** Why the switch is not available, when it is not. */
const blocked = computed(() => {
  switch (state.value) {
    case 'needs-install':
      return 'iPhone 和 iPad 要先把 OmniKeep 加到主畫面才能收通知（iOS 16.4 以上）。在 Safari 點分享、選「加入主畫面」，再從主畫面開啟後回到這裡。'
    case 'unsupported': return '這個瀏覽器不支援網頁通知。'
    case 'no-sw': return '這個網址還不能收通知：要用正式建置的版本，並透過 HTTPS 或 localhost 開啟。'
    case 'unconfigured': return '伺服器還沒有可用的推播金鑰。通常啟動時會自動產生；一直看到這段的話，到「進階」查看推播金鑰。'
    case 'denied': return '這個網站的通知被封鎖了。到瀏覽器或系統的通知設定允許 OmniKeep 後再試。'
    case 'error': return `無法讀取通知狀態：${errorText.value}`
    default: return ''
  }
})

onMounted(refresh)
</script>

<template>
  <SettingBlock id="device" title="這台裝置" description="每台裝置要各自開啟。">
    <SettingRow name="推播通知" help="收到探索的精選和自動加星的收藏時通知這台裝置，依探索設定的通知方式。" for="setting-push">
      <template #below>
        <p v-if="blocked" class="set-notice mt-2" :class="{ 'set-notice--bad': state === 'error' }">{{ blocked }}</p>
        <button v-if="state === 'unconfigured'" type="button" class="set-button mt-3" @click="ui.openSettings('advanced', '', 'push-keys')">查看推播金鑰</button>
      </template>
      <span v-if="state === 'loading'" class="set-note">檢查中…</span>
      <Switch
        v-else
        id="setting-push"
        :model-value="state === 'on'"
        :disabled="busy || (state !== 'on' && state !== 'off')"
        @update:model-value="$event ? enable() : disable()"
      />
    </SettingRow>
    <SettingRow v-if="state === 'on'" name="測試通知" help="送一則測試通知到所有已開啟的裝置。">
      <button type="button" class="set-button" :disabled="busy" @click="test">傳送</button>
    </SettingRow>
  </SettingBlock>
</template>
