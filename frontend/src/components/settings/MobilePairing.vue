<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import QRCode from 'qrcode'
import { toast } from 'vue-sonner'
import { Loader2 } from 'lucide-vue-next'
import SettingBlock from './SettingBlock.vue'
import SettingRow from './SettingRow.vue'
import { cancelPhonePairing, createPhonePairing, getPhonePairing, type PhonePairing } from '@/lib/api'
import { formatPairingCode, pairingLink, phoneAddresses } from '@/lib/pairing'

/** Signs a phone in with a one-time code: a QR code for Safari, the same code typed in the home-screen app. */
const pairing = ref<PhonePairing | null>(null)
const address = ref('')
const addresses = ref<string[]>([])
const svg = ref('')
const busy = ref(false)
const secondsLeft = ref(0)
const signedInAt = ref(0)
let timer: ReturnType<typeof setInterval> | undefined

const link = computed(() => (pairing.value && address.value.trim() ? pairingLink(address.value, pairing.value.code) : ''))
const countdown = computed(() => `${Math.floor(secondsLeft.value / 60)}:${String(secondsLeft.value % 60).padStart(2, '0')}`)

watch(link, async (value) => {
  svg.value = value ? await QRCode.toString(value, { type: 'svg', errorCorrectionLevel: 'M', margin: 1 }) : ''
})

function stop() {
  if (timer) clearInterval(timer)
  timer = undefined
  pairing.value = null
}

async function tick() {
  if (!pairing.value) return
  secondsLeft.value = Math.max(0, Math.round(pairing.value.expires_at - Date.now() / 1000))
  if (secondsLeft.value === 0) {
    stop()
    toast.info('配對碼已過期，需要時再產生一組')
    return
  }
  try {
    const status = await getPhonePairing()
    if (status.used_at) {
      signedInAt.value = status.used_at
      stop()
      toast.success('手機已登入 OmniKeep')
    } else if (!status.active) {
      stop()  // replaced or dropped after wrong tries
    }
  } catch {
    /* a missed poll is fine: the next one tries again */
  }
}

async function start() {
  busy.value = true
  try {
    pairing.value = await createPhonePairing()
    addresses.value = phoneAddresses(pairing.value.phone_urls, window.location)
    if (!addresses.value.includes(address.value)) address.value = addresses.value[0] ?? ''
    signedInAt.value = 0
    secondsLeft.value = pairing.value.ttl
    if (timer) clearInterval(timer)
    timer = setInterval(tick, 2000)
  } catch (e) {
    toast.error('無法產生配對碼', { description: e instanceof Error ? e.message : String(e) })
  } finally {
    busy.value = false
  }
}

async function cancel() {
  stop()
  await cancelPhonePairing().catch(() => undefined)
}

// Closing settings (or leaving this section) drops the code rather than leaving it valid unseen.
onBeforeUnmount(() => {
  if (pairing.value) cancelPhonePairing().catch(() => undefined)
  stop()
})

const signedInTime = computed(() =>
  signedInAt.value ? new Date(signedInAt.value * 1000).toLocaleTimeString('zh-TW', { hour: '2-digit', minute: '2-digit' }) : '')
</script>

<template>
  <SettingBlock id="phone" title="手機登入">
    <SettingRow name="用配對碼登入手機" help="不用在手機上輸入存取金鑰。配對碼 5 分鐘內有效、只能用一次，裡面不含金鑰。">
      <template v-if="signedInTime" #below>
        <p class="set-note set-note--ok mt-1" role="status">{{ signedInTime }} 有一支手機用配對碼登入了。</p>
      </template>
      <button v-if="!pairing" type="button" class="set-button" :disabled="busy" @click="start">
        <Loader2 v-if="busy" class="animate-spin" aria-hidden="true" />
        {{ signedInTime ? '再產生一組' : '產生配對碼' }}
      </button>
    </SettingRow>

    <div v-if="pairing" class="set-row set-row--stacked">
      <div class="flex flex-col items-center gap-6 sm:flex-row sm:items-start">
        <!-- QR codes need a light background to scan, in dark mode too. -->
        <div v-if="svg" class="size-44 shrink-0 rounded-lg bg-white p-2 [&>svg]:size-full" role="img" aria-label="手機登入 QR code" v-html="svg" />
        <div v-else class="set-panel flex size-44 shrink-0 items-center justify-center text-center text-sm text-muted-foreground">
          填入手機開啟 OmniKeep 的網址後顯示 QR code
        </div>
        <div class="min-w-0 flex-1 space-y-2">
          <p class="text-xs text-muted-foreground">配對碼，{{ countdown }} 後失效</p>
          <p class="font-mono text-2xl font-semibold tracking-widest">{{ formatPairingCode(pairing.code) }}</p>
          <ol class="set-text list-decimal space-y-1 pl-5">
            <li>用 iPhone 相機掃 QR code，會在 Safari 開啟並直接登入。</li>
            <li>加到主畫面的 OmniKeep 和 Safari 不共用登入：在它的登入頁輸入上面的配對碼。兩邊都要的話，用完再產生一組。</li>
          </ol>
        </div>
      </div>
      <div class="max-w-[560px]">
        <label for="phone-address" class="set-label">手機開啟 OmniKeep 的網址</label>
        <input id="phone-address" v-model="address" list="phone-addresses" placeholder="https://你的電腦.你的-tailnet.ts.net" class="set-input set-mono">
        <datalist id="phone-addresses">
          <option v-for="a in addresses" :key="a" :value="a" />
        </datalist>
        <p v-if="!addresses.length" class="set-text mt-2">
          找不到這台電腦的 Tailscale 網址。手機要和電腦在同一個 Tailscale 網路，電腦上啟用 <code>tailscale serve</code> 後再填入網址。
        </p>
      </div>
      <div class="flex flex-wrap gap-2">
        <button type="button" class="set-button" :disabled="busy" @click="start">重新產生</button>
        <button type="button" class="set-button set-button--text" @click="cancel">取消</button>
      </div>
    </div>
  </SettingBlock>
</template>
