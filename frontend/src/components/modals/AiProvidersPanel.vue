<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { toast } from 'vue-sonner'
import {
  ArrowDown, ArrowUp, CircleAlert, CircleCheck, ExternalLink, Loader2, Pencil, PlugZap, Plus, Trash2, X,
} from 'lucide-vue-next'
import Button from '@/components/ui/button/Button.vue'
import {
  createAiConnection, deleteAiConnection, getAiCatalog, getAiConnections, saveAiSlots, testAiConnection, testAiDraft,
  updateAiConnection,
  type AiCard, type AiConnection, type AiConnectionInput, type AiOverview, type AiSlotEntry, type AiSlotId, type AiTestResult,
} from '@/lib/api'
import { autoExtraBody, extraBodyAfterModelChange, formatExtraBody, parseExtraBody } from '@/lib/extraBody'
import { formatCooldown, hasPlaceholder } from '@/lib/setup'
import { useUiStore } from '@/stores/ui'

/**
 * 設定 › AI 服務商 (docs/ai_provider_options_2026-11.md §5): provider cards,
 * connections with a status light and cooldown, and per-task fallback lists.
 * Keys are write-only: only "configured" and the last four characters come back.
 */
const ui = useUiStore()

const overview = ref<AiOverview | null>(null)
const cards = ref<AiCard[]>([])
const loadError = ref('')
const busy = ref<string>('')
const tests = reactive<Record<string, AiTestResult | 'running'>>({})

interface Editor {
  mode: 'new' | 'edit'
  id?: number
  cardId: string
  label: string
  baseUrl: string
  key: string
  clearKey: boolean
  model: string
  minInterval: string
  maxConcurrency: string
  jsonMode: boolean
  /** caps.extra_body as JSON text; '' sends none */
  extraBody: string
  /** the model extraBody was last filled for (a model with a preset fills it again) */
  extraFor: string
  /** Gemini / Vertex thinking level; '' keeps the model's default */
  thinkingLevel: '' | 'low' | 'medium' | 'high'
  slot: AiSlotId | ''
  errors: Record<string, string>
  models: string[]
}
const editor = ref<Editor | null>(null)
const picking = ref(false)

const slotDraft = reactive<Partial<Record<AiSlotId, AiSlotEntry[]>>>({})
const slotErrors = ref<Record<string, string>>({})
const reindexHint = ref(false)

const cardOf = (id: string) => cards.value.find((c) => c.id === id)
const connections = computed(() => overview.value?.connections ?? [])
const byId = computed(() => new Map(connections.value.map((c) => [c.id, c])))
const editorCard = computed(() => (editor.value ? cardOf(editor.value.cardId) : undefined))

async function refresh() {
  loadError.value = ''
  try {
    const [catalog, current] = await Promise.all([cards.value.length ? null : getAiCatalog(), getAiConnections()])
    if (catalog) cards.value = catalog.cards
    apply(current)
    focusLinkedCard()
  } catch (e) {
    loadError.value = e instanceof Error ? e.message : String(e)
  }
}

/** An agent's settings link names a card: open its saved connection, or a new one to paste the key into. */
function focusLinkedCard() {
  const id = ui.settingsCard
  if (!id) return
  ui.settingsCard = ''
  const saved = connections.value.find((c) => c.card === id)
  if (saved) return startEdit(saved)
  const card = cardOf(id)
  if (card) startNew(card)
}

function apply(next: AiOverview) {
  overview.value = next
  for (const slot of next.slots) slotDraft[slot.id] = slot.entries.map((e) => ({ ...e }))
  slotErrors.value = {}
}

/* ── Status light ─────────────────────────────────────────── */

function light(conn: AiConnection): { tone: 'ok' | 'warn' | 'bad' | 'idle'; text: string } {
  if (!conn.enabled) return { tone: 'idle', text: '已停用' }
  if (conn.key_undecryptable) return { tone: 'bad', text: '金鑰無法解密' }
  const s = conn.status
  if (!s) return { tone: 'idle', text: '尚未使用' }
  if (s.action_required) return { tone: 'bad', text: '要處理' }
  if (s.cooldown_seconds > 0) return { tone: 'warn', text: `冷卻中 ${formatCooldown(s.cooldown_seconds)}` }
  if (!s.ok) return { tone: 'bad', text: '最近失敗' }
  return { tone: 'ok', text: '正常' }
}
const DOT = { ok: 'bg-success', warn: 'bg-warning', bad: 'bg-danger', idle: 'bg-muted-foreground/40' } as const

function keyText(conn: AiConnection) {
  if (conn.key_undecryptable) return '金鑰無法解密，請重新輸入'
  if (cardOf(conn.card)?.key_mode === 'none') return '不用金鑰'
  return conn.key_configured ? `金鑰 ${conn.key_hint || '已設定'}` : '沒有金鑰'
}

