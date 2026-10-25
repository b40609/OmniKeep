<script setup lang="ts">
import { Star, Archive, Package, Link2 } from 'lucide-vue-next'
import Badge from '@/components/ui/badge/Badge.vue'
import type { Item } from '@/lib/api'
import { cleanHost, formatRelativeTime, sourceMeta } from '@/lib/format'
import { useUiStore } from '@/stores/ui'
import { useMutations } from '@/composables/useMutations'

defineProps<{ item: Item }>()
const ui = useUiStore()
const { toggleStar, toggleRead } = useMutations()

function select(item: Item) {
  ui.activeItem = item
  ui.detailTab = 'analysis'
}
</script>

<template>
  <article
    class="glass group flex cursor-pointer flex-col justify-between gap-3 rounded-2xl p-4 transition-all duration-200 hover:-translate-y-0.5 hover:shadow-float active:scale-[0.99]"
    :class="[ui.activeItem?.id === item.id ? 'ring-2 ring-primary' : '', item.is_read ? 'opacity-60' : '']"
    tabindex="0"
    role="button"
    :aria-label="item.title_l1"
    @click="select(item)"
    @keydown.enter="select(item)"
  >
    <div class="min-w-0">
      <div class="mb-2 flex items-center justify-between gap-2">
        <div class="flex flex-wrap items-center gap-1.5">
          <Badge :class="sourceMeta(item.source_type).badgeClass">{{ sourceMeta(item.source_type).label }}</Badge>
          <span
            v-if="item.origin === 'radar'"
            title="雷達自動抓取"
            class="inline-flex items-center rounded-md bg-violet-500/10 px-1.5 py-0.5 text-2xs font-semibold text-violet-600 dark:text-violet-400"
          >📡 雷達</span>
          <span class="rounded-md bg-muted px-1.5 py-0.5 text-2xs font-medium text-muted-foreground">{{ item.category_name }}</span>
          <span v-if="item.sub_entities_count" class="inline-flex items-center gap-0.5 rounded-md bg-info-soft px-1.5 py-0.5 text-2xs font-semibold text-info">
            <Package class="size-2.5" /> {{ item.sub_entities_count }}
          </span>
          <span v-if="item.citations_count" class="inline-flex items-center gap-0.5 rounded-md bg-purple-soft px-1.5 py-0.5 text-2xs font-semibold text-purple">
            <Link2 class="size-2.5" /> {{ item.citations_count }}
          </span>
        </div>
        <button
          class="rounded-full p-1.5 transition-all active:scale-90"
          :class="item.is_starred ? 'text-warning' : 'text-subtle-foreground hover:text-warning'"
          :title="item.is_starred ? '取消星標' : '加星標'"
          aria-label="星標"
          @click.stop="toggleStar(item)"
        >
          <Star class="size-4" :class="item.is_starred ? 'fill-warning' : ''" />
        </button>
      </div>

      <h3 class="mb-1 line-clamp-2 text-sm leading-snug font-semibold tracking-tight text-foreground">
        {{ item.title_l1 }}
      </h3>
      <p class="line-clamp-2 text-xs leading-relaxed text-muted-foreground">{{ item.summary_l1 }}</p>

      <div class="mt-2.5 flex flex-wrap gap-1.5">
        <span
          v-for="tag in (item.tech_tags ?? []).slice(0, 4)"
          :key="tag"
          class="rounded-md bg-muted px-1.5 py-0.5 text-2xs font-medium text-muted-foreground"
        >
          {{ tag }}
        </span>
      </div>
    </div>

    <div class="flex items-center justify-between border-t border-hairline pt-2.5 text-2xs text-subtle-foreground">
      <span class="max-w-[160px] truncate">{{ cleanHost(item.url) }}</span>
      <div class="flex items-center gap-2">
        <span class="tabular-nums">{{ formatRelativeTime(item.created_at) }}</span>
        <button
          class="flex items-center gap-1 rounded-full bg-muted px-2 py-1 font-medium text-muted-foreground transition-colors hover:bg-success-soft hover:text-success"
          @click.stop="toggleRead(item)"
        >
          <Archive class="size-3" />
          {{ item.is_read ? '已封存' : '封存' }}
        </button>
      </div>
    </div>
  </article>
</template>
