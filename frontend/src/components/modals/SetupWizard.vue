<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { toast } from 'vue-sonner'
import { Sparkles, PlugZap, Loader2, CircleCheck, CircleAlert, ExternalLink, Check, KeyRound } from 'lucide-vue-next'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import Button from '@/components/ui/button/Button.vue'
import TelegramGuide from '@/components/settings/TelegramGuide.vue'
import TelegramPairing from '@/components/settings/TelegramPairing.vue'
import ProviderPicker from '@/components/settings/ProviderPicker.vue'
import {
  createAiConnection, getAiCatalog, getAiFeatures, getServiceStatus, getStats, getTelegramStatus, saveSettings,
  startOpenRouterOAuth, testAiDraft,
  type AiCard, type AiCardGroup, type AiFeature, type AiRecommendation, type AiTestResult, type TelegramStatus,
} from '@/lib/api'
import { callbackUrlFromLocation, savePendingOpenRouterOAuth } from '@/lib/openrouterOAuth'
import {
  cardById, connectionDraft, formProblem, guideStart, initialForm, sameValues, type ConnectionDraft, type SetupForm,
} from '@/lib/setup'
import { TELEGRAM_TOKEN_EXAMPLE, tokenProblem } from '@/lib/telegramGuide'
import { useUiStore } from '@/stores/ui'

/**
 * First-run guide: connect an AI service, then Telegram, so the first link can be sent
 * from the phone. Both parts can be skipped: a link is kept without an AI (it is analysed
 * once one is connected), and Telegram can be set up later in 設定 › 收錄管道.
 * Nothing is preselected; the suggested combo comes first, every service folded under its kind of free.
 *
 * A new install already has the no-signup services connected (app/ai_connections.py STARTER_CARDS),
 * so on a first visit to an empty library the guide opens at a welcome instead: what works now and
 * how well, then Telegram, then the first link. It is shown once per browser.
 */
const ui = useUiStore()
const LATER_KEY = 'omnikeep-setup-later'
const WELCOMED_KEY = 'omnikeep-welcomed'

type Step = 'welcome' | 'choose' | 'connect' | 'telegram' | 'done'
const step = ref<Step>('choose')
const cards = ref<AiCard[]>([])
const cardGroups = ref<AiCardGroup[]>([])
const recommended = ref<AiRecommendation[]>([])
const catalogError = ref('')
const cardId = ref('')
const form = reactive<SetupForm>({ baseUrl: '', apiKey: '', model: '' })
const testing = ref(false)
const saving = ref(false)
const oauthStarting = ref(false)
const result = ref<AiTestResult | null>(null)
const testedValues = ref<ConnectionDraft | null>(null)
/** An AI connection was saved in this run of the guide. */
const aiSaved = ref(false)

const card = computed<AiCard | undefined>(() => cardById(cards.value, cardId.value))
const values = computed(() => (card.value ? connectionDraft(card.value, form) : null))
const problem = computed(() => (card.value ? formProblem(card.value, form) : '請先選一個服務商'))
const canSave = computed(() => !!result.value?.ok && !!values.value && sameValues(testedValues.value, values.value) && !saving.value)
const modelChoices = computed(() => [...new Set([...(card.value?.models ?? []), ...(result.value?.models ?? [])])].slice(0, 200))
/** The AI was already connected when the guide opened: it starts at the welcome. */
const welcomeMode = ref(false)
/** Where the guide opens next time it is shown. */
const opening = ref<Step>('choose')
const features = ref<AiFeature[]>([])
const FEATURE_LEVEL = { good: '能用', basic: '基本', off: '沒開' } as const
const SETUP_STEPS: { id: Step; label: string }[] = [
  { id: 'choose', label: '選 AI 服務' },
  { id: 'connect', label: '連線與測試' },
  { id: 'telegram', label: '接上 Telegram' },
  { id: 'done', label: '完成' },
]
const WELCOME_STEPS: { id: Step; label: string }[] = [
  { id: 'welcome', label: 'AI 已接好' },
  { id: 'telegram', label: '接上 Telegram' },
  { id: 'done', label: '丟第一個連結' },
]
const STEPS = computed(() => (welcomeMode.value ? WELCOME_STEPS : SETUP_STEPS))
const stepIndex = computed(() => STEPS.value.findIndex((s) => s.id === step.value))
/** An AI is usable: connected before the guide opened, or saved in it. */
const aiReady = computed(() => welcomeMode.value || aiSaved.value)
/** An earlier step shows a tick only when it was really done, not when it was skipped. */
function stepDone(index: number): boolean {
  if (index >= stepIndex.value) return false
  return STEPS.value[index].id === 'telegram' ? telegramBound.value : aiReady.value
}

