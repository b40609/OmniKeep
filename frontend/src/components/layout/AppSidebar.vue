<script setup lang="ts">
import { computed } from 'vue'
import { useLocalStorage, useMediaQuery } from '@vueuse/core'
import {
  Inbox, Star, Archive, Layers, Folder, Plus, X, ChevronDown, ChevronUp,
  Compass, ScanEye, History,
} from 'lucide-vue-next'
import {
  DropdownMenuRoot, DropdownMenuTrigger, DropdownMenuPortal, DropdownMenuContent, DropdownMenuItem,
  DropdownMenuLabel, DropdownMenuSeparator, TooltipProvider,
} from 'reka-ui'
import SidebarRow from './SidebarRow.vue'
import { useItemsStore, type TriageView } from '@/stores/items'
import { useUiStore } from '@/stores/ui'
import { useExperimentsStore } from '@/stores/experiments'
import { WATCH_CATEGORIES } from '@/lib/experiments'
import { useMenuAction } from '@/composables/useMenuAction'

/**
 * The sidebar is navigation only: views, categories, and the experimental features
 * that are switched on in settings (each marked 實驗). Adding things, notifications
 * and settings live at the end of the top bar.
 */
const items = useItemsStore()
const ui = useUiStore()
const experiments = useExperimentsStore()
const desktop = useMediaQuery('(min-width: 768px)')
/** Collapsed on a wide screen is an icon-only rail; the phone drawer is always the full list. */
const rail = computed(() => desktop.value && !ui.sidebarOpen)

const views = computed(() => [
  { id: 'inbox' as TriageView, label: '收件匣', icon: Inbox, count: items.stats.inbox },
  { id: 'starred' as TriageView, label: '加星', icon: Star, count: items.stats.starred },
  { id: 'archived' as TriageView, label: '封存', icon: Archive, count: null },
  { id: 'all' as TriageView, label: '全部', icon: Layers, count: items.stats.total },
])

function setView(v: TriageView) {
  items.triageView = v
  items.loadItems()
  ui.sidebarMobileOpen = false
}

/* Categories: the fullest first, six showing until asked for more. */
const CATEGORY_LIMIT = 6
const showAllCategories = useLocalStorage('omnikeep-nav-all-categories', false)
const byCount = computed(() => [...items.categories].sort((a, b) => (b.item_count ?? 0) - (a.item_count ?? 0)))
const categories = computed(() => byCount.value.filter((c) => !WATCH_CATEGORIES.includes(c.name)))
// The project watcher's own categories show only while that feature is on, next to it.
const watchCategories = computed(() => (experiments.flags.watch ? byCount.value.filter((c) => WATCH_CATEGORIES.includes(c.name)) : []))
const anyExperiment = computed(() => experiments.flags.radar || experiments.flags.watch || experiments.flags.daily)
const shownCategories = computed(() => {
  const all = categories.value
  if (showAllCategories.value || all.length <= CATEGORY_LIMIT) return all
  const top = all.slice(0, CATEGORY_LIMIT)
  // The selected category stays in sight even when it is not one of the first six.
  const selected = all.find((c) => c.name === items.currentCategory)
  return selected && !top.includes(selected) ? [...top, selected] : top
})
const categoryName = (name: string) => (name === 'Inbox' ? '收件匣' : name)

/** Picking the selected category again clears the filter. */
function selectCategory(catName: string) {
  items.currentCategory = items.currentCategory === catName ? '全部' : catName
  items.loadItems()
  ui.sidebarMobileOpen = false
}

/** Open a dialog from the drawer and get the drawer out of its way. */
function openPanel(show: () => void) {
  show()
  ui.sidebarMobileOpen = false
}

// Menu items open their dialog once the menu has closed (see useMenuAction).
const menu = useMenuAction()
</script>

