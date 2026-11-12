<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { toast } from 'vue-sonner'
import { ArrowDown, ArrowUp, ChevronDown, ExternalLink, Loader2, Pencil, PlugZap, Plus, Trash2, X } from 'lucide-vue-next'
import Switch from '@/components/ui/switch/Switch.vue'
import Select from '@/components/ui/select/Select.vue'
import ConfirmDialog from '@/components/ui/confirm/ConfirmDialog.vue'
import SettingBlock from './SettingBlock.vue'
import AiConnectionEditor from './AiConnectionEditor.vue'
import type { AiEditor } from './aiEditor'
import { useSettingsForm } from '@/composables/useSettingsForm'
import { SLOT_TEXT } from '@/lib/settingsText'
import {
  createAiConnection, deleteAiConnection, getAiCatalog, getAiConnections, saveAiSlots, testAiConnection, testAiDraft,
  updateAiConnection,
  type AiCard, type AiConnection, type AiConnectionInput, type AiOverview, type AiSlotEntry, type AiSlotId, type AiTestResult,
} from '@/lib/api'
import { autoExtraBody, extraBodyAfterModelChange, formatExtraBody, parseExtraBody } from '@/lib/extraBody'
import { formatCooldown, hasPlaceholder } from '@/lib/setup'
import { useUiStore } from '@/stores/ui'

/**
 * 設定 › AI (docs/ai_provider_options_2026-11.md §5): connections, one folded row
 * each with a status light and cooldown, and the per-task fallback lists.
 * Keys are write-only: only "configured" and the last four characters come back.
 */
const ui = useUiStore()

const overview = ref<AiOverview | null>(null)
const cards = ref<AiCard[]>([])
const loadError = ref('')
const busy = ref<string>('')
const tests = reactive<Record<string, AiTestResult | 'running'>>({})

const editor = ref<AiEditor | null>(null)
const picking = ref(false)
/** Connections whose row is open. */
const expanded = ref(new Set<number>())
/** The connection 刪除 was pressed on, until the owner confirms. */
const removing = ref<AiConnection | null>(null)

