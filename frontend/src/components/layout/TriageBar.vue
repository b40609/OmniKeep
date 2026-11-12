<script setup lang="ts">
import { computed } from 'vue'
import { Inbox, Star, Archive, Layers, Plus, Radio } from 'lucide-vue-next'
import { useItemsStore, type TriageView } from '@/stores/items'
import { useUiStore } from '@/stores/ui'

const items = useItemsStore()
const ui = useUiStore()

const views = computed(() => [
  { id: 'inbox' as TriageView, label: '待讀', icon: Inbox, count: items.stats.inbox },
  { id: 'radar' as TriageView, label: '探索', icon: Radio, count: items.stats.radar },
  { id: 'starred' as TriageView, label: '加星', icon: Star, count: items.stats.starred },
  { id: 'archived' as TriageView, label: '封存', icon: Archive, count: items.stats.archived },
  { id: 'all' as TriageView, label: '全部', icon: Layers, count: items.stats.total },
])

function setView(v: TriageView) {
  items.triageView = v
  items.loadItems()
}
</script>

<template>
  <div class="z-20 flex shrink-0 flex-wrap items-center gap-2 border-b border-hairline bg-card px-3 py-2 sm:px-4">
    <!-- iOS segmented control -->
    <div class="grid w-full grid-cols-5 gap-1 rounded-lg bg-muted p-1 xl:w-auto" role="group" aria-label="收藏狀態">
      <button
        v-for="v in views"
        :key="v.id"
        :aria-pressed="items.triageView === v.id"
        :aria-label="`${v.label}，${v.count} 個項目`"
        class="flex min-h-11 min-w-0 items-center justify-center gap-1 rounded-lg px-1 text-xs font-medium transition-colors xl:px-3"
        :class="items.triageView === v.id
          ? 'bg-card text-foreground font-semibold'
          : 'text-muted-foreground hover:bg-accent'"
        @click="setView(v.id)"
      >
        <component :is="v.icon" class="hidden size-3.5 shrink-0 sm:block" />
        <span class="shrink-0">{{ v.label }}</span>
        <span
          class="max-w-10 truncate text-xs tabular-nums text-muted-foreground"
        >{{ v.count }}</span>
      </button>
    </div>

    <!-- Category chips -->
    <div class="flex min-w-0 basis-full items-center gap-1 overflow-x-auto xl:basis-0 xl:flex-1" role="group" aria-label="分類篩選">
      <button
        class="min-h-11 shrink-0 rounded-lg px-3 text-xs font-medium transition-colors"
        :aria-pressed="items.currentCategory === '全部'"
        :class="items.currentCategory === '全部'
          ? 'bg-primary-soft text-primary-soft-foreground'
          : 'text-muted-foreground hover:bg-accent hover:text-foreground'"
        @click="items.currentCategory = '全部'; items.loadItems()"
      >
        全部
      </button>
      <button
        v-for="cat in items.categories"
        :key="cat.id"
        class="flex min-h-11 shrink-0 items-center gap-1 rounded-lg px-3 text-xs font-medium transition-colors"
        :aria-pressed="items.currentCategory === cat.name"
        :class="items.currentCategory === cat.name
          ? 'bg-primary-soft text-primary-soft-foreground font-semibold'
          : 'text-muted-foreground hover:bg-accent hover:text-foreground'"
        @click="items.currentCategory = cat.name; items.loadItems()"
      >
        <span>{{ cat.name === 'Inbox' ? '收件匣' : cat.name }}</span>
        <span class="text-xs tabular-nums">{{ cat.item_count ?? 0 }}</span>
      </button>
      <button
        class="flex min-h-11 shrink-0 items-center gap-1 rounded-lg px-3 text-xs font-medium text-primary-soft-foreground transition-colors hover:bg-accent"
        aria-label="新增分類"
        @click="ui.showCategoryModal = true"
      >
        <Plus class="size-3" /> 新增
      </button>
    </div>
  </div>
</template>
