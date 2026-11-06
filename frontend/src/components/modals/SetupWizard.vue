<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { toast } from 'vue-sonner'
import { Sparkles, PlugZap, Loader2, CircleCheck, CircleAlert, ExternalLink, Check } from 'lucide-vue-next'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import Button from '@/components/ui/button/Button.vue'
import { createAiConnection, getAiCatalog, getServiceStatus, testAiDraft, type AiCard, type AiTestResult } from '@/lib/api'
import { cardById, connectionDraft, formProblem, initialForm, sameValues, type ConnectionDraft, type SetupForm } from '@/lib/setup'
import { useUiStore } from '@/stores/ui'

/**
 * First-run guide (after AnythingLLM's onboarding): while no AI provider is
 * usable, the owner picks a card from the catalog (nothing is preselected),
 * fills address, key and model, tests, then saves it as the analysis connection.
 */
const ui = useUiStore()
const LATER_KEY = 'omnikeep-setup-later'

const step = ref<'choose' | 'connect' | 'done'>('choose')
const cards = ref<AiCard[]>([])
const catalogError = ref('')
const cardId = ref('')
const form = reactive<SetupForm>({ baseUrl: '', apiKey: '', model: '' })
const testing = ref(false)
const saving = ref(false)
const result = ref<AiTestResult | null>(null)
const testedValues = ref<ConnectionDraft | null>(null)

const card = computed<AiCard | undefined>(() => cardById(cards.value, cardId.value))
// Services usable with no account come first, so a newcomer without keys can start right away.
const orderedCards = computed(() => [...cards.value.filter((c) => c.no_signup), ...cards.value.filter((c) => !c.no_signup)])
const values = computed(() => (card.value ? connectionDraft(card.value, form) : null))
const problem = computed(() => (card.value ? formProblem(card.value, form) : '請先選一個服務商'))
const canSave = computed(() => !!result.value?.ok && !!values.value && sameValues(testedValues.value, values.value) && !saving.value)
const modelChoices = computed(() => [...new Set([...(card.value?.models ?? []), ...(result.value?.models ?? [])])].slice(0, 200))
const STEPS = [
  { id: 'choose', label: '選服務商' },
  { id: 'connect', label: '連線與測試' },
  { id: 'done', label: '完成' },
] as const
const stepIndex = computed(() => STEPS.findIndex((s) => s.id === step.value))

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
    step.value = 'done'
  } catch (e) {
    toast.error('儲存失敗', { description: e instanceof Error ? e.message : String(e) })
  } finally {
    saving.value = false
  }
}

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
  ui.openSettings('ai')
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

const inputClass =
  'h-9 w-full rounded-lg border border-border bg-input px-3 text-xs text-foreground transition-all placeholder:text-subtle-foreground focus:border-primary focus:ring-2 focus:ring-primary/25 focus:outline-none disabled:opacity-50'
</script>

