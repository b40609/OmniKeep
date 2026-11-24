<script setup lang="ts">
import { ref, computed, watch, nextTick, onBeforeUnmount } from 'vue'
import { toast } from 'vue-sonner'
import { Link2, Package, ChevronRight, ChevronLeft, Camera, Sparkles, Network, ExternalLink, ArrowRight, ArrowUpRight, List, Hash, FileText, CornerUpLeft, Loader2, Scale } from 'lucide-vue-next'
import Badge from '@/components/ui/badge/Badge.vue'
import ItemCover from '@/components/items/ItemCover.vue'
import OriginIcon from '@/components/reader/OriginIcon.vue'
import { analyzeItem, getServiceStatus, type Item } from '@/lib/api'
import { isNotAnalysed, plainSummary } from '@/lib/wall'
import { originLink } from '@/lib/originLink'
import { useItemsStore } from '@/stores/items'
import { useEvaluationsStore } from '@/stores/evaluations'
import { AGENT_STATUS_LABELS, resolveBadgeUi } from '@/lib/evalUi'
import { cleanHost, displayCategory, formatRelativeTime, estimateReadTime, sourceMeta } from '@/lib/format'
import { renderMarkdown, useCodeCopy, extractToc } from '@/lib/markdown'
import { renderMermaidIn } from '@/lib/mermaid'
import { renderFlowsIn, disposeFlowsIn } from '@/lib/flowchart'
import { renderArchIn, disposeArchIn } from '@/lib/archchart'
import DeepDiagram from '@/components/reader/DeepDiagram.vue'
import ReaderOutline from '@/components/reader/ReaderOutline.vue'
import { useUiStore } from '@/stores/ui'
import { useMutations } from '@/composables/useMutations'
import { useSnapshotAvailable } from '@/composables/useSnapshotAvailable'

const ui = useUiStore()
const itemsStore = useItemsStore()
const evaluationsStore = useEvaluationsStore()
const { openSnapshot } = useMutations()
const hasSnapshot = useSnapshotAvailable()
const requestingEval = ref(false)

async function triggerEvalFromReader() {
  const item = ui.activeItem
  if (!item || requestingEval.value) return
  requestingEval.value = true
  try {
    const ev = await evaluationsStore.requestEvaluation(item.id, item.user_note || '', false)
    if (ui.activeItem?.id === item.id) {
      ui.activeItem = { ...ui.activeItem, agent_status: 'queued', latest_evaluation: ev }
    }
    toast.success('已送出背景評估（L0/L1）', {
      action: { label: '打開拍板台', onClick: () => ui.openEvaluations(ev.id) },
    })
  } catch (e) {
    toast.error('送出評估失敗', { description: e instanceof Error ? e.message : String(e) })
  } finally {
    requestingEval.value = false
  }
}
// the page this item was kept from: the button under the title, the source line and the cover all open it
const origin = computed(() => originLink(ui.activeItem?.url))

// An item kept while no AI was connected: say so, and offer the next step.
const notAnalysed = computed(() => !!ui.activeItem && isNotAnalysed(ui.activeItem))
/** null until the server has said whether an AI connection exists. */
const aiConnected = ref<boolean | null>(null)
const analysing = ref(false)

async function checkAi() {
  try {
    aiConnected.value = !(await getServiceStatus()).needs_setup
  } catch {
    aiConnected.value = null
  }
}
// Asked when such an item is opened, and again after settings are saved (a connection was added).
watch(() => [notAnalysed.value, ui.settingsVersion] as const, ([waiting]) => { if (waiting) void checkAi() }, { immediate: true })

