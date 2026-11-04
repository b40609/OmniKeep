<script setup lang="ts">
import ItemActions from './ItemActions.vue'
import type { Item } from '@/lib/api'
import { cleanHost, formatRelativeTime, sourceMeta } from '@/lib/format'
import { useUiStore } from '@/stores/ui'

const props = defineProps<{ item: Item; active: boolean }>()
const ui = useUiStore()

function select() {
  ui.activeItem = props.item
  ui.detailTab = 'analysis'
}
</script>

<template>
  <article
    class="group relative border-b border-hairline px-4 py-4 transition-colors"
    :class="active ? 'bg-primary-soft' : 'bg-card hover:bg-accent'"
    @click="select"
  >
    <h3 class="text-base font-semibold leading-snug text-foreground">
      <button class="block w-full break-words text-left" :aria-pressed="active" @click.stop="select">
        <span v-if="!item.is_read" class="mr-2 inline-block size-1.5 rounded-full bg-primary align-middle" aria-hidden="true" />
        {{ item.title_l1 }}
      </button>
    </h3>
    <p class="mt-1 line-clamp-2 text-sm leading-relaxed text-muted-foreground">{{ item.summary_l1 }}</p>
    <div v-if="item.tech_tags?.length" class="mt-2 flex flex-wrap gap-x-2 text-xs text-muted-foreground">
      <span v-for="tag in item.tech_tags.slice(0, 2)" :key="tag">#{{ tag }}</span>
      <span v-if="item.tech_tags.length > 2" :title="item.tech_tags.slice(2).join('、')">+{{ item.tech_tags.length - 2 }}</span>
    </div>
    <div class="mt-2 flex flex-wrap items-center justify-between gap-x-2">
      <div class="flex min-w-0 flex-1 flex-wrap items-center gap-x-2 gap-y-1 text-xs text-subtle-foreground">
        <span>{{ sourceMeta(item.source_type).label }}</span>
        <span class="max-w-32 truncate" :title="cleanHost(item.url)">{{ cleanHost(item.url) }}</span>
        <span>{{ item.category_name === 'Inbox' ? '收件匣' : item.category_name }}</span>
        <span v-if="item.origin === 'radar'">自動收錄</span>
        <span v-if="item.is_read">已封存</span>
        <time class="tabular-nums">{{ formatRelativeTime(item.created_at) }}</time>
      </div>
      <ItemActions :item="item" />
    </div>
  </article>
</template>
