<script setup lang="ts">
import { ref, computed, watch, nextTick, onBeforeUnmount } from 'vue'
import { toast } from 'vue-sonner'
import { Link2, Package, ChevronRight, Camera, Sparkles, Network, ExternalLink, ArrowRight, List, Hash, FileText, CornerUpLeft, Loader2 } from 'lucide-vue-next'
import Badge from '@/components/ui/badge/Badge.vue'
import ItemCover from '@/components/items/ItemCover.vue'
import { analyzeItem, getServiceStatus, type Item } from '@/lib/api'
import { isNotAnalysed, plainSummary } from '@/lib/wall'
import { useItemsStore } from '@/stores/items'
import { cleanHost, formatRelativeTime, estimateReadTime, sourceMeta } from '@/lib/format'
import { renderMarkdown, useCodeCopy, extractToc } from '@/lib/markdown'
import { renderMermaidIn } from '@/lib/mermaid'
import { renderFlowsIn, disposeFlowsIn } from '@/lib/flowchart'
import { useUiStore } from '@/stores/ui'
import { useMutations } from '@/composables/useMutations'

const ui = useUiStore()
const itemsStore = useItemsStore()
const { openSnapshot } = useMutations()

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
    disposeFlowsIn(contentRef.value)
    if (!ui.activeItem?.deep_analysis) return
    await nextTick()
    detachCodeCopy = useCodeCopy(contentRef.value)
    void renderMermaidIn(contentRef.value)
    renderFlowsIn(contentRef.value)
  },
  { immediate: true },
)
onBeforeUnmount(() => { detachCodeCopy?.(); disposeFlowsIn(contentRef.value) })

const tocItems = computed(() => extractToc(ui.activeItem?.deep_analysis))
function scrollToHeading(id: string) { document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' }) }

function openItem(id: number | string) {
  ui.activeItem = { id: Number(id) } as Item // skeleton placeholder, replaced by full fetch in ReaderPane
}
</script>

<template>
  <!-- 44rem less the padding is 40rem: about 40 Chinese characters a line, however wide the pane gets -->
  <div v-if="ui.activeItem" class="mx-auto max-w-[44rem] space-y-6 p-5 lg:p-8">
    <!-- Cover: same rules as the wall, and simply absent when there is none -->
    <ItemCover :item="ui.activeItem" variant="hero" />

    <!-- Article header -->
    <header class="pb-1">
      <h1 class="text-xl leading-snug font-bold tracking-tight text-foreground lg:text-2xl">
        {{ ui.activeItem.title_l1 }}
      </h1>
      <div class="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-subtle-foreground">
        <span>{{ cleanHost(ui.activeItem.url) }}</span>
        <span aria-hidden="true">·</span>
        <span>{{ ui.activeItem.published_date || formatRelativeTime(ui.activeItem.created_at) }}</span>
        <template v-if="ui.activeItem.author">
          <span aria-hidden="true">·</span>
          <span>{{ ui.activeItem.author }}</span>
        </template>
        <span
          v-if="ui.activeItem.content_raw"
          class="rounded border border-border bg-muted px-1.5 py-px"
          :title="`約 ${estimateReadTime(ui.activeItem.content_raw)} 分鐘`"
        >
          約 {{ estimateReadTime(ui.activeItem.content_raw) }} 分鐘
        </span>
        <button
          type="button"
          class="inline-flex min-h-11 cursor-pointer items-center gap-1 rounded-lg border border-border px-3 text-xs text-muted-foreground transition-colors hover:bg-accent"
          title="開啟收錄時保存的離線網頁"
          @click="openSnapshot(ui.activeItem)"
        >
          <Camera class="size-2.5" />
          <span>離線快照</span>
        </button>
      </div>
    </header>

    <!-- Cited-in backlinks -->
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
      <div v-if="ui.activeItem.tech_tags?.length" class="mt-3 flex flex-wrap gap-2 text-xs text-muted-foreground">
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
                {{ sub.category_name }}
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
        v-if="tocItems.length >= 2"
        class="mb-6 rounded-xl border border-white/[0.08] bg-muted/30 p-3.5 backdrop-blur-md"
        aria-label="目錄"
      >
        <div class="mb-2.5 flex items-center justify-between text-xs font-semibold text-muted-foreground">
          <span class="flex items-center gap-1.5">
            <List class="size-3.5 text-primary" />
            <span>目錄</span>
          </span>
          <span class="font-mono text-2xs text-subtle-foreground">{{ tocItems.length }} 個章節</span>
        </div>
        <div class="flex flex-wrap gap-1.5 sm:grid sm:grid-cols-2 md:grid-cols-3">
          <a
            v-for="h in tocItems"
            :key="h.id"
            :href="'#' + h.id"
            class="group flex items-center gap-1.5 truncate rounded-lg border border-border/40 bg-card/70 px-2.5 py-1 text-2xs text-foreground/80 transition-all hover:border-primary/50 hover:bg-primary/5 hover:text-primary"
            @click.prevent="scrollToHeading(h.id)"
          >
            <Hash class="size-2.5 shrink-0 text-muted-foreground/60 group-hover:text-primary" />
            <span class="truncate">{{ h.text }}</span>
          </a>
        </div>
      </nav>
      <div v-if="ui.activeItem.deep_analysis" ref="contentRef" class="prose-reader text-base" v-html="renderMarkdown(ui.activeItem.deep_analysis)" />
      <div v-else class="py-8 text-center text-sm text-muted-foreground">
        這則收藏還沒有重點分析，可以改看「原文」。
      </div>
    </section>

    <!-- Semantic Neighbors / Related Items (E4) -->
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
          class="group flex flex-col justify-between rounded-xl border border-border/60 bg-muted/20 p-3.5 transition hover:border-primary/40 hover:bg-card cursor-pointer"
          @click="openItem(rel.id)"
        >
          <div>
            <div class="mb-1.5 flex items-center justify-between gap-1.5">
              <Badge variant="outline" class="text-3xs font-mono">
                {{ rel.category_name || 'Inbox' }}
              </Badge>
              <span
                v-if="rel.similarity"
                class="rounded-full bg-primary/10 px-2 py-0.5 text-3xs font-mono font-bold text-primary"
              >
                {{ Math.round(rel.similarity * 100) }}% 相似
              </span>
            </div>
            <h3 class="line-clamp-2 text-xs font-bold leading-snug text-foreground group-hover:text-primary">
              {{ rel.title_l1 }}
            </h3>
            <p v-if="rel.summary_l1" class="mt-1 line-clamp-2 text-2xs leading-relaxed text-muted-foreground">
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
            @click="node.type !== 'center' && node.id && !String(node.id).startsWith('ent-') ? openItem(node.id) : null"
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

        <div class="mt-3 flex items-center gap-4 text-3xs text-muted-foreground pt-2 border-t border-border/40">
          <span class="flex items-center gap-1"><FileText class="size-3" aria-hidden="true" />這一則</span>
          <span class="flex items-center gap-1"><CornerUpLeft class="size-3" aria-hidden="true" />引用這一則的收藏</span>
          <span class="flex items-center gap-1"><Package class="size-3" aria-hidden="true" />文中提到的項目</span>
          <span class="flex items-center gap-1"><Sparkles class="size-3" aria-hidden="true" />內容相近的收藏</span>
        </div>
      </div>
    </section>
  </div>
</template>
