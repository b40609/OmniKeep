<script setup lang="ts">
import { Star, Archive, ExternalLink, ChevronUp, ChevronDown, Package, Link2, ChevronRight } from 'lucide-vue-next'
import Badge from '@/components/ui/badge/Badge.vue'
import type { Item } from '@/lib/api'
import { cleanHost, formatRelativeTime, sourceMeta } from '@/lib/format'
import { useUiStore } from '@/stores/ui'
import { useMutations } from '@/composables/useMutations'
import { useSignal } from '@/composables/useSignal'

const props = defineProps<{ item: Item; active: boolean }>()
const ui = useUiStore()
const { toggleStar, toggleRead } = useMutations()
const { tuneItem } = useSignal()

function select() {
  ui.activeItem = props.item
  ui.detailTab = 'analysis'
}
</script>

<template>
  <div
    class="glass-tint group relative mx-2 my-1 flex cursor-pointer items-start gap-3 rounded-2xl px-3 py-3 transition-all duration-200"
    :class="[
      active ? 'bg-primary-soft ring-1 ring-primary/40' : 'hover:bg-white/70 hover:shadow-card dark:hover:bg-white/[0.09]',
      item.is_read ? 'opacity-55' : '',
    ]"
    role="button"
    tabindex="0"
    :aria-label="item.title_l1"
    @click="select"
    @keydown.enter="select"
  >
    <!-- Unread dot -->
    <span
      class="mt-1.5 size-2 shrink-0 rounded-full transition-all duration-200"
      :class="item.is_read ? 'bg-transparent ring-1 ring-hairline' : 'bg-primary shadow-[0_0_6px] shadow-primary/50'"
      aria-hidden="true"
    />

    <div class="min-w-0 flex-1">
      <!-- Meta line -->
      <div class="mb-1 flex items-center gap-1.5">
        <Badge :class="sourceMeta(item.source_type).badgeClass">
          {{ sourceMeta(item.source_type).label }}
        </Badge>
        <span
          v-if="item.origin === 'radar'"
          title="雷達自動抓取（可與手動加入的內容分流）"
          class="inline-flex items-center rounded-md bg-violet-500/10 px-1.5 py-px text-2xs font-semibold text-violet-600 dark:text-violet-400"
        >
          📡 雷達
        </span>
        <span class="rounded-md bg-muted px-1.5 py-px text-2xs font-medium text-muted-foreground">
          {{ item.category_name }}
        </span>
        <span
          v-if="item.sub_entities_count"
          class="inline-flex items-center gap-0.5 rounded-md bg-info-soft px-1.5 py-px text-2xs font-semibold text-info"
        >
          <Package class="size-2.5" /> {{ item.sub_entities_count }}
        </span>
        <span
          v-if="item.citations_count"
          class="inline-flex items-center gap-0.5 rounded-md bg-purple-soft px-1.5 py-px text-2xs font-semibold text-purple"
        >
          <Link2 class="size-2.5" /> {{ item.citations_count }}
        </span>
        <span class="ml-auto shrink-0 text-2xs text-subtle-foreground tabular-nums">{{ formatRelativeTime(item.created_at) }}</span>
      </div>

      <!-- Title + summary -->
      <div class="flex items-start justify-between gap-2">
        <div class="min-w-0 flex-1">
          <h3 class="truncate text-[15px] leading-snug font-semibold tracking-tight text-foreground">
            {{ item.title_l1 }}
          </h3>
          <p class="mt-0.5 line-clamp-2 text-xs leading-relaxed text-muted-foreground">{{ item.summary_l1 }}</p>

          <div class="mt-1.5 flex flex-wrap items-center gap-1.5">
            <button
              v-for="tag in (item.tech_tags ?? []).slice(0, 3)"
              :key="tag"
              class="rounded-md bg-muted px-1.5 py-0.5 text-2xs font-medium text-muted-foreground transition-all duration-150 hover:bg-primary-soft hover:text-primary"
              :title="`提升 #${tag} 權重`"
              @click.stop="tuneItem({ item, action: 'boost' })"
            >
              {{ tag }}
            </button>
            <span class="text-2xs text-subtle-foreground max-sm:hidden">{{ cleanHost(item.url) }}</span>
          </div>
        </div>
        <ChevronRight class="mt-2 size-4 shrink-0 text-hairline transition-transform duration-200 group-hover:translate-x-0.5 group-hover:text-subtle-foreground" />
      </div>
    </div>

    <!-- Hover quick actions (floating pill) -->
    <div class="absolute -top-1 right-2 z-10 hidden items-center gap-0.5 rounded-full border border-hairline bg-popover/95 p-1 opacity-0 shadow-float backdrop-blur-xl transition-all duration-150 group-hover:opacity-100">
      <button class="rounded-full p-1.5 text-muted-foreground transition-colors hover:bg-primary-soft hover:text-primary" title="增強訊號" aria-label="增強訊號" @click.stop="tuneItem({ item, action: 'boost' })">
        <ChevronUp class="size-3.5" />
      </button>
      <button class="rounded-full p-1.5 text-muted-foreground transition-colors hover:bg-danger-soft hover:text-danger" title="降低頻率" aria-label="降低頻率" @click.stop="tuneItem({ item, action: 'dampen' })">
        <ChevronDown class="size-3.5" />
      </button>
      <button class="rounded-full p-1.5 transition-colors hover:bg-warning-soft" :class="item.is_starred ? 'text-warning' : 'text-muted-foreground hover:text-warning'" title="星標" aria-label="星標" @click.stop="toggleStar(item)">
        <Star class="size-3.5" :class="item.is_starred ? 'fill-warning' : ''" />
      </button>
      <button class="rounded-full p-1.5 text-muted-foreground transition-colors hover:bg-success-soft hover:text-success" title="封存" aria-label="封存" @click.stop="toggleRead(item)">
        <Archive class="size-3.5" />
      </button>
      <a :href="item.url" target="_blank" rel="noopener" class="rounded-full p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground" title="原始網頁" aria-label="開啟原始網頁" @click.stop>
        <ExternalLink class="size-3.5" />
      </a>
    </div>
  </div>
</template>
