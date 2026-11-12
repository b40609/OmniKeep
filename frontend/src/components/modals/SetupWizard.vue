<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { toast } from 'vue-sonner'
import { Sparkles, PlugZap, Loader2, CircleCheck, CircleAlert, ExternalLink, Check } from 'lucide-vue-next'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import Button from '@/components/ui/button/Button.vue'
import TelegramGuide from '@/components/settings/TelegramGuide.vue'
import TelegramPairing from '@/components/settings/TelegramPairing.vue'
import {
  createAiConnection, getAiCatalog, getServiceStatus, getTelegramStatus, saveSettings, testAiDraft,
  type AiCard, type AiTestResult, type TelegramStatus,
} from '@/lib/api'
import { cardById, connectionDraft, formProblem, initialForm, isStarterCard, sameValues, type ConnectionDraft, type SetupForm } from '@/lib/setup'
import { TELEGRAM_TOKEN_EXAMPLE, tokenProblem } from '@/lib/telegramGuide'
import { useUiStore } from '@/stores/ui'

/**
 * First-run guide: connect an AI service, then Telegram, so the first link can be sent
 * from the phone. Both parts can be skipped: a link is kept without an AI (it is analysed
 * once one is connected), and Telegram can be set up later in 設定 › 收錄管道.
 * Nothing is preselected; the cards that need no account or no key are listed first.
 */
const ui = useUiStore()
const LATER_KEY = 'omnikeep-setup-later'

type Step = 'choose' | 'connect' | 'telegram' | 'done'
const step = ref<Step>('choose')
const cards = ref<AiCard[]>([])
const catalogError = ref('')
const cardId = ref('')
const showAll = ref(false)
const form = reactive<SetupForm>({ baseUrl: '', apiKey: '', model: '' })
const testing = ref(false)
const saving = ref(false)
const result = ref<AiTestResult | null>(null)
const testedValues = ref<ConnectionDraft | null>(null)
/** An AI connection was saved in this run of the guide. */
const aiSaved = ref(false)

const card = computed<AiCard | undefined>(() => cardById(cards.value, cardId.value))
// The easiest ones to start with (no account, or no key at all) are what a newcomer sees first.
const starterCards = computed(() => cards.value.filter((c) => isStarterCard(c)))
const shownCards = computed(() => {
  if (showAll.value || !starterCards.value.length) return [...starterCards.value, ...cards.value.filter((c) => !isStarterCard(c))]
  // A card picked from the full list stays in view after the list is folded again.
  const picked = card.value && !isStarterCard(card.value) ? [card.value] : []
  return [...starterCards.value, ...picked]
})
const hiddenCount = computed(() => cards.value.length - shownCards.value.length)
const values = computed(() => (card.value ? connectionDraft(card.value, form) : null))
const problem = computed(() => (card.value ? formProblem(card.value, form) : '請先選一個服務商'))
const canSave = computed(() => !!result.value?.ok && !!values.value && sameValues(testedValues.value, values.value) && !saving.value)
const modelChoices = computed(() => [...new Set([...(card.value?.models ?? []), ...(result.value?.models ?? [])])].slice(0, 200))
const STEPS: { id: Step; label: string }[] = [
  { id: 'choose', label: '選 AI 服務' },
  { id: 'connect', label: '連線與測試' },
  { id: 'telegram', label: '接上 Telegram' },
  { id: 'done', label: '完成' },
]
const stepIndex = computed(() => STEPS.findIndex((s) => s.id === step.value))
/** An earlier step shows a tick only when it was really done, not when it was skipped. */
function stepDone(index: number): boolean {
  if (index >= stepIndex.value) return false
  return STEPS[index].id === 'telegram' ? telegramBound.value : aiSaved.value
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
    cards.value = (await getAiCatalog()).cards
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
  ui.openSettings(aiSaved.value ? 'channels' : 'ai')
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
    if (!open) return
    step.value = 'choose'
    aiSaved.value = false
    loadCatalog()
    if (cardId.value) choose(cardId.value)
  },
)

onMounted(async () => {
  try {
    if (sessionStorage.getItem(LATER_KEY)) return
  } catch {
    /* private mode: ask anyway */
  }
  try {
    const status = await getServiceStatus()
    // A key that cannot be decrypted is a different problem; the banner explains that one.
    if (status.needs_setup && !status.undecryptable.length && !ui.showSettingsModal) ui.showSetupWizard = true
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
          <DialogTitle>開始使用 OmniKeep</DialogTitle>
          <DialogDescription class="text-sm">
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
        <!-- 1. Choose a provider card -->
        <template v-if="step === 'choose'">
          <p v-if="catalogError" class="set-error">無法讀取服務商清單：{{ catalogError }}</p>
          <p v-else-if="!cards.length" class="set-text">讀取中…</p>
          <p v-else class="set-text">
            AI 用來幫收藏寫摘要和分類。下面幾個不用註冊或不用金鑰就能開始；之後隨時可以在「設定 › AI」換別家或加備援。
          </p>
          <div class="grid gap-2 sm:grid-cols-2" role="radiogroup" aria-label="AI 服務商">
            <button
              v-for="c in shownCards"
              :key="c.id"
              type="button"
              role="radio"
              :aria-checked="cardId === c.id"
              class="flex min-w-0 cursor-pointer flex-col rounded-lg border p-3 text-left transition-colors"
              :class="cardId === c.id ? 'border-primary bg-primary/10' : 'border-border hover:bg-muted'"
              @click="choose(c.id)"
            >
              <!-- Name, then cost on a line of its own: a long cost used to squeeze the name into four lines -->
              <span class="block text-base font-semibold [overflow-wrap:anywhere]">{{ c.label }}</span>
              <span class="mt-1 flex flex-wrap gap-x-2 text-sm text-muted-foreground [overflow-wrap:anywhere]">
                <span v-if="c.no_signup" class="text-success">不用註冊</span>
                <span v-else-if="c.key_mode === 'none'" class="text-success">不用金鑰</span>
                <span v-if="c.ended" class="text-warning">活動已結束</span>
                <span>{{ c.cost }}</span>
              </span>
              <span class="mt-1 block text-sm text-muted-foreground [overflow-wrap:anywhere]">{{ c.limits }}（{{ c.verified }} 查證）</span>
            </button>
          </div>
          <div v-if="cards.length" class="flex flex-wrap items-center gap-x-3 gap-y-2">
            <button v-if="hiddenCount > 0" type="button" class="set-button" @click="showAll = true">顯示全部 {{ cards.length }} 個服務商</button>
            <button v-else-if="showAll && starterCards.length" type="button" class="set-button" @click="showAll = false">只顯示最容易開始的</button>
            <span class="set-text">限額以服務商後台為準。不確定選哪個，可以請你的 Claude、Codex 或 Antigravity 依你的狀況說明。</span>
          </div>
        </template>

        <!-- 2. Address, key, model, then test -->
        <template v-else-if="step === 'connect' && card">
          <div class="space-y-1 text-sm text-muted-foreground">
            <p><span class="font-semibold text-foreground">{{ card.label }}</span>：{{ card.limits }}</p>
            <p v-if="card.notes">{{ card.notes }}</p>
            <p v-if="card.training_note" class="text-warning">提醒：{{ card.training_note }}</p>
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
            <li class="set-notice" :class="aiSaved ? 'set-notice--ok' : ''">
              <template v-if="aiSaved">已經接上 {{ card?.label }}。新的收藏會自動經過 AI 分析。</template>
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
          <template v-if="step === 'choose'">
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
            <Button v-if="!aiSaved" variant="ghost" @click="step = 'choose'">上一步</Button>
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
