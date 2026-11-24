<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import {
  ArrowLeft, CheckCircle2, Clock, ExternalLink, Loader2, RefreshCw,
  Scale, ShieldAlert, ShieldCheck, ShieldQuestion, Sparkles, X,
} from 'lucide-vue-next'
import { toast } from 'vue-sonner'
import { useEvaluationsStore } from '@/stores/evaluations'
import { useUiStore } from '@/stores/ui'
import { useItemsStore } from '@/stores/items'
import {
  AGENT_STATUS_LABELS,
  EVAL_FILTER_TABS,
  REJECT_REASONS,
  resolveBadgeUi,
  suggestedTriggerWhen,
} from '@/lib/evalUi'
import * as api from '@/lib/api'

const store = useEvaluationsStore()
const ui = useUiStore()
const itemsStore = useItemsStore()

const active = computed(() => store.activeEvaluation)
const badge = computed(() => resolveBadgeUi(active.value?.security_badge))
const showAllCounterpoints = ref(false)
const actionMode = ref<'none' | 'on_demand' | 'reject'>('none')
const triggerInput = ref('')
const decisionNote = ref('')

const counterpoints = computed(() => active.value?.community_counterpoints || [])
const visibleCounterpoints = computed(() =>
  showAllCounterpoints.value ? counterpoints.value : counterpoints.value.slice(0, 2),
)

const l0Github = computed(() => active.value?.l0?.github || {})
const l1 = computed(() => active.value?.l1 || {})
const slotComparison = computed(() => l1.value?.slot_comparison)

function resetDecisionDraft() {
  actionMode.value = 'none'
  decisionNote.value = active.value?.decision_note || ''
  triggerInput.value = active.value ? suggestedTriggerWhen(active.value) : ''
  showAllCounterpoints.value = false
}

watch(
  () => active.value?.id,
  () => resetDecisionDraft(),
)

watch(
  () => ui.evalFocusId,
  (id) => {
    if (id) void store.openEvaluation(id)
  },
  { immediate: true },
)

let inHistory = false

function pushEvalHistory() {
  if (typeof window === 'undefined' || typeof window.history?.pushState !== 'function') return
  window.history.pushState({ ...(window.history.state || {}), omnikeepEval: true }, '')
  inHistory = true
}

function onPopState() {
  if (!inHistory) return
  inHistory = false
  if (active.value) {
    backFromDetail()
    pushEvalHistory()
  } else {
    closeWorkspace()
  }
}

onMounted(() => {
  void store.loadEvaluations(store.statusFilter)
  if (ui.evalFocusId) void store.openEvaluation(ui.evalFocusId)
  window.addEventListener?.('keydown', onKeydown)
  pushEvalHistory()
  window.addEventListener?.('popstate', onPopState)
})

onUnmounted(() => {
  window.removeEventListener?.('keydown', onKeydown)
  window.removeEventListener?.('popstate', onPopState)
  if (inHistory && window.history?.state?.omnikeepEval) {
    inHistory = false
    window.history.back()
  }
})

function onKeydown(e: KeyboardEvent) {
  if (e.key !== 'Escape') return
  e.preventDefault()
  if (active.value) {
    store.clearActive()
  } else {
    ui.closeEvaluations()
  }
}

function backFromDetail() {
  store.clearActive()
  ui.evalFocusId = null
}

function closeWorkspace() {
  store.clearActive()
  ui.closeEvaluations()
}

function openOriginalItem() {
  const itemId = active.value?.item_id
  if (!itemId) return
  closeWorkspace()
  window.dispatchEvent(new CustomEvent('open-item', { detail: { itemId } }))
}

async function handleApproveL2() {
  if (!active.value || store.deciding) return
  try {
    await store.submitDecision(active.value.id, {
      decision: 'approve_l2',
      note: decisionNote.value.trim() || '手機核准進桌機 L2 實測',
    })
    toast.success('已加入桌機 L2 待實測清單', { description: '只進待測佇列，不會在背景自動安裝。' })
    void itemsStore.refreshAll()
  } catch (e) {
    toast.error('拍板送出失敗', { description: e instanceof Error ? e.message : String(e) })
  }
}

