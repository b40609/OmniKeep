<script setup lang="ts">
import { Star, Archive, Package, Link2, Camera, ExternalLink } from 'lucide-vue-next'
import Badge from '@/components/ui/badge/Badge.vue'
import type { Item } from '@/lib/api'
import { cleanHost, formatRelativeTime, sourceMeta } from '@/lib/format'
import { useUiStore } from '@/stores/ui'
import { useMutations } from '@/composables/useMutations'

defineProps<{ item: Item }>()
const ui = useUiStore()
const { toggleStar, toggleRead, openSnapshot } = useMutations()

function select(item: Item) {
  ui.activeItem = item
  ui.detailTab = 'analysis'
}
</script>

<template>
  <article
    class="group relative flex cursor-pointer flex-col justify-between rounded-xl border border-border/70 bg-card/80 p-5 shadow-xs transition-all duration-200 hover:-translate-y-0.5 hover:border-primary/40 hover:bg-card/95 hover:shadow-card active:scale-[0.99]"
    :class="[ui.activeItem?.id === item.id ? 'ring-2 ring-primary border-transparent' : '', item.is_read ? 'opacity-60' : '']"
    tabindex="0"
    role="button"
    :aria-label="item.title_l1"
    @click="select(item)"
    @keydown.enter="select(item)"
  >
    <div class="min-w-0">
      <!-- Top meta row: Badges & Star button -->
      <div class="mb-2.5 flex items-center justify-between gap-2">
        <div class="flex flex-wrap items-center gap-1.5 min-w-0">
          <Badge :class="sourceMeta(item.source_type).badgeClass">{{ sourceMeta(item.source_type).label }}</Badge>
          <span
            v-if="item.origin === 'radar'"
            title="自動訂閱排程收錄"
            class="inline-flex items-center rounded-md bg-violet-500/10 px-1.5 py-0.5 text-2xs font-semibold text-violet-600 dark:text-violet-400"
          >📡 自動訂閱</span>
          <span class="rounded-md border border-border/40 bg-muted/60 px-1.5 py-0.5 text-2xs font-medium text-muted-foreground">{{ item.category_name }}</span>
          <span v-if="item.sub_entities_count" class="inline-flex items-center gap-0.5 rounded-md bg-info-soft px-1.5 py-0.5 text-2xs font-semibold text-info">
            <Package class="size-2.5" /> {{ item.sub_entities_count }}
          </span>
          <span v-if="item.citations_count" class="inline-flex items-center gap-0.5 rounded-md bg-purple-soft px-1.5 py-0.5 text-2xs font-semibold text-purple">
            <Link2 class="size-2.5" /> {{ item.citations_count }}
          </span>
        </div>
        <button
          class="shrink-0 rounded-full p-1.5 transition-all active:scale-90 cursor-pointer text-muted-foreground hover:text-warning"
          :class="item.is_starred ? 'text-warning' : ''"
          :title="item.is_starred ? '取消星標' : '加入星標收藏'"
          aria-label="星標"
          @click.stop="toggleStar(item)"
        >
          <Star class="size-4" :class="item.is_starred ? 'fill-warning' : ''" />
        </button>
      </div>

      <!-- Title & Summary: Editorial Typography -->
      <h3 class="mb-1.5 line-clamp-2 text-[15px] leading-snug font-semibold tracking-tight text-foreground group-hover:text-primary transition-colors">
        {{ item.title_l1 }}
      </h3>
      <p class="line-clamp-2 text-xs leading-relaxed text-muted-foreground">{{ item.summary_l1 }}</p>

      <!-- Tags: Subtle, lightweight, strictly smaller than content summary -->
      <div v-if="item.tech_tags?.length" class="mt-3 flex flex-wrap items-center gap-1.5">
        <span
          v-for="tag in (item.tech_tags ?? []).slice(0, 3)"
          :key="tag"
          class="inline-flex items-center rounded-md border border-border/40 bg-muted/30 px-2 py-0.5 text-3xs font-normal text-muted-foreground/80"
        >
          #{{ tag }}
        </span>
        <span
          v-if="(item.tech_tags?.length ?? 0) > 3"
          :title="(item.tech_tags ?? []).slice(3).join(', ')"
          class="inline-flex items-center rounded-md border border-border/30 bg-muted/20 px-1.5 py-0.5 font-mono text-3xs text-muted-foreground/60"
        >
          +{{ item.tech_tags!.length - 3 }}
        </span>
      </div>
    </div>

    <!-- Scheme A: Clean Editorial Footer with Hover Action Toolbar -->
    <div class="mt-3.5 flex items-center justify-between border-t border-border/40 pt-2.5 text-2xs text-muted-foreground">
      <span class="max-w-[130px] truncate font-mono text-3xs text-muted-foreground/60">{{ cleanHost(item.url) }}</span>
      <div class="relative flex items-center justify-end min-h-[26px]">
        <!-- Resting info: Timestamp (fades out on card hover) -->
        <span class="tabular-nums text-3xs text-muted-foreground/60 transition-opacity duration-150 group-hover:opacity-0 pointer-events-none">
          {{ formatRelativeTime(item.created_at) }}
        </span>

        <!-- Hover Action Toolbar (fades in on card hover) -->
        <div class="absolute right-0 flex items-center gap-1 opacity-0 pointer-events-none transition-all duration-150 group-hover:opacity-100 group-hover:pointer-events-auto">
          <button
            class="flex items-center gap-1 rounded-md border border-border/60 bg-background/95 px-2 py-1 text-2xs font-medium text-muted-foreground shadow-2xs hover:bg-accent hover:text-foreground active:scale-95 transition cursor-pointer"
            title="開啟離線快照存檔 (Snapshot)"
            aria-label="離線快照"
            @click.stop="openSnapshot(item)"
          >
            <Camera class="size-3" />
            <span>快照</span>
          </button>
          <button
            class="flex items-center gap-1 rounded-md border border-border/60 bg-background/95 px-2 py-1 text-2xs font-medium text-muted-foreground shadow-2xs hover:bg-accent hover:text-foreground active:scale-95 transition cursor-pointer"
            :title="item.is_read ? '標記為未讀' : '封存歸檔 (Archive)'"
            aria-label="封存歸檔"
            @click.stop="toggleRead(item)"
          >
            <Archive class="size-3" />
            <span>{{ item.is_read ? '復原' : '封存' }}</span>
          </button>
          <a
            :href="item.url"
            target="_blank"
            rel="noopener noreferrer"
            class="flex items-center rounded-md border border-border/60 bg-background/95 p-1 text-muted-foreground shadow-2xs hover:bg-accent hover:text-foreground active:scale-95 transition cursor-pointer"
            title="開啟原始連結"
            aria-label="開啟原始連結"
            @click.stop
          >
            <ExternalLink class="size-3" />
          </a>
        </div>
      </div>
    </div>
  </article>
</template>