<template>
  <!-- Mobile backdrop -->
  <div
    v-if="ui.sidebarMobileOpen"
    class="fixed inset-0 z-40 bg-black/60 md:hidden"
    @click="ui.sidebarMobileOpen = false"
  />

  <aside
    class="z-40 flex h-full shrink-0 flex-col bg-shell transition-[width,transform] duration-200 motion-reduce:transition-none max-md:fixed max-md:inset-y-0 max-md:left-0 max-md:w-72 max-md:border-r max-md:border-hairline max-md:pt-[env(safe-area-inset-top)]"
    :inert="!desktop && !ui.sidebarMobileOpen"
    aria-label="主要導覽"
    :class="[rail ? 'md:w-[72px]' : 'md:w-60', ui.sidebarMobileOpen ? 'max-md:translate-x-0' : 'max-md:-translate-x-full']"
  >
    <TooltipProvider :delay-duration="150">
      <!-- Drawer header (phones only; on wider screens the product name is in the top bar) -->
      <div class="flex h-14 shrink-0 items-center justify-between pl-6 pr-2 md:hidden">
        <span class="text-lg font-bold tracking-[-0.01em]">OmniKeep</span>
        <button class="icon-button" aria-label="關閉選單" @click="ui.sidebarMobileOpen = false"><X /></button>
      </div>

      <nav class="min-h-0 flex-1 overflow-y-auto overflow-x-hidden px-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] pt-3" aria-label="收藏與分類">
        <!-- 1. Views -->
        <SidebarRow
          v-for="v in views"
          :key="v.id"
          :label="v.label"
          :count="v.count"
          :active="items.triageView === v.id"
          :rail="rail"
          @click="setView(v.id)"
        >
          <component :is="v.icon" aria-hidden="true" />
        </SidebarRow>

        <div class="nav-divider" />

        <!-- 2. Categories -->
        <template v-if="!rail">
          <div class="nav-heading">
            <h2>分類</h2>
            <button class="nav-heading__button" aria-label="新增分類" title="新增分類" @click="openPanel(() => (ui.showCategoryModal = true))"><Plus /></button>
          </div>
          <SidebarRow
            v-for="cat in shownCategories"
            :key="cat.id"
            :label="categoryName(cat.name)"
            :count="cat.item_count ?? 0"
            :active="items.currentCategory === cat.name"
            :title="items.currentCategory === cat.name ? '再按一次顯示所有分類' : undefined"
            @click="selectCategory(cat.name)"
          >
            <Folder aria-hidden="true" />
          </SidebarRow>
          <SidebarRow
            v-if="categories.length > CATEGORY_LIMIT"
            minor
            :label="showAllCategories ? '顯示較少' : `顯示另外 ${categories.length - shownCategories.length} 個`"
            :aria-expanded="showAllCategories"
            @click="showAllCategories = !showAllCategories"
          >
            <ChevronUp v-if="showAllCategories" aria-hidden="true" />
            <ChevronDown v-else aria-hidden="true" />
          </SidebarRow>
        </template>
        <DropdownMenuRoot v-else>
          <DropdownMenuTrigger as-child>
            <SidebarRow label="分類" rail :active="items.currentCategory !== '全部' ? true : undefined">
              <Folder aria-hidden="true" />
            </SidebarRow>
          </DropdownMenuTrigger>
          <DropdownMenuPortal>
            <DropdownMenuContent class="app-menu" side="right" align="start" :side-offset="12" :collision-padding="12" @close-auto-focus="menu.flush">
              <DropdownMenuLabel class="app-menu__label">分類</DropdownMenuLabel>
              <DropdownMenuItem v-for="cat in categories" :key="cat.id" class="app-menu__item" :data-state="items.currentCategory === cat.name ? 'checked' : undefined" @select="selectCategory(cat.name)">
                <Folder aria-hidden="true" />{{ categoryName(cat.name) }}
                <span class="app-menu__end">{{ cat.item_count ?? 0 }}</span>
              </DropdownMenuItem>
              <DropdownMenuSeparator class="app-menu__rule" />
              <DropdownMenuItem class="app-menu__item" @select="menu.defer(() => (ui.showCategoryModal = true))"><Plus aria-hidden="true" />新增分類</DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenuPortal>
        </DropdownMenuRoot>

        <!-- 3. Experimental features that are switched on: ordinary rows, each marked 實驗 -->
        <template v-if="anyExperiment">
          <div class="nav-divider" />
          <SidebarRow v-if="experiments.flags.radar" label="探索" tag="實驗" :rail="rail" :count="items.stats.radar || null" :active="items.triageView === 'radar'" :title="rail ? undefined : '探索找到、還沒處理的內容'" @click="setView('radar')">
            <Compass aria-hidden="true" />
          </SidebarRow>
          <template v-if="experiments.flags.watch">
            <SidebarRow label="專案監看" tag="實驗" :rail="rail" @click="openPanel(() => (ui.showWatchModal = true))">
              <ScanEye aria-hidden="true" />
            </SidebarRow>
            <template v-if="!rail">
              <SidebarRow
                v-for="cat in watchCategories"
                :key="cat.id"
                :label="`專案監看：${cat.name === '提案' ? '建議' : cat.name}`"
                :count="cat.item_count ?? 0"
                :active="items.currentCategory === cat.name"
                @click="selectCategory(cat.name)"
              >
                <Folder aria-hidden="true" />
              </SidebarRow>
            </template>
          </template>
          <SidebarRow v-if="experiments.flags.daily" label="每日回顧" tag="實驗" :rail="rail" :title="rail ? undefined : '每日回顧　Shift+D'" @click="openPanel(() => (ui.showDailyDeckModal = true))">
            <History aria-hidden="true" />
          </SidebarRow>
        </template>
      </nav>
    </TooltipProvider>
  </aside>
</template>