// Usage OmniKeep itself sent through a connection, and how much of the free allowance that is.
function compact(n: number) {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(n >= 10_000_000 ? 0 : 1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(n >= 10_000 ? 0 : 1)}K`
  return String(n)
}
const QUOTA_PERIOD = { day: '今天', month: '本月', once: '一次性額度' } as const
function usageText(conn: AiConnection) {
  const u = conn.usage
  if (!u?.total?.requests && !u?.total?.failures) return ''
  const today = u.today ?? { requests: 0, tokens: 0, failures: 0 }
  const month = u.month ?? { tokens: 0 }
  let text = `今天 ${today.requests} 次・${compact(today.tokens)} token；本月 ${compact(month.tokens)} token`
  if (today.failures) text += `；今天失敗 ${today.failures} 次`
  return text
}
function quotaText(conn: AiConnection) {
  const q = conn.usage?.quota
  if (!q) return ''
  const unit = q.unit === 'tokens' ? ' token' : ' 次'
  return `${QUOTA_PERIOD[q.period]}已用 ${compact(q.used)} / ${compact(q.limit)}${unit}（${q.percent}%）`
}

const SLOT_SHORT: Record<AiSlotId, string> = { analysis: '分析', brain: 'Ask Brain', radar: '雷達', embeddings: '向量', video: '影片' }

/* ── Testing ──────────────────────────────────────────────── */

async function runTest(conn: AiConnection, purpose: 'chat' | 'embeddings' = 'chat') {
  const key = `${conn.id}:${purpose}`
  tests[key] = 'running'
  try {
    tests[key] = await testAiConnection(conn.id, { purpose })
  } catch (e) {
    tests[key] = { ok: false, status: null, message: e instanceof Error ? e.message : String(e), detail: '' }
  }
  try {
    apply(await getAiConnections())
  } catch {
    /* keep the list */
  }
  ui.settingsVersion++
}

function testOf(conn: AiConnection, purpose: 'chat' | 'embeddings' = 'chat') {
  const value = tests[`${conn.id}:${purpose}`]
  return value === 'running' ? null : value
}

/* ── Adding and editing ───────────────────────────────────── */

function startNew(card: AiCard) {
  picking.value = false
  const analysisEmpty = !(overview.value?.slots.find((s) => s.id === 'analysis')?.entries.length)
  editor.value = {
    mode: 'new', cardId: card.id, label: card.label, baseUrl: card.base_url, key: '', clearKey: false,
    model: card.model, minInterval: String(card.min_interval ?? ''), maxConcurrency: String(card.max_concurrency ?? ''),
    jsonMode: card.caps.json_mode !== false, extraBody: formatExtraBody(autoExtraBody(card, card.model)), extraFor: card.model,
    thinkingLevel: card.caps.thinking_level ?? '',
    slot: analysisEmpty ? 'analysis' : '', errors: {}, models: [],
  }
  delete tests.editor
}

function startEdit(conn: AiConnection) {
  picking.value = false
  editor.value = {
    mode: 'edit', id: conn.id, cardId: conn.card, label: conn.label, baseUrl: conn.base_url, key: '', clearKey: false,
    model: conn.model, minInterval: conn.min_interval == null ? '' : String(conn.min_interval),
    maxConcurrency: conn.max_concurrency == null ? '' : String(conn.max_concurrency),
    jsonMode: conn.caps.json_mode !== false, extraBody: formatExtraBody(conn.caps.extra_body), extraFor: conn.model,
    thinkingLevel: conn.caps.thinking_level ?? '',
    slot: '', errors: {}, models: [],
  }
  delete tests.editor
}

const editorModels = computed(() => [...new Set([...(editorCard.value?.models ?? []), ...(editor.value?.models ?? [])])])

// A model the card has a preset for (NVIDIA's DeepSeek) fills the extra fields, unless they were typed by hand.
watch(() => editor.value?.model, (next) => {
  const e = editor.value
  if (!e || next === undefined || next === e.extraFor) return
  e.extraBody = extraBodyAfterModelChange(editorCard.value, e.extraFor, next, e.extraBody)
  e.extraFor = next
})
const editorExtra = computed(() => (editor.value ? parseExtraBody(editor.value.extraBody) : null))
const editorPreset = computed(() => {
  const e = editor.value
  return e ? editorCard.value?.model_extra_body?.[e.model.trim()] : undefined
})

function editorInput(): AiConnectionInput {
  const e = editor.value!
  const card = editorCard.value
  const input: AiConnectionInput = {
    card: e.cardId, label: e.label.trim(), model: e.model.trim(),
    min_interval: e.minInterval.trim() === '' ? null : Number(e.minInterval),
    max_concurrency: e.maxConcurrency.trim() === '' ? null : Number(e.maxConcurrency),
    caps: { json_mode: e.jsonMode },
  }
  if (card?.kind === 'gemini') input.caps = { ...input.caps, thinking_level: e.thinkingLevel }
  if (card?.kind !== 'gemini') {
    input.base_url = e.baseUrl.trim().replace(/\/+$/, '')
    const extra = parseExtraBody(e.extraBody)
    if (extra.ok) input.caps = { ...input.caps, extra_body: extra.value }
  }
  if (e.clearKey) input.key = ''
  else if (e.key.trim()) input.key = e.key.trim()
  return input
}

const editorProblem = computed(() => {
  const e = editor.value
  const card = editorCard.value
  if (!e || !card) return '請選一個服務商'
  if (card.kind !== 'gemini' && hasPlaceholder(e.baseUrl)) return '把 API 位址裡角括號的部分（例如 <帳號 ID>）換成你自己的值'
  if (e.mode === 'new' && card.key_mode === 'required' && !e.key.trim()) return '請輸入 API 金鑰'
  if (!e.model.trim()) return '請填模型名稱'
  if (card.kind !== 'gemini' && editorExtra.value && !editorExtra.value.ok) return editorExtra.value.error
  return null
})

async function testEditor() {
  const e = editor.value
  if (!e || editorProblem.value) return
  tests.editor = 'running'
  const input = editorInput()
  const draft = { base_url: input.base_url, model: input.model, key: input.key, extra_body: input.caps?.extra_body }
  try {
    const result = e.mode === 'edit' && e.id
      ? await testAiConnection(e.id, { ...draft, key: e.key.trim() || undefined })
      : await testAiDraft({ card: e.cardId, ...draft })
    tests.editor = result
    if (result.models?.length) e.models = result.models
    if (result.json_mode === false) e.jsonMode = false
  } catch (err) {
    tests.editor = { ok: false, status: null, message: err instanceof Error ? err.message : String(err), detail: '' }
  }
}

async function saveEditor() {
  const e = editor.value
  if (!e || editorProblem.value) return
  busy.value = 'editor'
  e.errors = {}
  try {
    const input = editorInput()
    const result = e.mode === 'edit' && e.id
      ? await updateAiConnection(e.id, input)
      : await createAiConnection({ ...input, slot: e.slot || undefined })
    apply(result)
    editor.value = null
    ui.settingsVersion++
    toast.success(e.mode === 'edit' ? '連線已更新，立即生效' : '已新增連線')
  } catch (err) {
    e.errors = (err as { fieldErrors?: Record<string, string> }).fieldErrors ?? {}
    toast.error('儲存失敗', { description: err instanceof Error ? err.message : String(err) })
  } finally {
    busy.value = ''
  }
}

async function toggleEnabled(conn: AiConnection) {
  busy.value = `toggle-${conn.id}`
  try {
    apply(await updateAiConnection(conn.id, { enabled: !conn.enabled }))
    ui.settingsVersion++
  } catch (e) {
    toast.error('更新失敗', { description: e instanceof Error ? e.message : String(e) })
  } finally {
    busy.value = ''
  }
}

async function remove(conn: AiConnection) {
  const where = conn.used_in.length ? `，它會從「${conn.used_in.map((s) => SLOT_SHORT[s]).join('、')}」的清單移除` : ''
  if (!window.confirm(`確定要刪除「${conn.label}」${where}？金鑰會一起刪除。`)) return
  busy.value = `delete-${conn.id}`
  try {
    apply(await deleteAiConnection(conn.id))
    if (editor.value?.id === conn.id) editor.value = null
    ui.settingsVersion++
  } catch (e) {
    toast.error('刪除失敗', { description: e instanceof Error ? e.message : String(e) })
  } finally {
    busy.value = ''
  }
}

/* ── Slots ────────────────────────────────────────────────── */

function allowed(slot: AiSlotId, conn: AiConnection) {
  if (slot === 'video') return conn.kind === 'gemini' && conn.caps.video !== false
  if (slot === 'embeddings') return conn.kind !== 'gemini'
  return true
}

function candidates(slot: AiSlotId) {
  const used = new Set((slotDraft[slot] ?? []).map((e) => e.connection_id))
  return connections.value.filter((c) => !used.has(c.id) && allowed(slot, c))
}

function move(slot: AiSlotId, index: number, delta: number) {
  const list = [...(slotDraft[slot] ?? [])]
  const target = index + delta
  if (target < 0 || target >= list.length) return
  ;[list[index], list[target]] = [list[target], list[index]]
  slotDraft[slot] = list
}

function dropEntry(slot: AiSlotId, index: number) {
  slotDraft[slot] = (slotDraft[slot] ?? []).filter((_, i) => i !== index)
}

function addEntry(slot: AiSlotId, event: Event) {
  const select = event.target as HTMLSelectElement
  const id = Number(select.value)
  select.value = ''
  if (!id) return
  slotDraft[slot] = [...(slotDraft[slot] ?? []), { connection_id: id, model: '' }]
}

const slotsDirty = computed(() =>
  (overview.value?.slots ?? []).some((s) => JSON.stringify(s.entries) !== JSON.stringify(slotDraft[s.id] ?? [])),
)

async function saveSlots() {
  busy.value = 'slots'
  slotErrors.value = {}
  try {
    const result = await saveAiSlots({ ...slotDraft })
    reindexHint.value = !!result.reindex_hint
    apply(result)
    ui.settingsVersion++
    toast.success('用途設定已儲存，立即生效')
  } catch (e) {
    slotErrors.value = (e as { fieldErrors?: Record<string, string> }).fieldErrors ?? {}
    toast.error('儲存失敗', { description: e instanceof Error ? e.message : String(e) })
  } finally {
    busy.value = ''
  }
}

function placeholderModel(slot: AiSlotId, entry: AiSlotEntry) {
  const conn = byId.value.get(entry.connection_id)
  if (!conn) return ''
  if (slot === 'embeddings') return conn.caps.embedding_model || cardOf(conn.card)?.embedding_model || conn.model
  return conn.model
}

let timer: ReturnType<typeof setInterval> | undefined
onMounted(() => {
  refresh()
  // Cooldowns and status lights change on their own; keep them current while the tab is open.
  timer = setInterval(async () => {
    if (editor.value || slotsDirty.value) return
    try {
      const next = await getAiConnections()
      if (overview.value) overview.value = { ...overview.value, connections: next.connections, needs_setup: next.needs_setup }
    } catch {
      /* offline */
    }
  }, 15_000)
})
onUnmounted(() => clearInterval(timer))

defineExpose({ refresh })

const inputClass =
  'h-9 w-full rounded-lg border border-border bg-input px-3 text-xs text-foreground transition-all placeholder:text-subtle-foreground focus:border-primary focus:ring-2 focus:ring-primary/25 focus:outline-none disabled:opacity-50'
</script>

<template>
  <div class="space-y-5">
    <p v-if="loadError" class="text-xs text-danger">無法讀取 AI 服務設定：{{ loadError }}</p>
    <p v-else-if="!overview" class="text-xs text-muted-foreground">讀取中…</p>

    <template v-else>
      <p v-if="overview.legacy_active" class="rounded-lg border border-border bg-muted/50 p-2.5 text-2xs text-muted-foreground">
        「分析」目前沿用舊的主要服務商設定（.env 或舊版設定）。新增一條連線並加到「分析」後，就改用這裡的設定。
      </p>
      <p v-else-if="overview.needs_setup" class="rounded-lg border border-warning/40 bg-warning/10 p-2.5 text-2xs text-warning">
        還沒有可以做 AI 分析的連線：新增一條並加到「分析」。
      </p>

      <!-- Connections -->
      <section class="space-y-2">
        <div class="flex items-center justify-between gap-2">
          <h3 class="text-xs font-semibold">連線</h3>
          <Button variant="secondary" size="sm" @click="picking = !picking; editor = null">
            <Plus class="size-3" /> 新增連線
          </Button>
        </div>
        <p class="text-2xs text-muted-foreground">
          一條連線是一個服務商帳號（位址、模型、金鑰）。同一家有兩把金鑰時，各建一條，加到同一個用途就會輪流備援。
        </p>

        <!-- Card picker -->
        <div v-if="picking" class="space-y-2 rounded-lg border border-border p-3">
          <div class="flex items-center justify-between">
            <p class="text-xs font-semibold">選服務商（沒有預設答案）</p>
            <button type="button" class="cursor-pointer text-muted-foreground hover:text-foreground" aria-label="關閉" @click="picking = false">
              <X class="size-3.5" />
            </button>
          </div>
          <div class="grid gap-2 sm:grid-cols-2">
            <button
              v-for="c in cards"
              :key="c.id"
              type="button"
              class="cursor-pointer rounded-lg border border-border p-2.5 text-left transition-colors hover:bg-muted"
              @click="startNew(c)"
            >
              <span class="flex items-baseline justify-between gap-2">
                <span class="text-xs font-semibold">{{ c.label }}<span v-if="c.no_signup" class="ml-1.5 rounded bg-success/15 px-1 py-0.5 text-2xs font-normal text-success">不用註冊</span><span v-if="c.ended" class="ml-1.5 rounded bg-warning/15 px-1 py-0.5 text-2xs font-normal text-warning">活動已結束</span></span>
                <span class="shrink-0 text-2xs text-muted-foreground">{{ c.cost }}</span>
              </span>
              <span class="mt-0.5 block text-2xs text-muted-foreground">{{ c.limits }}（{{ c.verified }} 查證）</span>
            </button>
          </div>
          <p v-if="cards.length" class="text-2xs text-subtle-foreground">限額以服務商後台為準。</p>
        </div>

        <!-- Editor (new or edit) -->
        <div v-if="editor && editorCard" class="space-y-3 rounded-lg border border-primary/40 p-3">
          <div class="flex items-start justify-between gap-2">
            <div class="space-y-0.5 text-2xs text-muted-foreground">
              <p class="text-xs font-semibold text-foreground">{{ editor.mode === 'new' ? '新增' : '編輯' }}：{{ editorCard.label }}</p>
              <p>{{ editorCard.limits }}</p>
              <p v-if="editorCard.notes">{{ editorCard.notes }}</p>
              <p v-if="editorCard.training_note" class="text-warning">提醒：{{ editorCard.training_note }}</p>
              <p v-if="editorCard.ended" class="text-warning">限時免費活動已在 {{ editorCard.ends }} 結束，先到官網確認還能不能免費用。</p>
            </div>
            <button type="button" class="cursor-pointer text-muted-foreground hover:text-foreground" aria-label="取消" @click="editor = null">
              <X class="size-3.5" />
            </button>
          </div>

          <div class="grid gap-3 sm:grid-cols-2">
            <div class="space-y-1">
              <label for="ai-label" class="text-2xs font-semibold">名稱</label>
              <input id="ai-label" v-model="editor.label" type="text" :class="inputClass">
              <p v-if="editor.errors.label" class="text-2xs text-danger">{{ editor.errors.label }}</p>
            </div>
            <div class="space-y-1">
              <label for="ai-model" class="text-2xs font-semibold">模型</label>
              <input id="ai-model" v-model="editor.model" type="text" spellcheck="false" list="ai-models" :class="inputClass">
              <datalist id="ai-models">
                <option v-for="m in editorModels" :key="m" :value="m" />
              </datalist>
              <p v-if="editor.errors.model" class="text-2xs text-danger">{{ editor.errors.model }}</p>
            </div>
          </div>

          <div v-if="editorCard.kind !== 'gemini'" class="space-y-1">
            <label for="ai-url" class="text-2xs font-semibold">API 位址</label>
            <input
              id="ai-url"
              v-model="editor.baseUrl"
              type="url"
              spellcheck="false"
              :readonly="!editorCard.editable_url && editor.mode === 'new'"
              :class="[inputClass, !editorCard.editable_url && editor.mode === 'new' && 'text-muted-foreground']"
            >
            <p v-if="editor.errors.base_url" class="text-2xs text-danger">{{ editor.errors.base_url }}</p>
          </div>

          <div v-if="editorCard.key_mode !== 'none'" class="space-y-1">
            <div class="flex items-center justify-between gap-2">
              <label for="ai-key" class="text-2xs font-semibold">
                API 金鑰<span v-if="editorCard.key_mode === 'optional'" class="font-normal text-muted-foreground">（選填）</span>
              </label>
              <a v-if="editorCard.key_url" :href="editorCard.key_url" target="_blank" rel="noopener noreferrer" class="inline-flex items-center gap-1 text-2xs text-primary hover:underline">
                取得金鑰 <ExternalLink class="size-3" />
              </a>
            </div>
            <div class="flex gap-2">
              <input
                id="ai-key"
                v-model="editor.key"
                type="password"
                autocomplete="new-password"
                spellcheck="false"
                :disabled="editor.clearKey"
                :placeholder="editor.mode === 'edit' ? (editor.clearKey ? '儲存後移除金鑰' : '留空表示不變') : (editorCard.kind === 'gemini' ? '多把金鑰用逗號分隔' : '貼上金鑰')"
                :class="inputClass"
              >
              <Button v-if="editor.mode === 'edit' && editorCard.key_mode === 'optional'" variant="ghost" size="sm" class="h-9 shrink-0" @click="editor.clearKey = !editor.clearKey">
                {{ editor.clearKey ? '取消移除' : '移除金鑰' }}
              </Button>
            </div>
            <p v-if="editor.errors.key" class="text-2xs text-danger">{{ editor.errors.key }}</p>
            <p v-else class="text-2xs text-muted-foreground">金鑰加密後存在這台伺服器，之後只顯示末四碼。更換位址時要一併重新輸入。</p>
          </div>

          <div class="grid gap-3 sm:grid-cols-3">
            <div class="space-y-1">
              <label for="ai-interval" class="text-2xs font-semibold">請求最小間隔（秒）</label>
              <input id="ai-interval" v-model="editor.minInterval" type="number" min="0.05" max="120" step="0.5" :placeholder="String(editorCard.min_interval)" :class="inputClass">
              <p v-if="editor.errors.min_interval" class="text-2xs text-danger">{{ editor.errors.min_interval }}</p>
            </div>
            <div class="space-y-1">
              <label for="ai-concurrency" class="text-2xs font-semibold">同時請求數</label>
              <input id="ai-concurrency" v-model="editor.maxConcurrency" type="number" min="1" max="16" step="1" :placeholder="String(editorCard.max_concurrency)" :class="inputClass">
            </div>
            <label class="flex items-end gap-2 pb-2 text-2xs">
              <input v-model="editor.jsonMode" type="checkbox" class="size-4 accent-primary">
              支援 JSON 格式參數
            </label>
          </div>

          <div v-if="editorCard.kind === 'gemini'" class="space-y-1">
            <label for="ai-thinking" class="text-2xs font-semibold">思考等級</label>
            <select id="ai-thinking" v-model="editor.thinkingLevel" :class="inputClass">
              <option value="" class="bg-popover text-foreground">模型預設</option>
              <option value="low" class="bg-popover text-foreground">低（快、省）</option>
              <option value="medium" class="bg-popover text-foreground">中</option>
              <option value="high" class="bg-popover text-foreground">高（慢、用量多、分析較深入）</option>
            </select>
          </div>

          <details v-if="editorCard.kind !== 'gemini'" class="group space-y-1">
            <summary class="flex cursor-pointer items-baseline gap-2 text-2xs font-semibold">
              進階：額外請求參數
              <span v-if="editor.extraBody" class="min-w-0 truncate font-mono font-normal text-muted-foreground group-open:hidden">{{ editor.extraBody }}</span>
            </summary>
            <textarea
              id="ai-extra"
              v-model="editor.extraBody"
              rows="2"
              spellcheck="false"
              aria-label="額外請求參數（JSON）"
              placeholder="{&quot;reasoning&quot;: {&quot;effort&quot;: &quot;low&quot;}}"
              class="w-full resize-y rounded-lg border border-border bg-input p-2.5 font-mono text-xs text-foreground placeholder:text-subtle-foreground focus:border-primary focus:ring-2 focus:ring-primary/25 focus:outline-none"
            />
            <p v-if="editorExtra && !editorExtra.ok" class="text-2xs text-danger">{{ editorExtra.error }}</p>
            <p v-else-if="editor.errors.caps" class="text-2xs text-danger">{{ editor.errors.caps }}</p>
            <p class="text-2xs text-muted-foreground">
              JSON 物件，會併進每一次分析請求和連線測試，常用來關閉推理。留空表示不帶。
              <span v-if="editorPreset">這個模型需要的參數已自動填入。</span>
            </p>
          </details>

          <div v-if="editor.mode === 'new'" class="space-y-1">
            <label for="ai-slot" class="text-2xs font-semibold">儲存後加到</label>
            <select id="ai-slot" v-model="editor.slot" :class="inputClass">
              <option value="" class="bg-popover text-foreground">先不要（之後在下面的「用途」加）</option>
              <option v-for="s in overview.slots.filter((x) => (x.id !== 'video' || editorCard!.kind === 'gemini') && (x.id !== 'embeddings' || editorCard!.kind !== 'gemini'))" :key="s.id" :value="s.id" class="bg-popover text-foreground">
                {{ s.label }}（排在第 {{ s.entries.length + 1 }} 順位）
              </option>
            </select>
          </div>

          <div class="flex flex-wrap items-center gap-2 border-t border-border pt-3">
            <Button variant="outline" size="sm" :disabled="!!editorProblem || tests.editor === 'running'" @click="testEditor">
              <Loader2 v-if="tests.editor === 'running'" class="size-3 animate-spin" />
              <PlugZap v-else class="size-3" />
              測試
            </Button>
            <Button size="sm" :disabled="!!editorProblem || busy === 'editor'" @click="saveEditor">
              <Loader2 v-if="busy === 'editor'" class="size-3 animate-spin" />
              儲存
            </Button>
            <span v-if="editorProblem" class="text-2xs text-muted-foreground">{{ editorProblem }}</span>
            <span v-else class="text-2xs text-muted-foreground">測試會先列出模型，再實際送一筆小的中文 JSON 請求；不會儲存任何東西。</span>
          </div>
          <div
            v-if="tests.editor && tests.editor !== 'running'"
            role="status"
            class="flex gap-2 rounded-lg border p-2.5 text-xs"
            :class="tests.editor.ok ? 'border-success/30 text-success' : 'border-danger/30 text-danger'"
          >
            <CircleCheck v-if="tests.editor.ok" class="mt-0.5 size-3.5 shrink-0" />
            <CircleAlert v-else class="mt-0.5 size-3.5 shrink-0" />
            <div class="min-w-0">
              <p>{{ tests.editor.message }}</p>
              <a v-if="tests.editor.fix_url" :href="tests.editor.fix_url" target="_blank" rel="noopener noreferrer" class="mt-1 inline-flex items-center gap-1 underline">
                前往修復 <ExternalLink class="size-3" />
              </a>
              <p v-if="tests.editor.detail" class="mt-1 break-all font-mono text-2xs opacity-80">{{ tests.editor.detail }}</p>
            </div>
          </div>
        </div>

        <!-- Connection list -->
        <p v-if="!connections.length" class="text-2xs text-muted-foreground">還沒有任何連線。</p>
        <ul class="space-y-2">
          <li v-for="conn in connections" :key="conn.id" class="space-y-2 rounded-lg border border-border p-3" :class="!conn.enabled && 'opacity-60'">
            <div class="flex items-start gap-2.5">
              <span class="mt-1 size-2.5 shrink-0 rounded-full" :class="DOT[light(conn).tone]" :title="light(conn).text" aria-hidden="true" />
              <div class="min-w-0 flex-1 space-y-0.5">
                <p class="flex flex-wrap items-baseline gap-x-2 text-xs">
                  <span class="font-semibold">{{ conn.label }}</span>
                  <span class="text-2xs" :class="light(conn).tone === 'bad' ? 'text-danger' : light(conn).tone === 'warn' ? 'text-warning' : 'text-muted-foreground'">{{ light(conn).text }}</span>
                </p>
                <p class="truncate text-2xs text-muted-foreground" :title="conn.base_url">
                  {{ cardOf(conn.card)?.label ?? conn.card }} · {{ conn.model }} · {{ keyText(conn) }} · 間隔 {{ conn.effective_interval }} 秒
                </p>
                <p v-if="cardOf(conn.card)?.ended" class="text-2xs text-warning">
                  限時免費活動已在 {{ cardOf(conn.card)?.ends }} 結束，先到官網確認還能不能免費用。
                </p>
                <p v-if="usageText(conn) || quotaText(conn)" class="text-2xs text-muted-foreground" title="只算 OmniKeep 自己送出的請求，以服務商後台為準">
                  {{ usageText(conn) }}<span v-if="usageText(conn) && quotaText(conn)"> · </span><span v-if="quotaText(conn)" :class="(conn.usage?.quota?.percent ?? 0) >= 90 ? 'text-warning' : ''">{{ quotaText(conn) }}</span>
                </p>
                <p class="flex flex-wrap gap-1 pt-0.5">
                  <span v-for="s in conn.used_in" :key="s" class="rounded-full border border-primary/30 px-1.5 py-px text-2xs text-primary-soft-foreground">{{ SLOT_SHORT[s] }}</span>
                  <span v-if="!conn.used_in.length" class="text-2xs text-subtle-foreground">沒有用在任何用途</span>
                </p>
              </div>
              <div class="flex shrink-0 items-center gap-1">
                <Button variant="outline" size="sm" :disabled="tests[`${conn.id}:chat`] === 'running'" @click="runTest(conn)">
                  <Loader2 v-if="tests[`${conn.id}:chat`] === 'running'" class="size-3 animate-spin" />
                  <PlugZap v-else class="size-3" />
                  測試
                </Button>
                <Button
                  v-if="conn.kind !== 'gemini' && (conn.caps.embeddings || conn.used_in.includes('embeddings'))"
                  variant="ghost"
                  size="sm"
                  :disabled="tests[`${conn.id}:embeddings`] === 'running'"
                  @click="runTest(conn, 'embeddings')"
                >
                  <Loader2 v-if="tests[`${conn.id}:embeddings`] === 'running'" class="size-3 animate-spin" />
                  測向量
                </Button>
                <button type="button" class="cursor-pointer rounded p-1.5 text-muted-foreground hover:text-foreground" :aria-label="`編輯 ${conn.label}`" @click="startEdit(conn)">
                  <Pencil class="size-3.5" />
                </button>
                <button type="button" class="cursor-pointer rounded p-1.5 text-muted-foreground hover:text-danger" :aria-label="`刪除 ${conn.label}`" :disabled="busy === `delete-${conn.id}`" @click="remove(conn)">
                  <Trash2 class="size-3.5" />
                </button>
              </div>
            </div>

            <div v-if="conn.status && !conn.status.ok && conn.enabled" class="rounded-md bg-danger-soft p-2 text-2xs text-danger">
              <p>{{ conn.status.hint || conn.status.message }}</p>
              <a v-if="conn.status.fix_url" :href="conn.status.fix_url" target="_blank" rel="noopener noreferrer" class="mt-0.5 inline-flex items-center gap-1 underline">
                前往修復 <ExternalLink class="size-3" />
              </a>
              <p v-if="conn.status.action_required" class="mt-0.5">修好後按「測試」，成功就會恢復使用；在那之前會跳過這條，改用下一條。</p>
            </div>

            <template v-for="purpose in (['chat', 'embeddings'] as const)" :key="purpose">
              <div
                v-if="testOf(conn, purpose)"
                class="flex gap-2 rounded-md border p-2 text-2xs"
                :class="testOf(conn, purpose)!.ok ? 'border-success/30 text-success' : 'border-danger/30 text-danger'"
              >
                <CircleCheck v-if="testOf(conn, purpose)!.ok" class="mt-px size-3.5 shrink-0" />
                <CircleAlert v-else class="mt-px size-3.5 shrink-0" />
                <div class="min-w-0">
                  <p>{{ testOf(conn, purpose)!.message }}</p>
                  <p v-if="testOf(conn, purpose)!.detail" class="mt-0.5 break-all font-mono opacity-80">{{ testOf(conn, purpose)!.detail }}</p>
                </div>
              </div>
            </template>

            <label class="flex items-center gap-2 text-2xs text-muted-foreground">
              <input type="checkbox" class="size-3.5 accent-primary" :checked="conn.enabled" :disabled="busy === `toggle-${conn.id}`" @change="toggleEnabled(conn)">
              啟用（停用的連線不會被任何用途使用）
            </label>
          </li>
        </ul>
      </section>

      <!-- Slots -->
      <section class="space-y-2 border-t border-border pt-4">
        <h3 class="text-xs font-semibold">用途與備援順序</h3>
        <p class="text-2xs text-muted-foreground">
          每個用途從第 1 條開始用；遇到 429 或伺服器錯誤會先退避重試，用完才換下一條；金鑰錯誤（401、403、404）立刻換下一條。下一筆工作會再從第 1 條開始。
        </p>
        <div v-for="slot in overview.slots" :key="slot.id" class="space-y-1.5 rounded-lg border border-border p-3">
          <p class="text-xs font-semibold">{{ slot.label }}</p>
          <p class="text-2xs text-muted-foreground">{{ slot.help }}</p>
          <ol class="space-y-1">
            <li v-for="(entry, i) in slotDraft[slot.id] ?? []" :key="`${slot.id}-${entry.connection_id}`" class="flex items-center gap-1.5 text-xs">
              <span class="w-4 shrink-0 text-right text-2xs text-muted-foreground">{{ i + 1 }}.</span>
              <span class="min-w-0 flex-1 truncate">
                <span class="mr-1 inline-block size-2 rounded-full" :class="byId.get(entry.connection_id) ? DOT[light(byId.get(entry.connection_id)!).tone] : 'bg-danger'" aria-hidden="true" />
                {{ byId.get(entry.connection_id)?.label ?? `連線 #${entry.connection_id}（已刪除）` }}
              </span>
              <input
                v-model="entry.model"
                type="text"
                spellcheck="false"
                :placeholder="placeholderModel(slot.id, entry)"
                :aria-label="`${slot.label}第 ${i + 1} 順位的模型`"
                class="h-7 w-40 rounded-md border border-border bg-input px-2 text-2xs placeholder:text-subtle-foreground focus:border-primary focus:outline-none"
              >
              <button type="button" class="cursor-pointer rounded p-1 text-muted-foreground hover:text-foreground disabled:opacity-30" :disabled="i === 0" aria-label="往前" @click="move(slot.id, i, -1)">
                <ArrowUp class="size-3.5" />
              </button>
              <button type="button" class="cursor-pointer rounded p-1 text-muted-foreground hover:text-foreground disabled:opacity-30" :disabled="i === (slotDraft[slot.id]?.length ?? 0) - 1" aria-label="往後" @click="move(slot.id, i, 1)">
                <ArrowDown class="size-3.5" />
              </button>
              <button type="button" class="cursor-pointer rounded p-1 text-muted-foreground hover:text-danger" aria-label="移除" @click="dropEntry(slot.id, i)">
                <X class="size-3.5" />
              </button>
            </li>
          </ol>
          <p v-if="!(slotDraft[slot.id] ?? []).length" class="text-2xs text-subtle-foreground">
            {{ slot.id === 'analysis' ? '空的：沿用舊的主要服務商設定' : slot.id === 'embeddings' ? '空的：沿用舊設定（本機 Ollama，再來是 OpenAI 相容服務）' : slot.id === 'video' ? '空的：用字幕或本機語音轉錄的逐字稿分析' : '空的：跟分析用同一份清單' }}
          </p>
          <select
            v-if="candidates(slot.id).length"
            class="h-7 rounded-md border border-border bg-input px-2 text-2xs"
            :aria-label="`加到${slot.label}`"
            @change="addEntry(slot.id, $event)"
          >
            <option value="" class="bg-popover text-foreground">＋ 加一條連線…</option>
            <option v-for="c in candidates(slot.id)" :key="c.id" :value="c.id" class="bg-popover text-foreground">{{ c.label }}</option>
          </select>
          <p v-if="slotErrors[slot.id]" class="text-2xs text-danger">{{ slotErrors[slot.id] }}</p>
        </div>
        <p v-if="reindexHint" class="rounded-lg border border-warning/40 bg-warning/10 p-2.5 text-2xs text-warning">
          向量模型換了：既有收藏的向量要重建才查得到（伺服器執行 <code>scripts/rebuild_embeddings.py</code>）。向量維度固定 256。
        </p>
        <div class="flex items-center gap-2">
          <Button size="sm" :disabled="!slotsDirty || busy === 'slots'" @click="saveSlots">
            <Loader2 v-if="busy === 'slots'" class="size-3 animate-spin" />
            儲存用途設定
          </Button>
          <Button v-if="slotsDirty" variant="ghost" size="sm" @click="overview && apply(overview)">還原</Button>
          <span v-if="slotsDirty" class="text-2xs text-warning">用途的變更尚未儲存</span>
        </div>
      </section>
    </template>
  </div>
</template>