async function loadFeatures() {
  try {
    features.value = (await getAiFeatures()).features
  } catch {
    features.value = []
  }
}

function choose(id: string) {
  cardId.value = id
  const chosen = card.value
  if (chosen) Object.assign(form, initialForm(chosen))
  result.value = null
  testedValues.value = null
}

// Any edit after a test means the result no longer describes what would be saved.
watch(values, (now) => {
  if (testedValues.value && now && !sameValues(testedValues.value, now)) result.value = null
})

async function loadCatalog() {
  if (cards.value.length) return
  catalogError.value = ''
  try {
    const catalog = await getAiCatalog()
    cards.value = catalog.cards
    cardGroups.value = catalog.groups ?? []
    recommended.value = catalog.recommended ?? []
  } catch (e) {
    catalogError.value = e instanceof Error ? e.message : String(e)
  }
}

async function test() {
  if (problem.value || testing.value || !values.value) return
  testing.value = true
  result.value = null
  const tested = { ...values.value }
  try {
    result.value = await testAiDraft(tested)
  } catch (e) {
    result.value = { ok: false, status: null, message: e instanceof Error ? e.message : String(e), detail: '' }
  } finally {
    testedValues.value = tested
    testing.value = false
  }
}

async function save() {
  if (!canSave.value || !values.value) return
  saving.value = true
  try {
    await createAiConnection({ ...values.value, slot: 'analysis' })
    ui.settingsVersion++
    form.apiKey = ''
    aiSaved.value = true
    step.value = 'telegram'
  } catch (e) {
    toast.error('儲存失敗', { description: e instanceof Error ? e.message : String(e) })
  } finally {
    saving.value = false
  }
}

async function startOpenRouterLogin() {
  if (!card.value || card.value.oauth !== 'openrouter' || oauthStarting.value) return
  oauthStarting.value = true
  try {
    const started = await startOpenRouterOAuth({
      callback_url: callbackUrlFromLocation(window.location),
      slot: 'analysis',
    })
    savePendingOpenRouterOAuth(sessionStorage, {
      state: started.state,
      createdAt: Date.now(),
      source: 'wizard',
      mode: 'new',
      model: form.model.trim() || undefined,
      slot: 'analysis',
    })
    window.location.assign(started.auth_url)
  } catch (e) {
    toast.error('無法開始 OpenRouter 登入', { description: e instanceof Error ? e.message : String(e) })
    oauthStarting.value = false
  }
}

/* ---------------- Telegram ---------------- */

const telegram = ref<TelegramStatus | null>(null)
const telegramError = ref('')
const token = ref('')
const tokenSaving = ref(false)
const tokenError = ref('')
const pairing = ref<InstanceType<typeof TelegramPairing> | null>(null)
const tokenHint = computed(() => tokenProblem(token.value))
const telegramBound = computed(() => !!telegram.value?.bound_user_ids.length)

async function loadTelegram() {
  telegramError.value = ''
  try {
    telegram.value = await getTelegramStatus()
  } catch (e) {
    telegramError.value = e instanceof Error ? e.message : String(e)
  }
}

async function saveToken() {
  const value = token.value.trim()
  if (!value || tokenSaving.value) return
  tokenSaving.value = true
  tokenError.value = ''
  try {
    await saveSettings({ TELEGRAM_BOT_TOKEN: value })
    token.value = ''
    ui.settingsVersion++
    await loadTelegram()
    await pairing.value?.refresh()
  } catch (e) {
    tokenError.value = e instanceof Error ? e.message : String(e)
  } finally {
    tokenSaving.value = false
  }
}

/** The pairing component re-read the bound accounts (after "我綁好了"). */
function onPaired(boundIds: number[]) {
  if (telegram.value) telegram.value = { ...telegram.value, bound_user_ids: boundIds }
}

watch(step, (now) => {
  if (now === 'telegram') void loadTelegram()
})