<template>
  <Dialog :open="ui.showSetupWizard" @update:open="onOpenChange">
    <DialogContent class="flex max-h-[90vh] max-w-2xl flex-col gap-0 overflow-hidden p-0">
      <div class="flex shrink-0 items-center gap-2.5 border-b border-border p-5 pb-4">
        <div class="flex size-9 items-center justify-center rounded-lg bg-primary text-primary-foreground shadow-sm">
          <Sparkles class="size-4.5" />
        </div>
        <DialogHeader>
          <DialogTitle>開始使用 OmniKeep</DialogTitle>
          <DialogDescription class="text-xs">
            OmniKeep 用 AI 幫收藏寫摘要、分類並建立語意搜尋。先接上一個 AI 服務，之後可以在「設定 › AI 服務商」加備援、依用途分開。
          </DialogDescription>
        </DialogHeader>
      </div>

      <ol class="flex shrink-0 items-center gap-2 border-b border-border px-5 py-2.5 text-2xs" aria-label="設定步驟">
        <li
          v-for="(s, i) in STEPS"
          :key="s.id"
          class="flex items-center gap-1.5"
          :class="i === stepIndex ? 'font-semibold text-foreground' : 'text-muted-foreground'"
          :aria-current="i === stepIndex ? 'step' : undefined"
        >
          <span
            class="flex size-5 items-center justify-center rounded-full border text-2xs"
            :class="i < stepIndex ? 'border-primary bg-primary text-primary-foreground' : i === stepIndex ? 'border-primary text-primary-soft-foreground' : 'border-border'"
          >
            <Check v-if="i < stepIndex" class="size-3" />
            <template v-else>{{ i + 1 }}</template>
          </span>
          {{ s.label }}
          <span v-if="i < STEPS.length - 1" class="mx-1 h-px w-6 bg-border" aria-hidden="true" />
        </li>
      </ol>

      <div class="min-h-0 flex-1 space-y-4 overflow-y-auto p-5 text-sm">
        <!-- 1. Choose a provider card -->
        <template v-if="step === 'choose'">
          <p v-if="catalogError" class="text-xs text-danger">無法讀取服務商清單：{{ catalogError }}</p>
          <p v-else-if="!cards.length" class="text-xs text-muted-foreground">讀取中…</p>
          <p v-else class="text-2xs text-muted-foreground">
            每個選項的費用與限制不同，沒有預設答案。也可以請你的 Claude、Codex 或 Antigravity 依你的狀況說明怎麼選。
          </p>
          <div class="grid gap-2 sm:grid-cols-2" role="radiogroup" aria-label="AI 服務商">
            <button
              v-for="c in orderedCards"
              :key="c.id"
              type="button"
              role="radio"
              :aria-checked="cardId === c.id"
              class="cursor-pointer rounded-lg border p-3 text-left transition-colors"
              :class="cardId === c.id ? 'border-primary bg-primary/10' : 'border-border hover:bg-muted'"
              @click="choose(c.id)"
            >
              <span class="flex items-baseline justify-between gap-2">
                <span class="text-xs font-semibold">{{ c.label }}<span v-if="c.no_signup" class="ml-1.5 rounded bg-success/15 px-1 py-0.5 text-2xs font-normal text-success">不用註冊</span><span v-if="c.ended" class="ml-1.5 rounded bg-warning/15 px-1 py-0.5 text-2xs font-normal text-warning">活動已結束</span></span>
                <span class="shrink-0 text-2xs text-muted-foreground">{{ c.cost }}</span>
              </span>
              <span class="mt-1 block text-2xs text-muted-foreground">{{ c.limits }}（{{ c.verified }} 查證）</span>
            </button>
          </div>
          <p v-if="cards.length" class="text-2xs text-subtle-foreground">還沒有任何金鑰也沒關係：標了「不用註冊」的可以先試，之後再加其他家。限額以服務商後台為準。</p>
        </template>

        <!-- 2. Address, key, model, then test -->
        <template v-else-if="step === 'connect' && card">
          <div class="space-y-1 text-xs text-muted-foreground">
            <p><span class="font-semibold text-foreground">{{ card.label }}</span>：{{ card.limits }}</p>
            <p v-if="card.notes">{{ card.notes }}</p>
            <p v-if="card.training_note" class="text-warning">提醒：{{ card.training_note }}</p>
          </div>

          <div v-if="card.kind !== 'gemini'" class="space-y-1.5">
            <label for="setup-url" class="text-xs font-semibold">API 位址</label>
            <input
              id="setup-url"
              v-model="form.baseUrl"
              type="url"
              spellcheck="false"
              placeholder="https://…/v1"
              :readonly="!card.editable_url"
              :class="[inputClass, !card.editable_url && 'text-muted-foreground']"
            >
            <p v-if="card.kind === 'ollama'" class="text-2xs text-muted-foreground">
              Ollama 裝在別台電腦時，把 127.0.0.1 換成那台的位址。模型要先下載：<code>ollama pull {{ form.model || 'qwen3:8b' }}</code>
            </p>
          </div>

          <div v-if="card.key_mode !== 'none'" class="space-y-1.5">
            <div class="flex items-center justify-between gap-2">
              <label for="setup-key" class="text-xs font-semibold">
                API 金鑰<span v-if="card.key_mode === 'optional'" class="font-normal text-muted-foreground">（選填）</span>
              </label>
              <a
                v-if="card.key_url"
                :href="card.key_url"
                target="_blank"
                rel="noopener noreferrer"
                class="inline-flex items-center gap-1 text-2xs text-primary hover:underline"
              >
                取得金鑰 <ExternalLink class="size-3" />
              </a>
            </div>
            <input
              id="setup-key"
              v-model="form.apiKey"
              type="password"
              autocomplete="new-password"
              spellcheck="false"
              :placeholder="card.kind === 'gemini' ? '多把金鑰用逗號分隔' : '貼上金鑰'"
              :class="inputClass"
            >
            <p class="text-2xs text-muted-foreground">金鑰會加密後存在這台伺服器，之後不會再顯示。</p>
          </div>

          <div class="space-y-1.5">
            <label for="setup-model" class="text-xs font-semibold">分析模型</label>
            <input id="setup-model" v-model="form.model" type="text" spellcheck="false" list="setup-models" :class="inputClass">
            <datalist id="setup-models">
              <option v-for="m in modelChoices" :key="m" :value="m" />
            </datalist>
            <p v-if="result?.models?.length" class="text-2xs text-muted-foreground">服務商列出 {{ result.models.length }} 個模型，點欄位可以挑。</p>
          </div>

          <div class="space-y-2 border-t border-border pt-3">
            <div class="flex flex-wrap items-center gap-2">
              <Button variant="outline" size="sm" :disabled="!!problem || testing" @click="test">
                <Loader2 v-if="testing" class="size-3 animate-spin" />
                <PlugZap v-else class="size-3" />
                測試連線
              </Button>
              <span v-if="problem" class="text-2xs text-muted-foreground">{{ problem }}</span>
              <span v-else-if="!result" class="text-2xs text-muted-foreground">會實際送一筆小的中文請求；測試成功後才能儲存。</span>
            </div>
            <div
              v-if="result"
              role="status"
              class="flex gap-2 rounded-lg border p-2.5 text-xs"
              :class="result.ok ? 'border-success/30 text-success' : 'border-danger/30 text-danger'"
            >
              <CircleCheck v-if="result.ok" class="mt-0.5 size-3.5 shrink-0" />
              <CircleAlert v-else class="mt-0.5 size-3.5 shrink-0" />
              <div class="min-w-0">
                <p>{{ result.message }}</p>
                <p v-if="!result.ok && result.hint && result.hint !== result.message" class="mt-1">{{ result.hint }}</p>
                <a v-if="result.fix_url" :href="result.fix_url" target="_blank" rel="noopener noreferrer" class="mt-1 inline-flex items-center gap-1 underline">
                  前往修復 <ExternalLink class="size-3" />
                </a>
                <p v-if="result.detail" class="mt-1 break-all font-mono text-2xs opacity-80">{{ result.detail }}</p>
              </div>
            </div>
          </div>
        </template>

        <!-- 3. Done -->
        <template v-else-if="step === 'done'">
          <div class="flex gap-2 rounded-lg border border-success/30 p-3 text-xs text-success">
            <CircleCheck class="mt-0.5 size-4 shrink-0" />
            <p>已經接上 {{ card?.label }}，立即生效。新的收藏會自動經過 AI 分析。</p>
          </div>
          <ul class="list-disc space-y-1 pl-5 text-2xs text-muted-foreground">
            <li>到「設定 › AI 服務商」可以再加一條備援連線（例如第二把金鑰），這條失敗時會自動換過去。</li>
            <li>Ask Brain、雷達評分、向量、影片解析也可以各自選服務商；沒選的就跟分析用同一條。</li>
            <li>Telegram、LINE Bot、GitHub Token 與備份也都在「設定」裡填，不需要修改 .env。</li>
          </ul>
        </template>
      </div>

      <div class="flex shrink-0 items-center justify-between gap-2 border-t border-border px-5 py-3">
        <button
          v-if="step !== 'done'"
          type="button"
          class="cursor-pointer text-2xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
          @click="later"
        >
          稍後再說
        </button>
        <button
          v-else
          type="button"
          class="cursor-pointer text-2xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
          @click="openFullSettings"
        >
          開啟完整設定
        </button>
        <div class="flex gap-2">
          <template v-if="step === 'choose'">
            <Button size="sm" :disabled="!card" @click="step = 'connect'">下一步</Button>
          </template>
          <template v-else-if="step === 'connect'">
            <Button variant="ghost" size="sm" :disabled="saving" @click="step = 'choose'">上一步</Button>
            <Button size="sm" :disabled="!canSave" @click="save">
              <Loader2 v-if="saving" class="size-3 animate-spin" />
              儲存並完成
            </Button>
          </template>
          <Button v-else size="sm" @click="ui.showSetupWizard = false">開始使用</Button>
        </div>
      </div>
    </DialogContent>
  </Dialog>
</template>