function toggleRow(id: number) {
  const next = new Set(expanded.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  expanded.value = next
  if (editor.value?.id === id && !next.has(id)) editor.value = null
}

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

const slotName = (id: AiSlotId) => SLOT_TEXT[id]?.label ?? id
function todayText(conn: AiConnection) {
  const today = conn.usage?.today
  return today?.requests ? `今天 ${today.requests} 次` : ''
}

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
  expanded.value = new Set([...expanded.value, conn.id])
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
  if (!e || !card) return '請選一個 AI 服務'
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
    toast.success(e.mode === 'edit' ? '連線已更新' : '已新增連線')
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

const removeText = computed(() => {
  const conn = removing.value
  if (!conn) return ''
  const where = conn.used_in.length ? `它會從「${conn.used_in.map(slotName).join('、')}」的清單移除。` : ''
  return `${where}金鑰會一起刪除，無法復原。`
})

async function remove() {
  const conn = removing.value
  if (!conn) return
  busy.value = `delete-${conn.id}`
  try {
    apply(await deleteAiConnection(conn.id))
    if (editor.value?.id === conn.id) editor.value = null
    removing.value = null
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

function addEntry(slot: AiSlotId, value: string) {
  const id = Number(value)
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
    toast.success('已儲存')
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

// The settings page asks before leaving while a connection is half typed or the task lists are unsaved.
const form = useSettingsForm()
watch(() => !!editor.value || slotsDirty.value, (dirty) => (form.extraDirty.value = dirty), { immediate: true })
onUnmounted(() => (form.extraDirty.value = false))

function emptySlotText(slot: AiSlotId) {
  if (slot === 'analysis') return '空的：沿用舊版的主要 AI 設定。'
  if (slot === 'embeddings') return '空的：沿用舊設定（本機 Ollama，再來是 OpenAI 相容服務）。'
  if (slot === 'video') return '空的：用字幕或本機語音轉錄的文字來分析。'
  return '空的：和「分析」用同一份清單。'
}

defineExpose({ refresh })
</script>

<template>
  <div>
    <p v-if="loadError" class="set-notice set-notice--bad mt-6">無法讀取 AI 連線：{{ loadError }}</p>
    <p v-else-if="!overview" class="set-text mt-6">讀取中…</p>

    <template v-else>
      <p v-if="overview.legacy_active" class="set-notice mt-6">
        「分析」目前沿用舊版的主要 AI 設定。新增一條連線並加到「分析」後，就改用這裡的設定。
      </p>
      <p v-else-if="overview.needs_setup" class="set-notice set-notice--warn mt-6">
        還沒有可以做分析的連線。新增一條，並加到「分析」。
      </p>

      <!-- Connections -->
      <SettingBlock id="connections" title="AI 連線" description="一條連線是一組位址、模型和金鑰。同一個服務有兩把金鑰時各建一條，加到同一個用途就會輪流備援。">
        <template #above>
          <div class="mt-4 flex items-center gap-3">
            <button type="button" class="set-button" :aria-expanded="picking" @click="picking = !picking; editor = null">
              <Plus aria-hidden="true" />新增連線
            </button>
          </div>

          <!-- Service picker -->
          <div v-if="picking" class="set-panel mt-4">
            <div class="flex items-center justify-between gap-3">
              <p class="text-base font-semibold">選一個 AI 服務</p>
              <button type="button" class="set-icon" aria-label="關閉" title="關閉" @click="picking = false"><X aria-hidden="true" /></button>
            </div>
            <ul class="mt-2 grid gap-x-6 sm:grid-cols-2">
              <li v-for="c in cards" :key="c.id" class="border-t border-hairline">
                <button type="button" class="w-full cursor-pointer rounded-lg px-2 py-3 text-left transition-colors hover:bg-surface-2" @click="startNew(c)">
                  <span class="flex items-baseline justify-between gap-3">
                    <span class="text-sm font-semibold">{{ c.label }}</span>
                    <span class="shrink-0 text-xs text-muted-foreground">{{ c.cost }}</span>
                  </span>
                  <span class="mt-0.5 block text-sm text-muted-foreground">{{ c.limits }}</span>
                  <span class="mt-1 flex flex-wrap gap-2 text-xs text-muted-foreground">
                    <span v-if="c.no_signup" class="set-tag">不用註冊</span>
                    <span v-if="c.ended" class="set-tag">活動已結束</span>
                    <span>{{ c.verified }} 查證</span>
                  </span>
                </button>
              </li>
            </ul>
            <p v-if="cards.length" class="set-text mt-3">限額以各服務的後台為準。</p>
          </div>

          <AiConnectionEditor
            v-if="editor && editor.mode === 'new' && editorCard"
            class="mt-4"
            :editor="editor"
            :card="editorCard"
            :models="editorModels"
            :slots="overview.slots"
            :problem="editorProblem"
            :extra-error="editorExtra && !editorExtra.ok ? editorExtra.error : ''"
            :has-preset="!!editorPreset"
            :test="tests.editor"
            :saving="busy === 'editor'"
            @test="testEditor"
            @save="saveEditor"
            @cancel="editor = null"
          />
        </template>

        <p v-if="!connections.length" class="set-text py-4">還沒有任何連線。</p>
        <div v-for="conn in connections" :key="conn.id" class="set-fold">
          <button
            type="button"
            class="set-fold__head"
            :aria-expanded="expanded.has(conn.id)"
            :aria-controls="`ai-conn-${conn.id}`"
            @click="toggleRow(conn.id)"
          >
            <span class="min-w-0 flex-1" :class="!conn.enabled && 'opacity-60'">
              <span class="block truncate text-base font-semibold">{{ conn.label }}</span>
              <span class="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-muted-foreground">
                <span class="truncate">{{ conn.model }}</span>
                <span v-for="s in conn.used_in" :key="s" class="set-tag">{{ slotName(s) }}</span>
                <span v-if="!conn.used_in.length" class="text-xs">沒有用在任何用途</span>
              </span>
            </span>
            <span v-if="todayText(conn)" class="shrink-0 text-xs tabular-nums text-muted-foreground max-sm:hidden" title="只算 OmniKeep 自己送出的請求">{{ todayText(conn) }}</span>
            <span class="set-status" :class="{ 'set-status--ok': light(conn).tone === 'ok', 'set-status--warn': light(conn).tone === 'warn', 'set-status--bad': light(conn).tone === 'bad' }">{{ light(conn).text }}</span>
            <ChevronDown aria-hidden="true" />
          </button>

          <div v-if="expanded.has(conn.id)" :id="`ai-conn-${conn.id}`" class="set-fold__body space-y-3">
            <AiConnectionEditor
              v-if="editor && editor.mode === 'edit' && editor.id === conn.id && editorCard"
              :editor="editor"
              :card="editorCard"
              :models="editorModels"
              :slots="overview.slots"
              :problem="editorProblem"
              :extra-error="editorExtra && !editorExtra.ok ? editorExtra.error : ''"
              :has-preset="!!editorPreset"
              :test="tests.editor"
              :saving="busy === 'editor'"
              @test="testEditor"
              @save="saveEditor"
              @cancel="editor = null"
            />
            <template v-else>
              <p class="set-text" :title="conn.base_url">
                {{ cardOf(conn.card)?.label ?? conn.card }}・{{ keyText(conn) }}・每次請求間隔 {{ conn.effective_interval }} 秒
              </p>
              <p v-if="usageText(conn) || quotaText(conn)" class="set-text" title="只算 OmniKeep 自己送出的請求，以服務的後台為準">
                {{ usageText(conn) }}<template v-if="usageText(conn) && quotaText(conn)">；</template><span v-if="quotaText(conn)" :class="(conn.usage?.quota?.percent ?? 0) >= 90 ? 'text-warning' : ''">{{ quotaText(conn) }}</span>
              </p>
              <p v-if="cardOf(conn.card)?.ended" class="set-notice set-notice--warn">
                限時免費活動已在 {{ cardOf(conn.card)?.ends }} 結束，先到官網確認還能不能免費用。
              </p>
              <div v-if="conn.status && !conn.status.ok && conn.enabled" class="set-notice set-notice--bad">
                <p>{{ conn.status.hint || conn.status.message }}</p>
                <a v-if="conn.status.fix_url" :href="conn.status.fix_url" target="_blank" rel="noopener noreferrer" class="inline-flex items-center gap-1 underline">
                  前往處理 <ExternalLink class="size-4" aria-hidden="true" />
                </a>
                <p v-if="conn.status.action_required">處理好後按「測試」，成功就會恢復使用；在那之前會跳過這條，改用下一條。</p>
              </div>
              <template v-for="purpose in (['chat', 'embeddings'] as const)" :key="purpose">
                <div v-if="testOf(conn, purpose)" role="status" class="set-notice" :class="testOf(conn, purpose)!.ok ? 'set-notice--ok' : 'set-notice--bad'">
                  <p>{{ testOf(conn, purpose)!.message }}</p>
                  <p v-if="testOf(conn, purpose)!.detail" class="set-mono mt-1 opacity-80">{{ testOf(conn, purpose)!.detail }}</p>
                </div>
              </template>

              <div class="flex flex-wrap items-center gap-2">
                <button type="button" class="set-button" :disabled="tests[`${conn.id}:chat`] === 'running'" @click="runTest(conn)">
                  <Loader2 v-if="tests[`${conn.id}:chat`] === 'running'" class="animate-spin" aria-hidden="true" />
                  <PlugZap v-else aria-hidden="true" />
                  測試
                </button>
                <button
                  v-if="conn.kind !== 'gemini' && (conn.caps.embeddings || conn.used_in.includes('embeddings'))"
                  type="button"
                  class="set-button"
                  :disabled="tests[`${conn.id}:embeddings`] === 'running'"
                  @click="runTest(conn, 'embeddings')"
                >
                  <Loader2 v-if="tests[`${conn.id}:embeddings`] === 'running'" class="animate-spin" aria-hidden="true" />
                  測試語意搜尋
                </button>
                <button type="button" class="set-button" @click="startEdit(conn)"><Pencil aria-hidden="true" />編輯</button>
                <button type="button" class="set-button set-button--danger" :disabled="busy === `delete-${conn.id}`" @click="removing = conn"><Trash2 aria-hidden="true" />刪除</button>
                <label class="ml-auto flex items-center gap-3 text-sm" :title="conn.enabled ? '停用後不會被任何用途使用' : undefined">
                  啟用
                  <Switch :model-value="conn.enabled" :disabled="busy === `toggle-${conn.id}`" :aria-label="`啟用 ${conn.label}`" @update:model-value="toggleEnabled(conn)" />
                </label>
              </div>
            </template>
          </div>
        </div>
      </SettingBlock>

      <!-- Slots -->
      <SettingBlock id="slots" title="用途與備援順序" description="每個用途從第 1 條開始用。遇到限流或伺服器錯誤會先等一下再試，試完才換下一條；金鑰錯誤則立刻換下一條。">
        <div v-for="slot in overview.slots" :key="slot.id" class="set-row set-row--stacked">
          <div class="set-row__text">
            <p class="set-row__name">{{ slotName(slot.id) }}</p>
            <p class="set-row__help">{{ SLOT_TEXT[slot.id]?.help ?? slot.help }}</p>
          </div>
          <ol v-if="(slotDraft[slot.id] ?? []).length" class="space-y-2">
            <li v-for="(entry, i) in slotDraft[slot.id] ?? []" :key="`${slot.id}-${entry.connection_id}`" class="flex items-center gap-2 text-sm">
              <span class="w-5 shrink-0 text-right text-xs tabular-nums text-muted-foreground">{{ i + 1 }}</span>
              <span class="min-w-0 flex-1 truncate">{{ byId.get(entry.connection_id)?.label ?? `連線 #${entry.connection_id}（已刪除）` }}</span>
              <input
                v-model="entry.model"
                type="text"
                spellcheck="false"
                class="set-input w-60 max-sm:w-28"
                :placeholder="placeholderModel(slot.id, entry)"
                :aria-label="`${slotName(slot.id)}第 ${i + 1} 順位的模型`"
              >
              <button type="button" class="set-icon" :disabled="i === 0" aria-label="往前" title="往前" @click="move(slot.id, i, -1)"><ArrowUp aria-hidden="true" /></button>
              <button type="button" class="set-icon" :disabled="i === (slotDraft[slot.id]?.length ?? 0) - 1" aria-label="往後" title="往後" @click="move(slot.id, i, 1)"><ArrowDown aria-hidden="true" /></button>
              <button type="button" class="set-icon" aria-label="移除" title="移除" @click="dropEntry(slot.id, i)"><X aria-hidden="true" /></button>
            </li>
          </ol>
          <p v-else class="set-text">{{ emptySlotText(slot.id) }}</p>
          <div v-if="candidates(slot.id).length">
            <Select
              model-value=""
              placeholder="加一條連線"
              :options="candidates(slot.id).map((c) => ({ value: String(c.id), label: c.label }))"
              :aria-label="`加到${slotName(slot.id)}`"
              @update:model-value="addEntry(slot.id, $event)"
            />
          </div>
          <p v-if="slotErrors[slot.id]" class="set-error" role="alert">{{ slotErrors[slot.id] }}</p>
        </div>
        <template #foot>
          <button type="button" class="set-button set-button--primary" :disabled="!slotsDirty || busy === 'slots'" @click="saveSlots">
            <Loader2 v-if="busy === 'slots'" class="animate-spin" aria-hidden="true" />
            儲存
          </button>
          <button v-if="slotsDirty" type="button" class="set-button set-button--text" @click="overview && apply(overview)">還原</button>
          <p v-if="reindexHint" class="set-notice set-notice--warn basis-full">
            語意搜尋的模型換了：既有收藏要重建向量才找得到。在伺服器的專案資料夾執行 <code>python scripts/rebuild_embeddings.py</code>。
          </p>
        </template>
      </SettingBlock>
    </template>

    <ConfirmDialog
      :open="!!removing"
      :title="`刪除「${removing?.label ?? ''}」？`"
      :description="removeText"
      confirm-label="刪除連線"
      danger
      :busy="!!removing && busy === `delete-${removing.id}`"
      @update:open="(open: boolean) => { if (!open) removing = null }"
      @confirm="remove"
    />
  </div>
</template>
