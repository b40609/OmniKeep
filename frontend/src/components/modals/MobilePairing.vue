<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import QRCode from 'qrcode'
import { toast } from 'vue-sonner'
import { Loader2, Smartphone } from 'lucide-vue-next'
import Button from '@/components/ui/button/Button.vue'
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

// Closing settings (or leaving this tab) drops the code rather than leaving it valid unseen.
onBeforeUnmount(() => {
  if (pairing.value) cancelPhonePairing().catch(() => undefined)
  stop()
})

const signedInTime = computed(() =>
  signedInAt.value ? new Date(signedInAt.value * 1000).toLocaleTimeString('zh-TW', { hour: '2-digit', minute: '2-digit' }) : '')
</script>

<template>
  <section class="space-y-2">
    <h3 class="flex items-center gap-1.5 text-xs font-semibold"><Smartphone class="size-3.5" /> 手機登入</h3>
    <p class="text-2xs text-muted-foreground">
      在手機上登入 OmniKeep，不必輸入 API 金鑰。配對碼 5 分鐘內有效、只能用一次，裡面不含金鑰。
    </p>

    <div v-if="pairing" class="space-y-3 rounded-lg border border-border p-3">
      <div class="flex flex-col items-center gap-3 sm:flex-row sm:items-start">
        <!-- QR codes need a light background to scan, in dark mode too. -->
        <div v-if="svg" class="size-44 shrink-0 rounded-md bg-white p-1.5 [&>svg]:size-full" role="img" aria-label="手機登入 QR code" v-html="svg" />
        <div v-else class="flex size-44 shrink-0 items-center justify-center rounded-md border border-dashed border-border p-3 text-center text-2xs text-muted-foreground">
          填入手機開啟 OmniKeep 的網址後顯示 QR code
        </div>
        <div class="min-w-0 flex-1 space-y-2 text-xs">
          <p class="text-2xs text-muted-foreground">配對碼（{{ countdown }} 後失效）</p>
          <p class="font-mono text-2xl font-semibold tracking-widest">{{ formatPairingCode(pairing.code) }}</p>
          <ol class="list-decimal space-y-1 pl-4 text-2xs text-muted-foreground">
            <li>用 iPhone 相機掃 QR code，會在 Safari 開啟並直接登入。</li>
            <li>加到主畫面的 OmniKeep App 和 Safari 不共用登入：在 App 的登入頁輸入上面的配對碼。兩邊都要的話，用完再產生一組。</li>
          </ol>
        </div>
      </div>
      <label class="block space-y-1">
        <span class="text-2xs text-muted-foreground">手機開啟 OmniKeep 的網址</span>
        <input
          v-model="address"
          list="phone-addresses"
          placeholder="https://你的電腦.你的-tailnet.ts.net"
          class="w-full rounded-md border border-border bg-background px-2.5 py-1.5 font-mono text-2xs focus:outline-none focus:ring-2 focus:ring-primary/40"
        />
        <datalist id="phone-addresses">
          <option v-for="a in addresses" :key="a" :value="a" />
        </datalist>
      </label>
      <p v-if="!addresses.length" class="text-2xs text-muted-foreground">
        找不到這台電腦的 Tailscale 網址。手機要和電腦在同一個 Tailscale 網路，電腦上啟用 <code>tailscale serve</code> 後再填入網址。
      </p>
      <div class="flex flex-wrap gap-2">
        <Button variant="secondary" size="sm" :disabled="busy" @click="start">重新產生</Button>
        <Button variant="ghost" size="sm" @click="cancel">取消</Button>
      </div>
    </div>

    <template v-else>
      <p v-if="signedInTime" class="text-2xs text-success">{{ signedInTime }} 有一支手機用配對碼登入了。</p>
      <Button variant="secondary" size="sm" :disabled="busy" @click="start">
        <Loader2 v-if="busy" class="size-3 animate-spin" />
        {{ signedInTime ? '再產生一組配對碼' : '產生手機登入 QR code' }}
      </Button>
    </template>
  </section>
</template>