async function analyseNow() {
  const item = ui.activeItem
  if (!item || analysing.value) return
  analysing.value = true
  try {
    const { item: analysed } = await analyzeItem(item.id)
    if (ui.activeItem?.id === item.id) ui.activeItem = { ...ui.activeItem, ...analysed }
    toast.success('分析完成')
    void itemsStore.refreshAll()
  } catch (e) {
    toast.error('這次沒有分析成功', { description: e instanceof Error ? e.message : String(e) })
    void checkAi()
  } finally {
    analysing.value = false
  }
}
const contentRef = ref<HTMLElement | null>(null)
let detachCodeCopy: (() => void) | null = null

// Re-attach code-copy handlers whenever the markdown re-renders.
watch(
  () => [ui.activeItem?.id, ui.activeItem?.deep_analysis] as const,
  async () => {
    detachCodeCopy?.()
    detachCodeCopy = null
    // no dispose here: the same markdown again keeps its drawn diagrams (disposing them left them blank
    // forever, 2026-11-17); render*In stops the ones whose blocks were replaced
    if (!ui.activeItem?.deep_analysis) return
    await nextTick()
    detachCodeCopy = useCodeCopy(contentRef.value)
    void renderMermaidIn(contentRef.value)
    renderFlowsIn(contentRef.value)
    renderArchIn(contentRef.value)
  },
  { immediate: true },
)
onBeforeUnmount(() => { detachCodeCopy?.(); disposeFlowsIn(contentRef.value); disposeArchIn(contentRef.value) })