function openOnDemandMode() {
  if (!active.value) return
  triggerInput.value = suggestedTriggerWhen(active.value)
  actionMode.value = actionMode.value === 'on_demand' ? 'none' : 'on_demand'
}

async function handleOnDemand() {
  if (!active.value || store.deciding) return
  const condition = triggerInput.value.trim() || suggestedTriggerWhen(active.value)
  try {
    await store.submitDecision(active.value.id, {
      decision: 'on_demand',
      note: decisionNote.value.trim(),
      trigger_when: condition,
    })
    actionMode.value = 'none'
    toast.success('已收為情境備案', { description: '平日維持 0 token 常駐，需要時由 MCP 按條件召回。' })
    void itemsStore.refreshAll()
  } catch (e) {
    toast.error('儲存備案失敗', { description: e instanceof Error ? e.message : String(e) })
  }
}

async function handleReject(quickReason = '') {
  if (!active.value || store.deciding) return
  const note = quickReason || decisionNote.value.trim() || '不採用，防重複推薦'
  try {
    await store.submitDecision(active.value.id, {
      decision: 'reject',
      note,
    })
    actionMode.value = 'none'
    toast.success('已記錄拒絕原因')
    void itemsStore.refreshAll()
  } catch (e) {
    toast.error('記錄拒絕失敗', { description: e instanceof Error ? e.message : String(e) })
  }
}

async function handleRetryEval() {
  if (!active.value) return
  try {
    const ev = await api.triggerItemEvaluation(active.value.item_id, {
      user_note: active.value.user_note || '',
      sync: false,
    })
    await store.openEvaluation(ev.evaluation.id)
    await store.loadEvaluations(store.statusFilter)
    toast.success('已重新排入背景評估')
  } catch (e) {
    toast.error('重試失敗', { description: e instanceof Error ? e.message : String(e) })
  }
}

function tabCount(id: string): number {
  const c = store.counts
  if (id === 'needs_decision') return c.needs_decision
  if (id === 'evaluating') return c.evaluating
  if (id === 'approved_l2') return c.approved_l2
  if (id === 'on_demand') return c.on_demand
  if (id === 'rejected') return c.rejected
  return 0
}
</script>

