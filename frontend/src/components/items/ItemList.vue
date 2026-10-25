<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { VList } from 'virtua/vue'
import { Inbox } from 'lucide-vue-next'
import ItemRow from './ItemRow.vue'
import ItemCards from './ItemCards.vue'
import SwipeableRow from './SwipeableRow.vue'
import Skeleton from '@/components/ui/skeleton/Skeleton.vue'
import { useItemsStore } from '@/stores/items'
import { useUiStore } from '@/stores/ui'

const items = useItemsStore()
const ui = useUiStore()

const vlist = ref<InstanceType<typeof VList> | null>(null)

const firstLoad = ref(true)
watch(
  () => items.loading,
  (loading, was) => {
    if (was && !loading) firstLoad.value = false
  },
)

const activeId = computed(() => ui.activeItem?.id ?? -1)

/** Scroll a row into view — used by J/K keyboard navigation. */
function scrollToIndex(index: number) {
  vlist.value?.scrollToIndex(index)
}

defineExpose({ scrollToIndex })
</script>

<template>
  <div class="flex min-h-0 flex-1 flex-col backdrop-blur-2xl [&::-webkit-scrollbar]:bg-transparent">
    <!-- Stream meta toolbar -->
    <div class="flex h-9 shrink-0 items-center justify-between px-4 text-2xs text-subtle-foreground">
      <div>
        <span>{{ items.loading ? '載入中…' : `${items.items.length} 個項目` }}</span>
        <span v-if="items.searchQuery" class="ml-2 font-medium text-primary">搜尋："{{ items.searchQuery }}"</span>
      </div>
      <div class="flex items-center gap-3 max-md:hidden">
        <span>J/K 巡航</span><span>E 歸檔</span><span>S 星標</span>
      </div>
    </div>

    <!-- First-load skeletons -->
    <div v-if="items.loading && firstLoad" class="flex-1 space-y-0 overflow-hidden" aria-label="載入中">
      <div v-for="i in 9" :key="i" class="flex items-start gap-3 border-b border-border/40 px-4 py-3.5">
        <Skeleton class="mt-1.5 size-2.5 rounded-full" />
        <div class="flex-1 space-y-2">
          <div class="flex gap-2">
            <Skeleton class="h-3.5 w-14" />
            <Skeleton class="h-3.5 w-16" />
            <Skeleton class="h-3.5 w-12 opacity-50" />
          </div>
          <Skeleton class="h-4 w-3/4" />
          <Skeleton class="h-3 w-1/2 opacity-60" />
        </div>
      </div>
    </div>

    <!-- Empty state -->
    <div v-else-if="!items.loading && items.items.length === 0" class="flex flex-1 flex-col items-center justify-center gap-3 px-6 py-20 text-center">
      <div class="flex size-16 items-center justify-center rounded-3xl bg-card text-primary shadow-card">
        <Inbox class="size-7" />
      </div>
      <div>
        <p class="text-base font-bold tracking-tight text-foreground">此視圖目前無內容</p>
        <p class="mt-1 max-w-xs text-xs leading-relaxed text-muted-foreground">
          在上方搜尋欄貼上連結按 Enter，或用 iPhone 捷徑一鍵存入，情報就會出現在這裡。
        </p>
      </div>
    </div>

    <!-- List mode: virtualized rows (ssrCount renders the first page even
         before/without ResizeObserver measurement, e.g. embedded webviews) -->
    <VList
      v-else-if="items.viewMode === 'list'"
      ref="vlist"
      :data="items.items"
      :item-size="92"
      :ssr-count="12"
      class="min-h-0 flex-1"
      :buffer-size="8"
    >
      <template #default="{ item }">
        <div :key="item.id" class="contents">
          <SwipeableRow :item="item">
            <ItemRow :item="item" :active="item.id === activeId" />
          </SwipeableRow>
        </div>
      </template>
    </VList>

    <!-- Cards mode: responsive grid with FLIP enter/leave -->
    <div v-else class="min-h-0 flex-1 overflow-y-auto p-4">
      <TransitionGroup
        name="cards"
        tag="div"
        class="grid grid-cols-1 content-start gap-3 md:grid-cols-2"
      >        <ItemCards v-for="item in items.items" :key="item.id" :item="item" />
      </TransitionGroup>
    </div>
  </div>
</template>

<style scoped>
.cards-enter-active {
  transition: opacity 240ms cubic-bezier(0.22, 1, 0.36, 1), transform 240ms cubic-bezier(0.22, 1, 0.36, 1);
}
.cards-enter-from {
  opacity: 0;
  transform: translateY(10px) scale(0.98);
}
.cards-leave-active {
  transition: opacity 160ms ease, transform 160ms ease;
  position: absolute;
  width: calc(50% - 6px);
}
.cards-leave-to {
  opacity: 0;
  transform: scale(0.96);
}
.cards-move {
  transition: transform 280ms cubic-bezier(0.22, 1, 0.36, 1);
}
</style>