// a github.com/owner/repo address: what the agent prompt clones
const isGithubProject = computed(() => /^https?:\/\/(www\.)?github\.com\/[\w.-]+\/[\w.-]+\/?(?:[#?].*)?$/i.test(ui.activeItem?.url || ''))

const tocItems = computed(() => extractToc(ui.activeItem?.deep_analysis))
function scrollToHeading(id: string) { document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' }) }

// Full-page reading on a wide screen: the outline on the left, the item's details on the right; each
// folds away ([ ]). When the window cannot fit both beside the 44rem column, the details go back under it.
const outlineOn = computed(() => ui.outlineShown)
const railOn = computed(() => ui.railShown)
const mainRef = ref<HTMLElement | null>(null)
// the previous and next item of the list the reader came from (J / K do the same)
const neighbours = computed(() => {
  const list = itemsStore.visibleItems
  const k = list.findIndex((i) => i.id === ui.activeItem?.id)
  return { prev: k > 0 ? list[k - 1] : null, next: k >= 0 && k < list.length - 1 ? list[k + 1] : null }
})
const shortTitle = (it: Item) => (it.title_l1 || '').split(/[：:]/)[0]

function openItem(id: number | string) {
  ui.activeItem = { id: Number(id) } as Item // skeleton placeholder, replaced by full fetch in ReaderPane
}
</script>

<template>
  <!-- 44rem less the padding is 40rem: about 40 Chinese characters a line, however wide the pane gets -->
  <div v-if="ui.activeItem" class="reader-layout" :class="{ 'has-outline': outlineOn, 'has-rail': railOn }">
  <aside v-if="outlineOn" class="reader-side reader-side--left"><ReaderOutline :root="mainRef" :version="ui.activeItem.id" /></aside>
  <div ref="mainRef" class="reader-main mx-auto w-full max-w-[44rem] space-y-6 p-5 lg:p-8">
    <!-- Article header: the title comes first, the cover under it -->
    <header class="pb-1">
      <h1 class="text-xl leading-snug font-bold tracking-tight text-foreground lg:text-2xl">
        {{ ui.activeItem.title_l1 }}
      </h1>
      <!-- Primary action row: open original page, plus offline snapshot beside it at matching height -->
      <div v-if="origin || (!railOn && hasSnapshot)" class="mt-3 flex flex-wrap items-center gap-2">
        <a
          v-if="origin"
          :href="origin.href"
          target="_blank"
          rel="noopener noreferrer"
          class="reader-origin !mt-0"
          :title="origin.href"
        >
          <OriginIcon :origin="origin" class="reader-origin__icon" />
          <span>{{ origin.action }}</span>
          <ArrowUpRight class="size-4" aria-hidden="true" />
          <span class="sr-only">（新分頁）</span>
        </a>
        <button
          v-if="!railOn && hasSnapshot"
          type="button"
          class="inline-flex min-h-11 cursor-pointer items-center gap-2 rounded-[10px] bg-surface-2 px-4 text-sm font-medium text-foreground transition-colors hover:bg-surface-3"
          title="開啟收錄時保存的離線網頁"
          @click="openSnapshot(ui.activeItem)"
        >
          <Camera class="size-4 text-muted-foreground" aria-hidden="true" />
          <span>離線快照</span>
        </button>
      </div>
      <!-- with the details rail open, all of this lives there (the snapshot too), so the title stands alone -->
      <div v-if="!railOn" class="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs leading-5 text-subtle-foreground">
        <a v-if="origin" :href="origin.href" target="_blank" rel="noopener noreferrer" class="reader-source">
          <OriginIcon :origin="origin" class="reader-source__icon" />{{ cleanHost(ui.activeItem.url) }}<ArrowUpRight class="size-3" aria-hidden="true" />
        </a>
        <span v-else>{{ cleanHost(ui.activeItem.url) }}</span>
        <span class="whitespace-nowrap">{{ ui.activeItem.published_date || formatRelativeTime(ui.activeItem.created_at) }}</span>
        <span v-if="ui.activeItem.author" class="break-words">{{ ui.activeItem.author }}</span>
        <span
          v-if="ui.activeItem.content_raw"
          class="whitespace-nowrap"
          :title="`約 ${estimateReadTime(ui.activeItem.content_raw)} 分鐘`"
        >約 {{ estimateReadTime(ui.activeItem.content_raw) }} 分鐘</span>
      </div>
    </header>

    <!-- Cover: same rules as the wall, and simply absent when there is none -->
    <ItemCover :item="ui.activeItem" variant="hero" class="reader-cover" :href="origin?.href" />

    <!-- Cited-in backlinks (in the details rail when it is open) -->
    <Teleport defer to="#reader-rail-slot" :disabled="!railOn">
    <section
      v-if="ui.activeItem.citations?.length"
      class="border-t border-hairline pt-6"
      aria-label="收錄與引用來源"
    >
      <div class="mb-3 flex items-center justify-between">
        <div class="flex items-center gap-2">
          <span class="text-muted-foreground">
            <Link2 class="size-3.5" />
          </span>
          <h2 class="text-base font-semibold text-foreground">
            收錄與引用（{{ ui.activeItem.citations.length }}）
          </h2>
        </div>
      </div>
      <div class="space-y-2">
        <button
          v-for="cit in ui.activeItem.citations"
          :key="cit.citation_id"
          class="group flex min-h-11 w-full flex-wrap items-start justify-between gap-3 border-b border-hairline py-3 text-left transition-colors hover:bg-accent"
          @click="openItem(cit.parent_id)"
        >
          <div class="min-w-0 flex-1">
            <div class="mb-1 flex items-center gap-2">
              <Badge :class="sourceMeta(cit.parent_source_type).badgeClass">{{ cit.parent_source_type }}</Badge>
              <span class="line-clamp-2 text-sm font-semibold text-foreground group-hover:text-primary-soft-foreground">
                {{ cit.parent_title }}
              </span>
            </div>
            <p v-if="cit.mention_context" class="line-clamp-2 text-sm leading-relaxed text-muted-foreground">
              「{{ cit.mention_context }}」
            </p>
          </div>
          <span class="flex shrink-0 items-center gap-0.5 pt-1 text-xs text-subtle-foreground group-hover:text-primary-soft-foreground">
            閱讀來源 <ChevronRight class="size-3.5" />
          </span>
        </button>
      </div>
    </section>
    </Teleport>

    <!-- User note & Agent evaluation bridge -->
    <section
      v-if="ui.activeItem.user_note || ui.activeItem.latest_evaluation || (ui.activeItem.agent_status && ui.activeItem.agent_status !== 'none') || isGithubProject"
      class="border-t border-hairline pt-6 space-y-3"
      aria-label="備忘與工具評估"
    >
      <div v-if="ui.activeItem.user_note" class="rounded-xl border border-primary/30 bg-primary/5 px-4 py-3">
        <div class="text-xs font-semibold text-primary">我的收藏備忘／問題</div>
        <p class="mt-1 text-sm leading-relaxed text-foreground">{{ ui.activeItem.user_note }}</p>
      </div>

      <div class="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-hairline bg-card px-4 py-3">
        <div class="min-w-0 text-xs">
          <div class="flex flex-wrap items-center gap-2 font-semibold text-foreground">
            <Scale class="size-3.5 text-primary" aria-hidden="true" />
            <span>Agent 工具評估</span>
            <span v-if="ui.activeItem.agent_status && ui.activeItem.agent_status !== 'none'" class="rounded border border-hairline px-1.5 py-0.5 font-normal text-muted-foreground">
              {{ AGENT_STATUS_LABELS[ui.activeItem.agent_status] || ui.activeItem.agent_status }}
            </span>
            <span
              v-if="ui.activeItem.latest_evaluation?.security_badge"
              class="rounded border px-1.5 py-0.5 text-xs font-medium"
              :class="resolveBadgeUi(ui.activeItem.latest_evaluation.security_badge).pillClass"
            >
              {{ resolveBadgeUi(ui.activeItem.latest_evaluation.security_badge).label }}
            </span>
          </div>
        </div>
        <div class="flex shrink-0 items-center gap-2">
          <button
            v-if="ui.activeItem.latest_evaluation"
            type="button"
            class="inline-flex min-h-10 cursor-pointer items-center gap-1 rounded-lg bg-primary px-3 text-xs font-semibold text-primary-foreground hover:bg-primary-hover"
            @click="ui.openEvaluations(ui.activeItem.latest_evaluation.id)"
          >
            開啟拍板報告
          </button>
          <button
            type="button"
            :disabled="requestingEval"
            class="inline-flex min-h-10 cursor-pointer items-center gap-1 rounded-lg border border-hairline px-3 text-xs font-medium text-foreground hover:bg-accent disabled:opacity-50"
            @click="triggerEvalFromReader"
          >
            {{ requestingEval ? '排入中…' : ui.activeItem.latest_evaluation ? '重新評估' : '送去評估' }}
          </button>
        </div>
      </div>
    </section>

    <!-- L1 highlight -->
    <!-- Kept without analysis: what that means, and the one thing to do next -->
    <section v-if="notAnalysed" class="border-t border-hairline pt-6" aria-label="尚未分析">
      <h2 class="mb-2 text-base font-semibold text-foreground">尚未分析</h2>
      <p class="text-sm leading-relaxed text-muted-foreground">
        <template v-if="aiConnected">這則收藏已經存下標題、網址和原文，還沒有經過 AI 分析。會在背景自動補上，也可以現在就分析。</template>
        <template v-else>這則收藏已經存下標題、網址和原文，搜尋找得到。接上 AI 之後，會自動補上摘要、分類和重點。</template>
      </p>
      <div class="mt-3 flex flex-wrap gap-2">
        <button
          v-if="aiConnected"
          type="button"
          class="inline-flex min-h-10 cursor-pointer items-center gap-2 rounded-lg bg-primary px-4 text-sm font-semibold text-primary-foreground hover:bg-primary-hover disabled:opacity-50"
          :disabled="analysing"
          @click="analyseNow"
        >
          <Loader2 v-if="analysing" class="size-4 animate-spin" aria-hidden="true" />
          {{ analysing ? '分析中…' : '現在分析' }}
        </button>
        <button
          v-else
          type="button"
          class="inline-flex min-h-10 cursor-pointer items-center rounded-lg bg-primary px-4 text-sm font-semibold text-primary-foreground hover:bg-primary-hover"
          @click="ui.openSettings('ai')"
        >接上 AI</button>
        <button
          type="button"
          class="inline-flex min-h-10 cursor-pointer items-center rounded-lg px-3 text-sm font-medium text-foreground hover:bg-accent"
          @click="ui.detailTab = 'reader'"
        >看原文</button>
      </div>
    </section>

    <section v-if="plainSummary(ui.activeItem.summary_l1)" class="border-t border-hairline pt-6" :aria-label="notAnalysed ? '原文開頭' : '摘要'">
      <h2 class="mb-2 text-base font-semibold text-foreground">{{ notAnalysed ? '原文開頭' : '摘要' }}</h2>
      <p class="text-base leading-relaxed text-foreground">{{ plainSummary(ui.activeItem.summary_l1) }}</p>
      <div v-if="ui.activeItem.tech_tags?.length && !railOn" class="mt-3 flex flex-wrap gap-2 text-xs text-muted-foreground">
        <span
          v-for="tag in ui.activeItem.tech_tags.slice(0, 2)"
          :key="tag"
        >
          #{{ tag }}
        </span>
        <span v-if="ui.activeItem.tech_tags.length > 2" :title="ui.activeItem.tech_tags.slice(2).join('、')">+{{ ui.activeItem.tech_tags.length - 2 }}</span>
      </div>
    </section>

    <!-- Sub-entities bundle -->
    <section
      v-if="ui.activeItem.sub_entities?.length"
      class="border-t border-hairline pt-6"
      aria-label="相關項目"
    >
      <div class="mb-3 flex items-center justify-between">
        <div class="flex items-center gap-2">
          <span class="text-muted-foreground">
            <Package class="size-3.5" />
          </span>
          <h2 class="text-base font-semibold text-foreground">
            相關項目（{{ ui.activeItem.sub_entities.length }}）
          </h2>
        </div>
      </div>
      <div class="grid grid-cols-1 gap-2.5">
        <div
          v-for="sub in ui.activeItem.sub_entities"
          :key="sub.citation_id"
          class="border-b border-hairline py-4"
        >
          <div class="mb-1.5 flex flex-wrap items-start justify-between gap-2">
            <div class="flex min-w-0 items-center gap-2">
              <span class="line-clamp-2 text-sm font-semibold text-foreground">
                {{ sub.target_name || sub.title_l1 || '未命名專案' }}
              </span>
              <span v-if="sub.category_name" class="text-xs text-muted-foreground">
                {{ displayCategory(sub.category_name) }}
              </span>
            </div>
            <div class="flex shrink-0 items-center gap-1.5">
              <button
                v-if="sub.target_item_id"
                class="flex min-h-11 items-center gap-1 rounded-lg px-3 text-sm text-primary-soft-foreground transition-colors hover:bg-accent"
                title="在 OmniKeep 閱讀相關項目"
                @click="openItem(sub.target_item_id)"
              >
                開啟 <ChevronRight class="size-3" />
              </button>
              <a
                v-if="sub.target_canonical_url"
                :href="sub.target_canonical_url"
                target="_blank"
                rel="noopener noreferrer"
                class="inline-flex min-h-11 items-center rounded-lg px-3 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                title="開啟 GitHub 或官方網站"
              >
                原始連結
              </a>
            </div>
          </div>
          <p v-if="sub.mention_context" class="mb-1.5 text-sm leading-relaxed text-foreground">{{ sub.mention_context }}</p>
          <div v-if="sub.tech_tags?.length" class="flex flex-wrap gap-1">
            <span v-for="st in sub.tech_tags.slice(0, 2)" :key="st" class="text-xs text-muted-foreground">
              #{{ st }}
            </span>
          </div>
        </div>
      </div>
    </section>

    <!-- L2 deep analysis -->
    <section class="border-t border-hairline pt-6" aria-label="重點分析">
      <h2 class="mb-3 text-base font-semibold text-foreground">重點分析</h2>

      <!-- Table of Contents (TOC) -->
      <nav
        v-if="tocItems.length >= 2 && !outlineOn"
        class="mb-6 rounded-xl border border-hairline bg-surface-1 p-3.5"
        aria-label="目錄"
      >
        <div class="mb-2.5 flex items-center justify-between text-xs font-semibold text-muted-foreground">
          <span class="flex items-center gap-1.5">
            <List class="size-3.5 text-primary" />
            <span>目錄</span>
          </span>
          <span class="font-mono text-xs text-subtle-foreground">{{ tocItems.length }} 個章節</span>
        </div>
        <div class="flex flex-wrap gap-1.5 sm:grid sm:grid-cols-2 md:grid-cols-3">
          <a
            v-for="h in tocItems"
            :key="h.id"
            :href="'#' + h.id"
            class="group flex min-h-9 items-center gap-1.5 truncate rounded-lg border border-hairline bg-card px-2.5 py-1.5 text-xs text-foreground transition-colors hover:border-primary/50 hover:bg-surface-2 hover:text-primary"
            @click.prevent="scrollToHeading(h.id)"
          >
            <Hash class="size-3 shrink-0 text-muted-foreground group-hover:text-primary" />
            <span class="truncate">{{ h.text }}</span>
          </a>
        </div>
      </nav>
      <div v-if="ui.activeItem.deep_analysis" ref="contentRef" class="prose-reader text-base" v-html="renderMarkdown(ui.activeItem.deep_analysis)" />
      <div v-else class="py-8 text-center text-sm text-muted-foreground">
        這則收藏還沒有重點分析，可以改看「原文」。
      </div>
    </section>

    <!-- Community counterpoints extracted from social discussions -->
    <section
      v-if="ui.activeItem.community_counterpoints?.length"
      class="border-t border-hairline pt-6"
      aria-label="社群實測與反例"
    >
      <h2 class="mb-3 text-base font-semibold text-foreground">
        社群實測與反例（{{ ui.activeItem.community_counterpoints.length }}）
      </h2>
      <ul class="space-y-2 text-sm">
        <li
          v-for="(cp, idx) in ui.activeItem.community_counterpoints"
          :key="idx"
          class="rounded-xl border border-hairline bg-card px-4 py-3 leading-relaxed text-foreground"
        >
          <span class="mr-2 font-mono text-xs uppercase text-muted-foreground">[{{ cp.category }}]</span>
          <span>{{ cp.point }}</span>
        </li>
      </ul>
    </section>

    <!-- A deeper diagram from the user's own agent (Archify), GitHub projects only -->
    <DeepDiagram v-if="isGithubProject" :item-id="ui.activeItem.id" />

    <!-- Semantic Neighbors / Related Items (E4), in the details rail when it is open -->
    <Teleport defer to="#reader-rail-slot" :disabled="!railOn">
    <section
      v-if="ui.activeItem.related_items?.length"
      class="border-t border-hairline pt-6"
      aria-label="相關收藏"
    >
      <div class="mb-3 flex items-center justify-between">
        <div class="flex items-center gap-2">
          <Sparkles class="size-4 text-muted-foreground" />
          <h2 class="text-base font-semibold text-foreground">
            相關收藏（{{ ui.activeItem.related_items.length }}）
          </h2>
        </div>
      </div>

      <div class="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
        <div
          v-for="rel in ui.activeItem.related_items"
          :key="rel.id"
          class="group flex min-w-0 flex-col justify-between overflow-hidden rounded-xl border border-border/60 bg-muted/20 p-3.5 transition hover:border-primary/40 hover:bg-card cursor-pointer focus-visible:outline-2 focus-visible:outline-ring"
          role="button" tabindex="0" :aria-label="`開啟 ${rel.title_l1}`"
          @click="openItem(rel.id)" @keydown.enter.prevent="openItem(rel.id)" @keydown.space.prevent="openItem(rel.id)"
        >
          <div class="min-w-0">
            <div class="mb-1.5 flex items-center justify-between gap-1.5">
              <Badge variant="outline" class="min-w-0 truncate text-3xs font-mono">
                {{ displayCategory(rel.category_name) }}
              </Badge>
              <span
                v-if="rel.similarity"
                class="shrink-0 whitespace-nowrap rounded-full bg-primary/10 px-2 py-0.5 text-3xs font-mono font-bold text-primary"
              >
                {{ Math.round(rel.similarity * 100) }}% 相似
              </span>
            </div>
            <h3 class="line-clamp-2 break-words text-xs font-bold leading-snug text-foreground group-hover:text-primary">
              {{ rel.title_l1 }}
            </h3>
            <p v-if="rel.summary_l1" class="mt-1 line-clamp-2 break-words text-2xs leading-relaxed text-muted-foreground">
              {{ rel.summary_l1 }}
            </p>
          </div>

          <div class="mt-3 flex items-center justify-end text-3xs font-semibold text-primary">
            <span>開啟</span>
            <ArrowRight class="ml-1 size-3 transition-transform group-hover:translate-x-0.5" />
          </div>
        </div>
      </div>
    </section>
    </Teleport>

    <!-- Entity Knowledge Graph (E4) -->
    <section
      v-if="ui.activeItem.graph && ui.activeItem.graph.nodes.length > 1"
      class="border-t border-hairline pt-6"
      aria-label="關聯圖"
    >
      <div class="mb-3 flex items-center justify-between">
        <div class="flex items-center gap-2">
          <Network class="size-4 text-muted-foreground" />
          <h2 class="text-base font-semibold text-foreground">
            關聯圖（{{ ui.activeItem.graph.nodes.length }} 個節點、{{ ui.activeItem.graph.edges.length }} 條關聯）
          </h2>
        </div>
      </div>

      <!-- Graph Cluster Chips -->
      <div class="rounded-xl border border-border/60 bg-muted/20 p-4">
        <div class="flex flex-wrap items-center gap-2">
          <div
            v-for="node in ui.activeItem.graph.nodes"
            :key="node.id"
            class="flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-2xs font-medium transition"
            :class="[
              node.type === 'center'
                ? 'border-primary/50 bg-primary/10 text-primary font-bold shadow-xs'
                : node.type === 'backlink'
                ? 'border-indigo-500/40 bg-indigo-500/10 text-indigo-600 dark:text-indigo-400 hover:bg-indigo-500/20 cursor-pointer'
                : node.type === 'entity'
                ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 hover:bg-emerald-500/20'
                : 'border-border bg-card text-foreground hover:border-primary/40 cursor-pointer',
            ]"
            :role="node.type !== 'center' && node.id && !String(node.id).startsWith('ent-') ? 'button' : undefined"
            :tabindex="node.type !== 'center' && node.id && !String(node.id).startsWith('ent-') ? 0 : undefined"
            @click="node.type !== 'center' && node.id && !String(node.id).startsWith('ent-') ? openItem(node.id) : null"
            @keydown.enter.prevent="node.type !== 'center' && node.id && !String(node.id).startsWith('ent-') ? openItem(node.id) : null"
          >
            <FileText v-if="node.type === 'center'" class="size-3.5 shrink-0" aria-hidden="true" />
            <CornerUpLeft v-else-if="node.type === 'backlink'" class="size-3.5 shrink-0" aria-hidden="true" />
            <Package v-else-if="node.type === 'entity'" class="size-3.5 shrink-0" aria-hidden="true" />
            <Sparkles v-else class="size-3.5 shrink-0" aria-hidden="true" />

            <span class="max-w-[12rem] truncate">{{ node.label }}</span>

            <a
              v-if="node.url && String(node.id).startsWith('ent-')"
              :href="node.url"
              target="_blank"
              rel="noopener noreferrer"
              class="ml-1 text-subtle-foreground hover:text-foreground inline-flex items-center"
              @click.stop
            >
              <ExternalLink class="size-2.5" />
            </a>
          </div>
        </div>

        <div class="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-3xs text-muted-foreground pt-2 border-t border-border/40">
          <span class="flex items-center gap-1"><FileText class="size-3" aria-hidden="true" />這一則</span>
          <span class="flex items-center gap-1"><CornerUpLeft class="size-3" aria-hidden="true" />引用這一則的收藏</span>
          <span class="flex items-center gap-1"><Package class="size-3" aria-hidden="true" />文中提到的項目</span>
          <span class="flex items-center gap-1"><Sparkles class="size-3" aria-hidden="true" />內容相近的收藏</span>
        </div>
      </div>
    </section>

    <!-- previous / next in the list the reader came from -->
    <nav v-if="neighbours.prev || neighbours.next" class="reader-next" aria-label="上一篇與下一篇">
      <button v-if="neighbours.prev" type="button" class="reader-next__item" @click="ui.activeItem = neighbours.prev">
        <span class="reader-next__dir"><ChevronLeft class="size-3.5" />上一篇<kbd>K</kbd></span>
        <span class="reader-next__title">{{ shortTitle(neighbours.prev) }}</span>
      </button>
      <span v-else />
      <button v-if="neighbours.next" type="button" class="reader-next__item is-next" @click="ui.activeItem = neighbours.next">
        <span class="reader-next__dir">下一篇<kbd>J</kbd><ChevronRight class="size-3.5" /></span>
        <span class="reader-next__title">{{ shortTitle(neighbours.next) }}</span>
      </button>
    </nav>
  </div>
  <!-- the item's details beside the article; kept in the page (v-show) so the sections can move in and out -->
  <aside v-show="railOn" class="reader-side reader-side--right" aria-label="這則收藏的資訊">
    <section class="reader-info">
      <h2>資訊</h2>
      <dl>
        <div><dt>來源</dt><dd>
          <a v-if="origin" :href="origin.href" target="_blank" rel="noopener noreferrer" class="reader-source" :title="origin.href">
            <OriginIcon :origin="origin" class="reader-source__icon" />{{ cleanHost(ui.activeItem.url) }}<ArrowUpRight class="size-3.5" aria-hidden="true" /><span class="sr-only">（新分頁）</span>
          </a>
          <template v-else>{{ cleanHost(ui.activeItem.url) }}</template>
        </dd></div>
        <div><dt>{{ ui.activeItem.published_date ? '發布' : '收錄' }}</dt><dd>{{ ui.activeItem.published_date || formatRelativeTime(ui.activeItem.created_at) }}</dd></div>
        <div v-if="ui.activeItem.author"><dt>作者</dt><dd>{{ ui.activeItem.author }}</dd></div>
        <div v-if="ui.activeItem.content_raw"><dt>閱讀時間</dt><dd>{{ estimateReadTime(ui.activeItem.content_raw) }} 分鐘</dd></div>
        <div v-if="hasSnapshot"><dt>離線快照</dt><dd><button type="button" class="reader-info__link" title="開啟收錄時保存的離線網頁" @click="openSnapshot(ui.activeItem)">開啟<ChevronRight class="size-3.5" /></button></dd></div>
      </dl>
      <div v-if="ui.activeItem.tech_tags?.length" class="reader-info__tags">
        <span v-for="tag in ui.activeItem.tech_tags" :key="tag">#{{ tag }}</span>
      </div>
    </section>
    <div id="reader-rail-slot" />
  </aside>
  </div>
</template>