<template>
  <section
    class="safe-top fixed inset-0 z-50 flex flex-col bg-shell text-foreground"
    role="dialog"
    aria-modal="true"
    aria-label="工具評估與拍板台"
  >
    <!-- Top bar -->
    <header class="flex h-14 shrink-0 items-center justify-between gap-2 border-b border-hairline bg-shell px-3 sm:px-6">
      <div class="flex min-w-0 items-center gap-2">
        <button
          v-if="active"
          type="button"
          class="inline-flex min-h-11 items-center gap-1.5 rounded-lg px-2.5 text-sm font-medium text-foreground hover:bg-accent"
          @click="backFromDetail"
        >
          <ArrowLeft class="size-4" />
          <span>清單</span>
        </button>
        <div v-else class="flex items-center gap-2 pl-1">
          <Scale class="size-4 text-primary" aria-hidden="true" />
          <h1 class="truncate text-base font-semibold">工具評估拍板台</h1>
        </div>
      </div>

      <div class="flex shrink-0 items-center gap-1.5">
        <button
          type="button"
          class="inline-flex min-h-11 min-w-11 items-center justify-center rounded-lg text-muted-foreground hover:bg-accent hover:text-foreground"
          title="重新整理"
          aria-label="重新整理"
          @click="active ? store.openEvaluation(active.id) : store.loadEvaluations(store.statusFilter)"
        >
          <RefreshCw class="size-4" :class="store.loading || store.loadingDetail ? 'animate-spin' : ''" />
        </button>
        <button
          type="button"
          class="inline-flex min-h-11 min-w-11 items-center justify-center rounded-lg text-muted-foreground hover:bg-accent hover:text-foreground"
          title="關閉"
          aria-label="關閉評估拍板台"
          @click="closeWorkspace"
        >
          <X class="size-5" />
        </button>
      </div>
    </header>

    <!-- Single evaluation decision sheet -->
    <template v-if="active">
      <div class="mobile-scroll min-h-0 flex-1 overflow-x-hidden overflow-y-auto px-4 pb-36 pt-4 sm:px-6">
        <div class="mx-auto max-w-2xl space-y-5">
          <!-- 1. Top summary + security badge -->
          <div class="space-y-3 rounded-xl border border-hairline bg-card p-4">
            <div class="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
              <span class="font-mono">{{ active.target_repo || '一般評估項目' }}</span>
              <div class="flex items-center gap-2">
                <span class="rounded border border-hairline px-2 py-0.5 font-mono">
                  {{ active.adapter === 'omnikit' ? 'OmniKit L0/L1' : '本機輕量評估' }}
                </span>
                <span class="rounded border border-hairline px-2 py-0.5">
                  {{ AGENT_STATUS_LABELS[active.agent_status || 'needs_decision'] || active.agent_status }}
                </span>
              </div>
            </div>

            <h2 class="text-lg font-bold leading-snug text-foreground">
              {{ l1.name || active.item_title || '未命名項目' }}
            </h2>

            <!-- GitHub metrics if known -->
            <div
              v-if="l0Github.stars != null || l0Github.license || l0Github.pushed_at"
              class="flex flex-wrap items-center gap-3 text-xs text-muted-foreground"
            >
              <span v-if="l0Github.stars != null">★ {{ Number(l0Github.stars).toLocaleString() }}</span>
              <span v-if="l0Github.license">授權 {{ l0Github.license }}</span>
              <span v-if="l0Github.pushed_at">最近更新 {{ String(l0Github.pushed_at).slice(0, 10) }}</span>
              <span v-if="l0Github.archived" class="font-semibold text-red-600 dark:text-red-400">已封存倉庫</span>
            </div>

            <!-- Security 3-state badge -->
            <div class="flex items-start gap-2.5 rounded-lg border px-3 py-2.5 text-sm" :class="badge.pillClass">
              <ShieldCheck v-if="badge.tone === 'green'" class="mt-0.5 size-4 shrink-0" />
              <ShieldAlert v-else-if="badge.tone === 'red'" class="mt-0.5 size-4 shrink-0" />
              <ShieldQuestion v-else class="mt-0.5 size-4 shrink-0" />
              <div class="min-w-0">
                <div class="font-semibold">{{ badge.label }}</div>
                <p class="mt-0.5 text-xs opacity-90">{{ badge.detail }}</p>
              </div>
            </div>

            <div class="flex flex-wrap gap-2 pt-1">
              <a
                v-if="active.target_url || active.item_url"
                :href="active.target_url || active.item_url"
                target="_blank"
                rel="noopener noreferrer"
                class="inline-flex min-h-11 items-center gap-1.5 rounded-lg border border-hairline px-3 text-xs font-medium text-foreground hover:bg-accent"
              >
                <ExternalLink class="size-3.5" />
                開啟原始倉庫／連結
              </a>
              <button
                type="button"
                class="inline-flex min-h-11 items-center gap-1.5 rounded-lg border border-hairline px-3 text-xs font-medium text-foreground hover:bg-accent"
                @click="openOriginalItem"
              >
                看完整收藏與原文
              </button>
            </div>
          </div>

          <!-- Failed banner -->
          <div
            v-if="active.status === 'failed'"
            class="space-y-3 rounded-xl border border-red-500/40 bg-red-500/10 p-4 text-sm"
          >
            <div class="font-semibold text-red-700 dark:text-red-300">背景預研未完成</div>
            <p class="text-xs leading-relaxed text-muted-foreground">{{ active.error_message || '未知錯誤' }}</p>
            <button
              type="button"
              class="inline-flex min-h-11 items-center gap-1.5 rounded-lg bg-primary px-4 text-sm font-semibold text-primary-foreground hover:bg-primary-hover"
              @click="handleRetryEval"
            >
              <RefreshCw class="size-4" />
              重新執行評估
            </button>
          </div>

          <!-- 2. My user_note / question -->
          <section v-if="active.user_note" class="rounded-xl border border-primary/30 bg-primary/5 p-4">
            <h3 class="text-xs font-semibold uppercase tracking-wide text-primary">我的收藏疑問</h3>
            <p class="mt-1.5 text-sm leading-relaxed text-foreground">{{ active.user_note }}</p>
          </section>

          <!-- 3. L1 verdict & slot comparison -->
          <section class="space-y-3 rounded-xl border border-hairline bg-card p-4">
            <h3 class="text-sm font-semibold text-foreground">L1 核心判讀與現任對照</h3>
            <p class="text-sm leading-relaxed text-foreground">
              {{ l1.summary || active.item_summary || '（背景預研中，稍後可點右上重整）' }}
            </p>

            <div v-if="slotComparison" class="rounded-lg border border-hairline bg-shell p-3 text-xs space-y-1.5">
              <div v-if="slotComparison.matched_slots?.length">
                <span class="font-semibold text-muted-foreground">命中槽位：</span>
                <span class="font-mono text-foreground">{{ slotComparison.matched_slots.join('、') }}</span>
              </div>
              <div v-if="slotComparison.incumbent_tools?.length">
                <span class="font-semibold text-muted-foreground">現任工具：</span>
                <span class="text-foreground">{{ slotComparison.incumbent_tools.join('、') }}</span>
              </div>
              <div v-if="slotComparison.delta_summary">
                <span class="font-semibold text-muted-foreground">差異判讀：</span>
                <span class="text-foreground">{{ slotComparison.delta_summary }}</span>
              </div>
            </div>

            <p v-if="l1.differences" class="text-xs leading-relaxed text-muted-foreground">
              <span class="font-semibold text-foreground">主要差異與門檻：</span>{{ l1.differences }}
            </p>

            <div v-if="l1.claims?.length" class="space-y-1.5 pt-1">
              <div class="text-xs font-semibold text-muted-foreground">待 L2 驗證宣稱（{{ l1.claims.length }}）</div>
              <ul class="space-y-1.5 text-xs">
                <li v-for="(c, i) in l1.claims" :key="i" class="rounded-lg border border-hairline bg-shell px-3 py-2">
                  <div class="font-medium text-foreground">{{ c.claim }}</div>
                  <div v-if="c.how_to_verify" class="mt-0.5 text-muted-foreground">驗證：{{ c.how_to_verify }}</div>
                </li>
              </ul>
            </div>
          </section>

          <!-- 4. Community counterpoints -->
          <section v-if="counterpoints.length" class="space-y-2.5 rounded-xl border border-hairline bg-card p-4">
            <div class="flex items-center justify-between">
              <h3 class="text-sm font-semibold text-foreground">社群實測與反例（{{ counterpoints.length }}）</h3>
              <button
                v-if="counterpoints.length > 2"
                type="button"
                class="min-h-11 px-2 text-xs font-medium text-primary hover:underline"
                @click="showAllCounterpoints = !showAllCounterpoints"
              >
                {{ showAllCounterpoints ? '收起部分' : `展開全部 ${counterpoints.length} 條` }}
              </button>
            </div>
            <ul class="space-y-2 text-xs">
              <li
                v-for="(cp, idx) in visibleCounterpoints"
                :key="idx"
                class="rounded-lg border border-hairline bg-shell px-3 py-2 leading-relaxed text-foreground"
              >
                <span class="mr-1.5 font-mono text-2xs uppercase text-muted-foreground">[{{ cp.category }}]</span>
                <span>{{ cp.point }}</span>
              </li>
            </ul>
          </section>

          <!-- Existing decision summary -->
          <section v-if="active.decision" class="rounded-xl border border-hairline bg-card p-4 text-xs space-y-1">
            <div class="flex items-center gap-1.5 font-semibold text-foreground">
              <CheckCircle2 class="size-4 text-primary" />
              <span>目前拍板：{{ AGENT_STATUS_LABELS[active.agent_status || ''] || active.decision }}</span>
            </div>
            <p v-if="active.trigger_when" class="text-muted-foreground">觸發條件：{{ active.trigger_when }}</p>
            <p v-if="active.decision_note" class="text-muted-foreground">備註：{{ active.decision_note }}</p>
          </section>
        </div>
      </div>

      <!-- 5. Sticky single-handed bottom decision bar -->
      <footer class="safe-bottom shrink-0 border-t border-hairline bg-shell px-3 py-3 sm:px-6">
        <div class="mx-auto max-w-2xl space-y-2.5">
          <!-- Expandable on_demand drawer -->
          <div v-if="actionMode === 'on_demand'" class="space-y-2 rounded-xl border border-hairline bg-card p-3">
            <label class="block text-xs font-semibold text-foreground" for="eval-trigger-input">
              何時才召回這個備案？（平日保持 0 token 常駐）
            </label>
            <input
              id="eval-trigger-input"
              v-model="triggerInput"
              type="text"
              class="w-full rounded-lg border border-hairline bg-shell px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-primary/40"
              placeholder="例如：遇到大型 PDF 轉檔太慢時再用"
            />
            <div class="flex justify-end gap-2">
              <button
                type="button"
                class="min-h-11 rounded-lg px-3 text-xs font-medium text-muted-foreground hover:bg-accent"
                @click="actionMode = 'none'"
              >
                取消
              </button>
              <button
                type="button"
                :disabled="store.deciding"
                class="inline-flex min-h-11 items-center gap-1.5 rounded-lg bg-primary px-4 text-xs font-semibold text-primary-foreground hover:bg-primary-hover disabled:opacity-50"
                @click="handleOnDemand"
              >
                確認收為備案
              </button>
            </div>
          </div>

          <!-- Expandable reject drawer -->
          <div v-else-if="actionMode === 'reject'" class="space-y-2 rounded-xl border border-hairline bg-card p-3">
            <div class="text-xs font-semibold text-foreground">選擇或填寫拒絕理由（防日後重複推薦）</div>
            <div class="flex flex-wrap gap-1.5">
              <button
                v-for="reason in REJECT_REASONS"
                :key="reason"
                type="button"
                :disabled="store.deciding"
                class="min-h-11 rounded-lg border border-hairline bg-shell px-3 text-xs text-foreground hover:bg-accent"
                @click="handleReject(reason)"
              >
                {{ reason }}
              </button>
            </div>
            <div class="flex gap-2">
              <input
                v-model="decisionNote"
                type="text"
                class="min-w-0 flex-1 rounded-lg border border-hairline bg-shell px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-primary/40"
                placeholder="或輸入其他原因…"
              />
              <button
                type="button"
                :disabled="store.deciding"
                class="min-h-11 rounded-lg bg-red-600 px-4 text-xs font-semibold text-white hover:bg-red-700 disabled:opacity-50"
                @click="handleReject()"
              >
                拒絕
              </button>
            </div>
          </div>

          <!-- Three main single-thumb decision buttons -->
          <div class="grid grid-cols-3 gap-2">
            <button
              type="button"
              :disabled="store.deciding"
              class="inline-flex min-h-12 flex-col items-center justify-center rounded-xl bg-primary px-2 py-1.5 text-center text-xs font-semibold text-primary-foreground hover:bg-primary-hover disabled:opacity-50"
              @click="handleApproveL2"
            >
              <Loader2 v-if="store.deciding" class="size-4 animate-spin" />
              <span v-else>核准進 L2</span>
              <span class="text-[10px] font-normal opacity-85">僅入待實測</span>
            </button>

            <button
              type="button"
              :disabled="store.deciding"
              class="inline-flex min-h-12 flex-col items-center justify-center rounded-xl border border-hairline bg-card px-2 py-1.5 text-center text-xs font-semibold text-foreground hover:bg-accent disabled:opacity-50"
              @click="openOnDemandMode"
            >
              <span>收為備案</span>
              <span class="text-[10px] font-normal text-muted-foreground">0 token 常駐</span>
            </button>

            <button
              type="button"
              :disabled="store.deciding"
              class="inline-flex min-h-12 flex-col items-center justify-center rounded-xl border border-hairline bg-card px-2 py-1.5 text-center text-xs font-semibold text-muted-foreground hover:bg-accent hover:text-foreground disabled:opacity-50"
              @click="actionMode = actionMode === 'reject' ? 'none' : 'reject'"
            >
              <span>拒絕</span>
              <span class="text-[10px] font-normal">記理由防重推</span>
            </button>
          </div>
        </div>
      </footer>
    </template>

    <!-- Evaluation Queue List -->
    <template v-else>
      <!-- Filter strip -->
      <div class="flex shrink-0 gap-1.5 overflow-x-auto border-b border-hairline bg-shell px-3 py-2.5 sm:px-6">
        <button
          v-for="tab in EVAL_FILTER_TABS"
          :key="tab.id"
          type="button"
          class="inline-flex min-h-10 shrink-0 items-center gap-1.5 rounded-lg border px-3 text-xs font-medium transition-colors"
          :class="
            store.statusFilter === tab.id
              ? 'border-primary bg-primary text-primary-foreground'
              : 'border-hairline bg-card text-muted-foreground hover:bg-accent hover:text-foreground'
          "
          @click="store.loadEvaluations(tab.id)"
        >
          <span>{{ tab.label }}</span>
          <span v-if="tabCount(tab.id)" class="tabular-nums opacity-85">{{ tabCount(tab.id) }}</span>
        </button>
      </div>

      <div class="mobile-scroll min-h-0 flex-1 overflow-x-hidden overflow-y-auto px-3 py-4 sm:px-6">
        <div class="mx-auto max-w-2xl space-y-2.5">
          <div v-if="store.loading && !store.evaluations.length" class="flex items-center justify-center py-16 text-sm text-muted-foreground">
            <Loader2 class="mr-2 size-4 animate-spin" />
            載入評估清單…
          </div>

          <div v-else-if="store.error" class="rounded-xl border border-red-500/40 bg-red-500/10 p-4 text-sm text-red-600 dark:text-red-300">
            {{ store.error }}
          </div>

          <div v-else-if="!store.evaluations.length" class="rounded-xl border border-hairline bg-card p-8 text-center text-sm text-muted-foreground">
            <Sparkles class="mx-auto mb-2 size-5 opacity-60" />
            <p>這個狀態目前沒有待處理項目。</p>
            <p class="mt-1 text-xs">用 iPhone 捷徑或任何收藏頁按「送去評估」，背景就會先跑完 L0/L1 等你拍板。</p>
          </div>

          <button
            v-for="ev in store.evaluations"
            :key="ev.id"
            type="button"
            class="flex w-full flex-col gap-2 rounded-xl border border-hairline bg-card p-4 text-left transition-colors hover:border-primary/40 hover:bg-accent/40"
            @click="store.openEvaluation(ev.id)"
          >
            <div class="flex w-full items-center justify-between gap-2">
              <span class="truncate text-sm font-semibold text-foreground">
                {{ ev.l1?.name || ev.target_repo || ev.item_title }}
              </span>
              <span
                class="shrink-0 rounded-md border px-2 py-0.5 text-[11px] font-medium"
                :class="resolveBadgeUi(ev.security_badge).pillClass"
              >
                {{ ev.status === 'queued' || ev.status === 'running_l0' ? '預研中' : resolveBadgeUi(ev.security_badge).label }}
              </span>
            </div>

            <p v-if="ev.user_note" class="line-clamp-1 text-xs text-primary">
              問：{{ ev.user_note }}
            </p>
            <p class="line-clamp-2 text-xs leading-relaxed text-muted-foreground">
              {{ ev.l1?.summary || ev.item_summary || ev.error_message || '正在背景執行 L0/L1 檢查…' }}
            </p>

            <div class="flex items-center gap-2 text-[11px] text-subtle-foreground">
              <Clock class="size-3" />
              <span>{{ ev.target_repo || ev.item_url }}</span>
            </div>
          </button>
        </div>
      </div>
    </template>
  </section>
</template>
