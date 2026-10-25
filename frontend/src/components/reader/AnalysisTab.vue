<script setup lang="ts">
import { ref, watch, onBeforeUnmount } from 'vue'
import { Link2, Package, Bot, ChevronRight } from 'lucide-vue-next'
import Badge from '@/components/ui/badge/Badge.vue'
import Skeleton from '@/components/ui/skeleton/Skeleton.vue'
import * as api from '@/lib/api'
import type { Item } from '@/lib/api'
import { cleanHost, formatRelativeTime, estimateReadTime, sourceMeta } from '@/lib/format'
import { renderMarkdown, useCodeCopy } from '@/lib/markdown'
import { useUiStore } from '@/stores/ui'

const ui = useUiStore()
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

function openItem(id: number) {
  ui.activeItem = { id } as Item // skeleton placeholder, replaced by full fetch in ReaderPane
  api.getItem(id).then((full) => {
    if (ui.activeItem?.id === full.id) ui.activeItem = full
  })
}
</script>

<template>
  <div v-if="ui.activeItem" class="mx-auto max-w-3xl space-y-6 p-5 lg:p-8">
    <!-- Article header -->
    <header class="pb-1">
      <h1 class="text-xl leading-snug font-bold tracking-tight text-foreground lg:text-2xl">
        {{ ui.activeItem.title_l1 }}
      </h1>
      <div class="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 font-mono text-2xs text-subtle-foreground">
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
          ~{{ estimateReadTime(ui.activeItem.content_raw) }} min
        </span>
      </div>
    </header>

    <!-- Cited-in backlinks -->
    <section
      v-if="ui.activeItem.citations?.length"
      class="rounded-xl border border-primary/25 bg-primary-soft p-4"
      aria-label="收錄與引用來源"
    >
      <div class="mb-3 flex items-center justify-between">
        <div class="flex items-center gap-2">
          <span class="rounded-md bg-primary/15 p-1 text-primary">
            <Link2 class="size-3.5" />
          </span>
          <span class="font-mono text-2xs font-bold tracking-wider text-primary-soft-foreground uppercase">
            收錄與引用（{{ ui.activeItem.citations.length }}）
          </span>
        </div>
        <span class="font-mono text-2xs text-muted-foreground">母子關聯回溯</span>
      </div>
      <div class="space-y-2">
        <button
          v-for="cit in ui.activeItem.citations"
          :key="cit.citation_id"
          class="group flex w-full items-start justify-between gap-3 rounded-lg border-0 bg-white/45 p-3 text-left shadow-sm transition-all duration-150 hover:bg-white/75 hover:shadow-card active:scale-[0.995] dark:bg-white/[0.06] dark:hover:bg-white/[0.1]"
          @click="openItem(cit.parent_id)"
        >
          <div class="min-w-0 flex-1">
            <div class="mb-1 flex items-center gap-2">
              <Badge :class="sourceMeta(cit.parent_source_type).badgeClass">{{ cit.parent_source_type }}</Badge>
              <span class="truncate text-xs font-semibold text-foreground group-hover:text-primary-soft-foreground">
                {{ cit.parent_title }}
              </span>
            </div>
            <p v-if="cit.mention_context" class="line-clamp-2 text-xs leading-relaxed text-muted-foreground">
              「{{ cit.mention_context }}」
            </p>
          </div>
          <span class="flex shrink-0 items-center gap-0.5 pt-1 font-mono text-2xs text-subtle-foreground transition-colors group-hover:text-primary-soft-foreground">
            檢視母文 <ChevronRight class="size-3.5 transition-transform duration-150 group-hover:translate-x-0.5" />
          </span>
        </button>
      </div>
    </section>

    <!-- L1 highlight -->
    <section class="glass-tint relative overflow-hidden rounded-xl p-4" aria-label="L1 速覽">
      <div class="absolute inset-y-0 left-0 w-1 bg-primary" aria-hidden="true" />
      <div class="mb-2 flex items-center justify-between">
        <span class="font-mono text-2xs font-bold tracking-wider text-primary-soft-foreground uppercase">L1 速覽 · 白話痛點與核心論點</span>
        <span class="flex items-center gap-1 font-mono text-2xs text-subtle-foreground">
          <Bot class="size-3" /> AI AUTO TRIAGE
        </span>
      </div>
      <p class="text-sm leading-relaxed text-foreground/90">{{ ui.activeItem.summary_l1 }}</p>
      <div v-if="ui.activeItem.tech_tags?.length" class="mt-3 flex flex-wrap gap-1.5 border-t border-border pt-3">
        <span
          v-for="tag in ui.activeItem.tech_tags"
          :key="tag"
          class="rounded-md bg-white/55 px-2 py-0.5 font-medium text-primary shadow-sm dark:bg-white/[0.08]"
        >
          #{{ tag }}
        </span>
      </div>
    </section>

    <!-- Sub-entities bundle -->
    <section
      v-if="ui.activeItem.sub_entities?.length"
      class="rounded-xl border border-info/25 bg-info/[0.06] p-4"
      aria-label="獨立專案拆解"
    >
      <div class="mb-3 flex items-center justify-between">
        <div class="flex items-center gap-2">
          <span class="rounded-md bg-info/15 p-1 text-info">
            <Package class="size-3.5" />
          </span>
          <span class="font-mono text-2xs font-bold tracking-wider text-info uppercase">
            內含獨立專案拆解（{{ ui.activeItem.sub_entities.length }} 立項）
          </span>
        </div>
        <span class="font-mono text-2xs text-muted-foreground">實體級去重 · 派生入庫</span>
      </div>
      <div class="grid grid-cols-1 gap-2.5">
        <div
          v-for="(sub, idx) in ui.activeItem.sub_entities"
          :key="sub.citation_id"
          class="rounded-lg border-0 bg-white/45 p-3 shadow-sm transition-all duration-150 hover:bg-white/75 dark:bg-white/[0.06] dark:hover:bg-white/[0.1]"
        >
          <div class="mb-1.5 flex items-start justify-between gap-2">
            <div class="flex min-w-0 items-center gap-2">
              <span class="font-mono text-2xs font-bold text-subtle-foreground">#{{ idx + 1 }}</span>
              <span class="truncate text-xs font-bold text-foreground">
                {{ sub.target_name || sub.title_l1 || '未命名專案' }}
              </span>
              <span v-if="sub.category_name" class="rounded bg-muted px-1.5 py-px font-mono text-2xs text-muted-foreground">
                {{ sub.category_name }}
              </span>
            </div>
            <div class="flex shrink-0 items-center gap-1.5">
              <button
                v-if="sub.target_item_id"
                class="flex items-center gap-1 rounded-md border border-info/30 bg-info/10 px-2 py-1 font-mono text-2xs text-info transition-colors hover:bg-info/20"
                title="在 OmniKeep 展開完整情報"
                @click="openItem(sub.target_item_id)"
              >
                專案情報 <ChevronRight class="size-3" />
              </button>
              <a
                v-if="sub.target_canonical_url"
                :href="sub.target_canonical_url"
                target="_blank"
                rel="noopener"
                class="rounded-md border border-border bg-muted px-2 py-1 font-mono text-2xs text-muted-foreground transition-colors hover:text-foreground"
                title="開啟 GitHub 或官方網站"
              >
                外連
              </a>
            </div>
          </div>
          <p v-if="sub.mention_context" class="mb-1.5 text-xs leading-relaxed text-foreground/80">{{ sub.mention_context }}</p>
          <div v-if="sub.tech_tags?.length" class="flex flex-wrap gap-1">
            <span v-for="st in sub.tech_tags.slice(0, 3)" :key="st" class="rounded border border-border bg-muted/60 px-1.5 py-px font-mono text-2xs text-muted-foreground">
              #{{ st }}
            </span>
          </div>
        </div>
      </div>
    </section>

    <!-- L2 deep analysis -->
    <section aria-label="L2 深度解構">
      <h3 class="mb-3 font-mono text-2xs font-bold tracking-wider text-subtle-foreground uppercase">L2 深度技術架構解構</h3>
      <div v-if="ui.activeItem.deep_analysis" ref="contentRef" class="prose-reader text-sm" v-html="renderMarkdown(ui.activeItem.deep_analysis)" />
      <div v-else-if="ui.activeItem.content_raw === undefined" class="space-y-2">
        <Skeleton class="h-4 w-full" />
        <Skeleton class="h-4 w-11/12" />
        <Skeleton class="h-4 w-4/5" />
      </div>
      <div v-else class="rounded-xl border-0 bg-white/45 py-10 text-center text-xs text-muted-foreground shadow-sm dark:bg-white/[0.06]">
        此項目無深入解構內容
      </div>
    </section>
  </div>
</template>
