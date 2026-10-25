<script setup lang="ts">
import { computed } from 'vue'
import { Inbox, Star, Archive, Layers, Plus } from 'lucide-vue-next'
import { useItemsStore, type TriageView } from '@/stores/items'
import { useUiStore } from '@/stores/ui'

const items = useItemsStore()
const ui = useUiStore()

const views = computed(() => [
  { id: 'inbox' as TriageView, label: '待讀', icon: Inbox, count: items.stats.inbox },
  { id: 'starred' as TriageView, label: '星標', icon: Star, count: items.stats.starred },
  { id: 'archived' as TriageView, label: '封存', icon: Archive, count: items.stats.archived },
  { id: 'all' as TriageView, label: '全部', icon: Layers, count: items.stats.total },
])

function setView(v: TriageView) {
  items.triageView = v
  items.loadItems()
}
</script>

<template>
  <div class="ios-blur z-20 flex h-12 shrink-0 items-center gap-3 border-b border-white/40 px-3 shadow-sm dark:border-white/10 sm:px-4">
    <!-- iOS segmented control -->
    <div class="flex items-center rounded-[10px] bg-white/50 p-0.5 shadow-inner dark:bg-white/[0.08]" role="tablist" aria-label="分類視圖">
      <button
        v-for="v in views"
        :key="v.id"
        role="tab"
        :aria-selected="items.triageView === v.id"
        class="flex h-7 items-center gap-1 rounded-[8px] px-2.5 text-xs font-medium transition-all duration-200"
        :class="items.triageView === v.id
          ? 'bg-white/90 text-foreground shadow-md font-semibold dark:bg-white/[0.16]'
          : 'text-muted-foreground active:opacity-70'"
        @click="setView(v.id)"
      >
        <component :is="v.icon" class="size-3.5" :class="items.triageView === v.id ? 'text-primary' : ''" />
        <span class="max-sm:hidden">{{ v.label }}</span>
        <span
          class="min-w-4 rounded-full px-1 text-2xs font-semibold tabular-nums"
          :class="items.triageView === v.id ? 'bg-primary-soft text-primary' : 'text-subtle-foreground'"
        >{{ v.count }}</span>
      </button>
    </div>

    <!-- Category chips -->
    <div class="no-scrollbar flex flex-1 items-center justify-end gap-1.5 overflow-x-auto">
      <button
        class="h-7 shrink-0 rounded-full px-3 text-2xs font-semibold transition-all duration-150 active:scale-[0.96]"
        :class="items.currentCategory === '全部'
          ? 'bg-primary text-primary-foreground shadow-sm'
          : 'bg-white/50 text-muted-foreground hover:text-foreground dark:bg-white/[0.08]'"
        @click="items.currentCategory = '全部'; items.loadItems()"
      >
        全部
      </button>
      <button
        v-for="cat in items.categories"
        :key="cat.id"
        class="flex h-7 shrink-0 items-center gap-1 rounded-full px-3 text-2xs font-medium transition-all duration-150 active:scale-[0.96]"
        :class="items.currentCategory === cat.name
          ? 'bg-primary text-primary-foreground shadow-sm font-semibold'
          : 'bg-white/50 text-muted-foreground hover:text-foreground dark:bg-white/[0.08]'"
        @click="items.currentCategory = cat.name; items.loadItems()"
      >
        <span>{{ cat.name }}</span>
        <span class="text-2xs tabular-nums opacity-70">{{ cat.item_count ?? 0 }}</span>
      </button>
      <button
        class="flex h-7 shrink-0 items-center gap-1 rounded-full bg-white/50 px-2.5 dark:bg-white/[0.08] text-2xs font-medium text-primary transition-all active:scale-[0.96]"
        aria-label="新增分類"
        @click="ui.showCategoryModal = true"
      >
        <Plus class="size-3" /> 新增
      </button>
    </div>
  </div>
</template>