/* ---------------- Opening and closing ---------------- */

function later() {
  try {
    sessionStorage.setItem(LATER_KEY, '1')
  } catch {
    /* private mode */
  }
  ui.showSetupWizard = false
}

function openFullSettings() {
  ui.showSetupWizard = false
  ui.openSettings(aiReady.value ? 'channels' : 'ai')
}

/** 設定 › AI, where every feature lists the one step that makes it better. */
function openUpgrades() {
  ui.showSetupWizard = false
  ui.openSettings('ai', '', 'features')
}

function addFirstLink() {
  ui.showSetupWizard = false
  ui.openAdd()
}

function onOpenChange(open: boolean) {
  if (open) return
  if (step.value === 'done') ui.showSetupWizard = false
  else later()
}

watch(
  () => ui.showSetupWizard,
  (open) => {
    if (!open) {
      // Seen once is enough: closing it any way at all counts.
      if (welcomeMode.value) {
        try {
          localStorage.setItem(WELCOMED_KEY, '1')
        } catch {
          /* private mode */
        }
      }
      return
    }
    welcomeMode.value = opening.value === 'welcome'
    step.value = opening.value
    opening.value = 'choose'
    aiSaved.value = false
    if (welcomeMode.value) void loadFeatures()
    else loadCatalog()
    if (cardId.value) choose(cardId.value)
  },
)

function stored(storage: () => Storage, key: string): boolean {
  try {
    return !!storage().getItem(key)
  } catch {
    return false // private mode: show it anyway
  }
}

onMounted(async () => {
  const later = stored(() => sessionStorage, LATER_KEY)
  if (later) return
  try {
    const status = await getServiceStatus()
    let total: number | null = null
    if (!status.needs_setup) {
      try {
        total = (await getStats()).total
      } catch {
        total = null
      }
    }
    // A key that cannot be decrypted is a different problem; the banner explains that one.
    const start = guideStart({
      needsSetup: status.needs_setup,
      undecryptable: status.undecryptable.length,
      total,
      welcomed: stored(() => localStorage, WELCOMED_KEY),
      later,
      settingsOpen: ui.showSettingsModal,
    })
    if (start) {
      opening.value = start
      ui.showSetupWizard = true
    }
  } catch {
    /* offline or signed out */
  }
})
</script>

