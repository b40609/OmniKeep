<script setup lang="ts">
import ItemActions from './ItemActions.vue'
import type { Item } from '@/lib/api'
import { cleanHost, formatRelativeTime, sourceMeta } from '@/lib/format'
import { useUiStore } from '@/stores/ui'

defineProps<{ item: Item }>()
const ui = useUiStore()
function select(item: Item) {
  ui.activeItem = item
  ui.detailTab = 'analysis'
}
</script>

<template>
  <article class="flex min-w-0 flex-col justify-between rounded-xl border p-4 transition-all duration-200 micro-glow cursor-pointer"
    :class="ui.activeItem?.id === item.id ? 'border-primary bg-primary/5 shadow-md' : 'border-white/[0.08] bg-card/80 hover:border-zinc-500/40 hover:bg-card'"
    @click="select(item)">
    <div>
      <h3 class="text-base font-semibold leading-snug text-foreground">
        <button class="block w-full break-words text-left" :aria-pressed="ui.activeItem?.id === item.id" @click.stop="select(item)">
          {{ item.title_l1 }}
        </button>
      </h3>
      <p class="mt-2 line-clamp-3 text-sm leading-relaxed text-muted-foreground">{{ item.summary_l1 }}</p>
      <div v-if="item.tech_tags?.length" class="mt-3 flex flex-wrap gap-x-2 text-xs text-muted-foreground">
        <span v-for="tag in item.tech_tags.slice(0, 2)" :key="tag">#{{ tag }}</span>
        <span v-if="item.tech_tags.length > 2" :title="item.tech_tags.slice(2).join('、')">+{{ item.tech_tags.length - 2 }}</span>
      </div>
    </div>
    <div class="mt-4">
      <div class="flex flex-wrap gap-x-2 gap-y-1 text-xs text-subtle-foreground">
        <span>{{ sourceMeta(item.source_type).label }}</span>
        <span>{{ item.category_name === 'Inbox' ? '收件匣' : item.category_name }}</span>
        <span v-if="item.origin === 'radar'">自動收錄</span>
        <span v-if="item.is_read">已封存</span>
        <time class="tabular-nums">{{ formatRelativeTime(item.created_at) }}</time>
      </div>
      <div class="mt-2 flex flex-wrap items-center justify-between border-t border-hairline pt-1">
        <span class="min-w-0 max-w-36 truncate text-xs text-subtle-foreground" :title="cleanHost(item.url)">{{ cleanHost(item.url) }}</span>
        <ItemActions :item="item" />
      </div>
    </div>
  </article>
</template>
