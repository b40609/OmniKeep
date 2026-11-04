<script setup lang="ts">
import { ref, watch } from 'vue'
import { toast } from 'vue-sonner'
import { BellRing } from 'lucide-vue-next'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import Button from '@/components/ui/button/Button.vue'
import { getPushConfig, sendTestPush, subscribePush, unsubscribePush } from '@/lib/api'
import { pushEnvironment, sameKey, urlBase64ToUint8Array } from '@/lib/push'
import { useUiStore } from '@/stores/ui'
import TelegramPairing from './TelegramPairing.vue'

/** Per-device Web Push opt-in, plus binding the Telegram account notifications also go to. */
const ui = useUiStore()
const telegram = ref<InstanceType<typeof TelegramPairing> | null>(null)

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
      toast.success('這台裝置已開啟推播')
    })
    .catch((e) => {
      if (Notification.permission === 'denied') state.value = 'denied'
      toast.error('開啟推播失敗', { description: message(e) })
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
    toast.success('這台裝置已關閉推播')
  } catch (e) {
    toast.error('關閉推播失敗', { description: message(e) })
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

function openPushSettings() {
  ui.showPushModal = false
  ui.openSettings('push')
}

watch(
  () => ui.showPushModal,
  (open) => {
    if (open) {
      refresh()
      telegram.value?.refresh()
    }
  },
)
</script>

<template>
  <Dialog :open="ui.showPushModal" @update:open="(v) => (ui.showPushModal = v)">
    <DialogContent class="max-w-md">
      <DialogHeader>
        <DialogTitle class="flex items-center gap-2"><BellRing class="size-4" /> 推播通知</DialogTitle>
        <DialogDescription class="text-xs">
          在這台裝置接收雷達戰報與雷達自動收藏通知（依雷達設定的通知模式）。每台裝置要各自開啟；Telegram 通知不受影響。
        </DialogDescription>
      </DialogHeader>

      <div class="space-y-3 text-sm">
        <p v-if="state === 'loading'" class="text-muted-foreground">檢查中…</p>

        <p v-else-if="state === 'needs-install'" class="text-muted-foreground">
          iPhone、iPad 只有加到主畫面的網頁 App 能收推播（iOS 16.4 以上）。請在 Safari 點分享 →「加入主畫面」，再從主畫面圖示開啟 OmniKeep 後回到這裡。
        </p>

        <p v-else-if="state === 'unsupported'" class="text-muted-foreground">這個瀏覽器不支援網頁推播。</p>

        <p v-else-if="state === 'no-sw'" class="text-muted-foreground">
          Service Worker 尚未啟用。請用建置後的版本（<code>npm run build</code>），並透過 HTTPS 或 localhost 開啟。
        </p>

        <div v-else-if="state === 'unconfigured'" class="space-y-2">
          <p class="text-muted-foreground">
            伺服器還沒有可用的推播金鑰。OmniKeep 啟動時會自動產生；如果一直看到這段，可能是主金鑰換過而無法解密，請到「設定 › 推播」查看或重新產生。
          </p>
          <Button variant="secondary" size="sm" @click="openPushSettings">開啟推播設定</Button>
        </div>

        <p v-else-if="state === 'denied'" class="text-muted-foreground">
          這個網站的通知已被封鎖。請到瀏覽器或系統的通知設定允許 OmniKeep 後再試。
        </p>

        <p v-else-if="state === 'error'" class="text-danger">無法讀取推播狀態：{{ errorText }}</p>

        <template v-else>
          <p :class="state === 'on' ? 'text-success' : 'text-muted-foreground'">
            {{ state === 'on' ? '這台裝置已開啟推播。' : '這台裝置尚未開啟推播。' }}
          </p>
          <div class="flex flex-wrap gap-2">
            <Button v-if="state === 'off'" :disabled="busy" @click="enable">開啟這台裝置的推播</Button>
            <template v-else>
              <Button variant="secondary" :disabled="busy" @click="test">傳送測試通知</Button>
              <Button variant="ghost" :disabled="busy" @click="disable">關閉推播</Button>
            </template>
          </div>
        </template>
      </div>

      <TelegramPairing ref="telegram" />
    </DialogContent>
  </Dialog>
</template>