<template>
  <Dialog :open="ui.showSetupWizard" @update:open="onOpenChange">
    <DialogContent class="flex max-h-[90vh] max-w-2xl flex-col gap-0 overflow-hidden p-0">
      <div class="flex shrink-0 items-start gap-3 border-b border-border p-5 pb-4">
        <div class="flex size-10 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground">
          <Sparkles class="size-5" aria-hidden="true" />
        </div>
        <DialogHeader>
          <DialogTitle>{{ welcomeMode ? '歡迎使用 OmniKeep' : '開始使用 OmniKeep' }}</DialogTitle>
          <DialogDescription v-if="welcomeMode" class="text-sm">
            在 Telegram 把連結傳給機器人，OmniKeep 幫你讀完、寫成摘要，之後搜尋就找得到。AI 已經自動接好，接下來接上 Telegram，再丟第一個連結。
          </DialogDescription>
          <DialogDescription v-else class="text-sm">
            在 Telegram 把連結傳給機器人，OmniKeep 幫你讀完、寫成摘要，之後搜尋就找得到。先接上 AI，再接上 Telegram；兩步都可以略過，之後在「設定」補。
          </DialogDescription>
        </DialogHeader>
      </div>

      <ol class="flex shrink-0 flex-wrap items-center gap-x-2 gap-y-1 border-b border-border px-5 py-3 text-sm" aria-label="設定步驟">
        <li
          v-for="(s, i) in STEPS"
          :key="s.id"
          class="flex items-center gap-2"
          :class="i === stepIndex ? 'font-semibold text-foreground' : 'text-muted-foreground'"
          :aria-current="i === stepIndex ? 'step' : undefined"
        >
          <span
            class="flex size-6 items-center justify-center rounded-full border text-xs tabular-nums"
            :class="stepDone(i) ? 'border-primary bg-primary text-primary-foreground' : i === stepIndex ? 'border-primary text-foreground' : 'border-border'"
          >
            <Check v-if="stepDone(i)" class="size-3.5" aria-hidden="true" />
            <template v-else>{{ i + 1 }}</template>
          </span>
          <!-- A phone has room for the current step's name only -->
          <span :class="i === stepIndex ? '' : 'max-sm:sr-only'">{{ s.label }}</span>
          <span v-if="i < STEPS.length - 1" class="mx-1 h-px w-4 bg-border sm:w-6" aria-hidden="true" />
        </li>
      </ol>

      <div class="min-h-0 flex-1 space-y-4 overflow-y-auto p-5 text-sm">
        <!-- 0. The no-signup services are connected already: what works now, and how well -->
        <template v-if="step === 'welcome'">
          <p class="set-notice set-notice--ok flex items-start gap-2">
            <CircleCheck class="mt-0.5 size-4 shrink-0" aria-hidden="true" />
            <span>AI 已經自動接好：用不必註冊的免費服務，新的收藏會自動寫摘要和分類，不用先申請任何帳號。</span>
          </p>
          <div v-if="features.length">
            <p class="set-label">目前能用的功能</p>
            <ul class="divide-y divide-border rounded-lg border border-border">
              <li v-for="f in features" :key="f.id" class="flex items-start justify-between gap-3 px-3 py-2.5">
                <span class="min-w-0">
                  <span class="block font-medium text-foreground">{{ f.name }}</span>
                  <span class="block text-muted-foreground [overflow-wrap:anywhere]">{{ f.now }}</span>
                </span>
                <span class="set-status shrink-0" :class="{ 'set-status--ok': f.level === 'good' }">{{ FEATURE_LEVEL[f.level] }}</span>
              </li>
            </ul>
          </div>
          <p class="set-text">
            現在就能用。哪一項想要更好，「設定 › AI」有每一項的升級方法，例如申請免費的 Google AI Studio 金鑰，分析會更完整。
          </p>
        </template>

        <!-- 1. Choose a provider card -->
        <template v-else-if="step === 'choose'">
          <p v-if="catalogError" class="set-error">無法讀取服務商清單：{{ catalogError }}</p>
          <p v-else-if="!cards.length" class="set-text">讀取中…</p>
          <p v-else class="set-text">
            AI 用來幫收藏寫摘要和分類。先接建議的第 1 條；其他幾條之後到「設定 › AI」加成備援，或從下面的分組挑別家。
          </p>
          <div role="radiogroup" aria-label="AI 服務商">
            <ProviderPicker radio :cards="cards" :groups="cardGroups" :recommended="recommended" :selected="cardId" @pick="choose" />
          </div>
          <p v-if="cards.length" class="set-text">限額以服務商後台為準。不確定選哪個，可以請你的 Claude、Codex 或 Antigravity 依你的狀況說明。</p>
        </template>

        <!-- 2. Address, key, model, then test -->
        <template v-else-if="step === 'connect' && card">
          <div class="space-y-1 text-sm text-muted-foreground">
            <p><span class="font-semibold text-foreground">{{ card.label }}</span>：{{ card.limits }}</p>
            <p v-if="card.notes">{{ card.notes }}</p>
          </div>

          <div v-if="card.kind !== 'gemini'">
            <label for="setup-url" class="set-label">API 位址</label>
            <input
              id="setup-url"
              v-model="form.baseUrl"
              type="url"
              spellcheck="false"
              placeholder="https://…/v1"
              :readonly="!card.editable_url"
              class="set-input w-full"
            >
            <p v-if="card.kind === 'ollama'" class="set-text mt-2">
              Ollama 裝在別台電腦時，把 127.0.0.1 換成那台的位址。模型要先下載：<code>ollama pull {{ form.model || 'qwen3:8b' }}</code>
            </p>
          </div>

          <div v-if="card.key_mode !== 'none'">
            <div class="flex items-center justify-between gap-2">
              <label for="setup-key" class="set-label">
                API 金鑰<span v-if="card.key_mode === 'optional'" class="font-normal text-muted-foreground">（選填）</span>
              </label>
              <a
                v-if="card.key_url"
                :href="card.key_url"
                target="_blank"
                rel="noopener noreferrer"
                class="set-link mb-1.5 inline-flex items-center gap-1 text-sm"
              >
                取得金鑰 <ExternalLink class="size-3.5" aria-hidden="true" />
              </a>
            </div>
            <div v-if="card.oauth === 'openrouter'" class="mb-2.5 space-y-1.5">
              <button type="button" class="set-button" :disabled="oauthStarting || saving" @click="startOpenRouterLogin">
                <Loader2 v-if="oauthStarting" class="animate-spin" aria-hidden="true" />
                <KeyRound v-else aria-hidden="true" />
                用 OpenRouter 一鍵登入取得金鑰
              </button>
              <p class="set-text">前往 OpenRouter 授權後會自動儲存連線並加到分析，不用手動複製貼上。</p>
            </div>
            <input
              id="setup-key"
              v-model="form.apiKey"
              type="password"
              autocomplete="new-password"
              spellcheck="false"
              :placeholder="card.kind === 'gemini' ? '多把金鑰用逗號分隔' : '貼上金鑰'"
              class="set-input w-full"
            >
            <p class="set-text mt-2">金鑰會加密後存在這台伺服器，之後不會再顯示。</p>
          </div>

          <div>
            <label for="setup-model" class="set-label">分析模型</label>
            <input id="setup-model" v-model="form.model" type="text" spellcheck="false" list="setup-models" class="set-input w-full">
            <datalist id="setup-models">
              <option v-for="m in modelChoices" :key="m" :value="m" />
            </datalist>
            <p v-if="result?.models?.length" class="set-text mt-2">服務商列出 {{ result.models.length }} 個模型，點欄位可以挑。</p>
          </div>

          <div class="space-y-3 border-t border-border pt-4">
            <div class="flex flex-wrap items-center gap-3">
              <button type="button" class="set-button" :disabled="!!problem || testing" @click="test">
                <Loader2 v-if="testing" class="animate-spin" aria-hidden="true" />
                <PlugZap v-else aria-hidden="true" />
                測試連線
              </button>
              <span v-if="problem" class="set-text">{{ problem }}</span>
              <span v-else-if="!result" class="set-text">會實際送一筆小的中文請求；測試成功後才能儲存。</span>
            </div>
            <div v-if="result" role="status" class="set-notice" :class="result.ok ? 'set-notice--ok' : 'set-notice--bad'">
              <p class="flex items-start gap-2">
                <CircleCheck v-if="result.ok" class="mt-0.5 size-4 shrink-0" aria-hidden="true" />
                <CircleAlert v-else class="mt-0.5 size-4 shrink-0" aria-hidden="true" />
                <span>{{ result.message }}</span>
              </p>
              <p v-if="!result.ok && result.hint && result.hint !== result.message" class="mt-1">{{ result.hint }}</p>
              <a v-if="result.fix_url" :href="result.fix_url" target="_blank" rel="noopener noreferrer" class="mt-1 inline-flex items-center gap-1 underline">
                前往修復 <ExternalLink class="size-3.5" aria-hidden="true" />
              </a>
              <p v-if="result.detail" class="set-mono mt-1 opacity-80">{{ result.detail }}</p>
            </div>
          </div>
        </template>

        <!-- 3. Telegram: token, then the one-time pairing link -->
        <template v-else-if="step === 'telegram'">
          <p v-if="aiSaved" class="set-notice set-notice--ok">已經接上 {{ card?.label }}，新的收藏會自動經過 AI 分析。</p>
          <p v-else-if="welcomeMode" class="set-notice set-notice--ok">AI 已經自動接好，新的收藏會自動經過 AI 分析。</p>
          <p v-else class="set-notice">還沒有接上 AI：連結照樣能收藏，會標成「尚未分析」，之後接上 AI 就會補分析。</p>
          <p class="set-text">接上 Telegram 之後，在手機或電腦把連結傳給你的機器人，就會收進 OmniKeep。</p>
          <TelegramGuide />

          <div class="space-y-3 border-t border-border pt-4">
            <p v-if="telegramError" class="set-error">無法讀取 Telegram 狀態：{{ telegramError }}</p>
            <p v-else-if="telegramBound" class="set-notice set-notice--ok" role="status">已綁定 Telegram 帳號。現在把任何連結傳給機器人試試看。</p>
            <template v-else>
              <div v-if="telegram && !telegram.configured">
                <label for="setup-telegram-token" class="set-label">機器人權杖</label>
                <div class="flex flex-wrap gap-2">
                  <input
                    id="setup-telegram-token"
                    v-model="token"
                    type="password"
                    autocomplete="new-password"
                    spellcheck="false"
                    class="set-input min-w-0 flex-1"
                    :placeholder="`例如 ${TELEGRAM_TOKEN_EXAMPLE.slice(0, 16)}…`"
                    @keyup.enter="saveToken"
                  >
                  <button type="button" class="set-button" :disabled="!token.trim() || tokenSaving" @click="saveToken">
                    <Loader2 v-if="tokenSaving" class="animate-spin" aria-hidden="true" />
                    儲存權杖
                  </button>
                </div>
                <p v-if="tokenError" class="set-error mt-2" role="alert">{{ tokenError }}</p>
                <p v-else-if="tokenHint" class="set-text mt-2">{{ tokenHint }}</p>
              </div>
              <p v-else-if="telegram" class="set-text">機器人權杖已經儲存。接著產生配對連結，綁定你的 Telegram 帳號。</p>
              <TelegramPairing v-if="telegram?.configured" ref="pairing" @refreshed="onPaired" />
            </template>
          </div>
        </template>

        <!-- 4. Done -->
        <template v-else-if="step === 'done'">
          <ul class="space-y-3">
            <li class="set-notice" :class="aiReady ? 'set-notice--ok' : ''">
              <template v-if="aiSaved">已經接上 {{ card?.label }}。新的收藏會自動經過 AI 分析。</template>
              <template v-else-if="welcomeMode">AI 已經自動接好。新的收藏會自動經過 AI 分析；想要更好，到「設定 › AI」看升級方法。</template>
              <template v-else>還沒有接上 AI。連結照樣能收藏，會標成「尚未分析」；到「設定 › AI」接上之後會補分析。</template>
            </li>
            <li class="set-notice" :class="telegramBound ? 'set-notice--ok' : ''">
              <template v-if="telegramBound">已經接上 Telegram。把連結傳給你的機器人，就會收進來。</template>
              <template v-else>還沒有接上 Telegram。之後到「設定 › 收錄管道」可以再設定。</template>
            </li>
          </ul>
          <p class="set-text">
            接下來丟第一個連結：{{ telegramBound ? '在 Telegram 傳給機器人，或' : '' }}按右上角的「新增」貼上網址。讀完後會出現在收件匣。
          </p>
        </template>
      </div>

      <div class="flex shrink-0 flex-wrap items-center justify-between gap-2 border-t border-border px-5 py-3">
        <button v-if="step !== 'done'" type="button" class="set-button set-button--text -ml-2" @click="later">稍後再說</button>
        <button v-else type="button" class="set-button set-button--text -ml-2" @click="openFullSettings">開啟設定</button>
        <div class="flex flex-wrap gap-2">
          <template v-if="step === 'welcome'">
            <Button variant="ghost" @click="openUpgrades">看升級方法</Button>
            <Button @click="step = 'telegram'">下一步</Button>
          </template>
          <template v-else-if="step === 'choose'">
            <Button variant="ghost" @click="step = 'telegram'">先不接 AI</Button>
            <Button :disabled="!card" @click="step = 'connect'">下一步</Button>
          </template>
          <template v-else-if="step === 'connect'">
            <Button variant="ghost" :disabled="saving" @click="step = 'choose'">上一步</Button>
            <Button :disabled="!canSave" @click="save">
              <Loader2 v-if="saving" class="size-4 animate-spin" aria-hidden="true" />
              儲存並繼續
            </Button>
          </template>
          <template v-else-if="step === 'telegram'">
            <Button v-if="welcomeMode" variant="ghost" @click="step = 'welcome'">上一步</Button>
            <Button v-else-if="!aiSaved" variant="ghost" @click="step = 'choose'">上一步</Button>
            <Button v-if="telegramBound" @click="step = 'done'">下一步</Button>
            <Button v-else variant="ghost" @click="step = 'done'">略過這一步</Button>
          </template>
          <template v-else>
            <Button variant="ghost" @click="addFirstLink">新增第一個連結</Button>
            <Button @click="ui.showSetupWizard = false">開始使用</Button>
          </template>
        </div>
      </div>
    </DialogContent>
  </Dialog>
</template>
