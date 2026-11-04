<script setup lang="ts">
import { ref, computed, watch, onBeforeUnmount } from 'vue'
import { Link2, Package, ChevronRight, Camera, Sparkles, Network, ExternalLink, ArrowRight, List, Hash } from 'lucide-vue-next'
import Badge from '@/components/ui/badge/Badge.vue'
import type { Item } from '@/lib/api'
import { cleanHost, formatRelativeTime, estimateReadTime, sourceMeta } from '@/lib/format'
import { renderMarkdown, useCodeCopy, extractToc } from '@/lib/markdown'
import { useUiStore } from '@/stores/ui'
import { useMutations } from '@/composables/useMutations'

const ui = useUiStore()
const { openSnapshot } = useMutations()
const contentRef = ref<HTMLElement | null>(null)
let detachCodeCopy: (() => void) | null = null

// Re-attach code-copy handlers whenever the markdown re-renders.
watch(
  () => [ui.activeItem?.id, ui.activeItem?.deep_analysis] as const,
  async () => {
    detachCodeCopy?.()
    detachCodeCopy = null
    if (!ui.activeItem?.deep_analysis) return
    await Promise.resolve()
    detachCodeCopy = useCodeCopy(contentRef.value)
  },
  { immediate: true },
)
onBeforeUnmount(() => detachCodeCopy?.())

const tocItems = computed(() => extractToc(ui.activeItem?.deep_analysis))
function scrollToHeading(id: string) { document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' }) }

function openItem(id: number | string) {
  ui.activeItem = { id: Number(id) } as Item // skeleton placeholder, replaced by full fetch in ReaderPane
}
</script>

<template>
  <div v-if="ui.activeItem" class="mx-auto max-w-3xl space-y-6 p-5 lg:p-8">
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
    <section class="border-t border-hairline pt-6" aria-label="內容摘要">
      <h2 class="mb-2 text-base font-semibold text-foreground">內容摘要</h2>
      <p class="text-base leading-relaxed text-foreground">{{ ui.activeItem.summary_l1 }}</p>
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
                閱讀詳情 <ChevronRight class="size-3" />
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

    <!-- Semantic Neighbors / Related Items (E4) -->
    <section
      v-if="ui.activeItem.related_items?.length"
      class="border-t border-hairline pt-6"
      aria-label="語意關聯推薦"
    >
      <div class="mb-3 flex items-center justify-between">
        <div class="flex items-center gap-2">
          <Sparkles class="size-4 text-amber-500" />
          <h2 class="text-base font-semibold text-foreground">
            語意關聯推薦（{{ ui.activeItem.related_items.length }}）
          </h2>
        </div>
        <span class="text-2xs font-mono text-muted-foreground">GPU 向量餘弦關聯</span>
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
            <span>前往閱讀</span>
            <ArrowRight class="ml-1 size-3 transition-transform group-hover:translate-x-0.5" />
          </div>
        </div>
      </div>
    </section>

    <!-- Entity Knowledge Graph (E4) -->
    <section
      v-if="ui.activeItem.graph && ui.activeItem.graph.nodes.length > 1"
      class="border-t border-hairline pt-6"
      aria-label="實體知識網絡"
    >
      <div class="mb-3 flex items-center justify-between">
        <div class="flex items-center gap-2">
          <Network class="size-4 text-primary" />
          <h2 class="text-base font-semibold text-foreground">
            實體知識網絡（{{ ui.activeItem.graph.nodes.length }} 節點，{{ ui.activeItem.graph.edges.length }} 關聯）
          </h2>
        </div>
        <span class="text-2xs text-muted-foreground">雙向圖譜網絡</span>
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
            <span v-if="node.type === 'center'">★</span>
            <span v-else-if="node.type === 'backlink'">🔗</span>
            <span v-else-if="node.type === 'entity'">📦</span>
            <span v-else>⚡</span>

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
          <span class="flex items-center gap-1">★ 本文核心</span>
          <span class="flex items-center gap-1">🔗 反向引用 (Backlink)</span>
          <span class="flex items-center gap-1">📦 提及實體 (Entity)</span>
          <span class="flex items-center gap-1">⚡ 語意相鄰 (Similar)</span>
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
        aria-label="章節目錄導航"
      >
        <div class="mb-2.5 flex items-center justify-between text-xs font-semibold text-muted-foreground">
          <span class="flex items-center gap-1.5">
            <List class="size-3.5 text-primary" />
            <span>章節目錄 (Table of Contents)</span>
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
        這個項目尚無重點分析，可切換「原文」閱讀。
      </div>
    </section>
  </div>
</template>
