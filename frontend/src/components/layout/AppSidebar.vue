<script setup lang="ts">
import { computed } from 'vue'
import { useLocalStorage, useMediaQuery } from '@vueuse/core'
import {
  Inbox, Star, Archive, Layers, Folder, Plus, X, ChevronDown, ChevronUp, ChevronRight, Check,
  FlaskConical, Radar, ScanEye, Sparkles,
  Settings, Palette, Bell, KeyRound, FolderInput, Keyboard, LogOut,
} from 'lucide-vue-next'
import {
  DropdownMenuRoot, DropdownMenuTrigger, DropdownMenuPortal, DropdownMenuContent, DropdownMenuItem,
  DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuSub, DropdownMenuSubTrigger, DropdownMenuSubContent,
  DropdownMenuRadioGroup, DropdownMenuRadioItem, DropdownMenuItemIndicator, TooltipProvider,
} from 'reka-ui'
import SidebarRow from './SidebarRow.vue'
import { useItemsStore, type TriageView } from '@/stores/items'
import { useUiStore } from '@/stores/ui'
import { useTheme, type AccentColor } from '@/composables/useTheme'
import { useMenuAction } from '@/composables/useMenuAction'
import { THEME_MODES, type ThemeMode } from '@/lib/themeMode'

/**
 * The sidebar only holds places to go: views, categories, experimental features.
 * Creating things lives in the top bar; settings, theme, sign-out and the like
 * sit behind the single 設定 row at the bottom.
 */
const emit = defineEmits<{ (e: 'logout'): void }>()

const items = useItemsStore()
const ui = useUiStore()
const { mode, accent, accents, labels, set: setTheme, setAccent } = useTheme()
const appVersion = __APP_VERSION__
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
const categories = computed(() => [...items.categories].sort((a, b) => (b.item_count ?? 0) - (a.item_count ?? 0)))
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

/* Experimental features stay reachable but start folded away. */
const experimentalOpen = useLocalStorage('omnikeep-nav-experimental', false)

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
      <div class="flex h-14 shrink-0 items-center justify-between pl-[26px] pr-2 md:hidden">
        <span class="text-[17px] font-bold tracking-[-0.01em]">OmniKeep</span>
        <button class="item-action" aria-label="關閉選單" @click="ui.sidebarMobileOpen = false"><X class="size-5" /></button>
      </div>

      <nav class="min-h-0 flex-1 overflow-y-auto overflow-x-hidden px-3 pb-3 pt-2" aria-label="收藏與分類">
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
            :label="showAllCategories ? '顯示較少' : `顯示更多（${categories.length - shownCategories.length}）`"
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

        <div class="nav-divider" />

        <!-- 3. Experimental: folded away until asked for -->
        <template v-if="!rail">
          <h2>
            <button type="button" class="nav-heading" :aria-expanded="experimentalOpen" aria-controls="nav-experimental" @click="experimentalOpen = !experimentalOpen">
              實驗功能
              <ChevronUp v-if="experimentalOpen" aria-hidden="true" />
              <ChevronDown v-else aria-hidden="true" />
            </button>
          </h2>
          <div v-if="experimentalOpen" id="nav-experimental">
            <SidebarRow label="雷達" :count="items.stats.radar || null" :active="items.triageView === 'radar'" title="雷達找來的候選內容" @click="setView('radar')">
              <Radar aria-hidden="true" />
            </SidebarRow>
            <SidebarRow label="專案監看" @click="openPanel(() => (ui.showWatchModal = true))">
              <ScanEye aria-hidden="true" />
            </SidebarRow>
            <SidebarRow label="每日回顧" title="每日回顧　Shift+D" @click="openPanel(() => (ui.showDailyDeckModal = true))">
              <Sparkles aria-hidden="true" />
            </SidebarRow>
          </div>
        </template>
        <DropdownMenuRoot v-else>
          <DropdownMenuTrigger as-child>
            <SidebarRow label="實驗功能" rail :count="items.stats.radar || null" :active="items.triageView === 'radar' ? true : undefined">
              <FlaskConical aria-hidden="true" />
            </SidebarRow>
          </DropdownMenuTrigger>
          <DropdownMenuPortal>
            <DropdownMenuContent class="app-menu" side="right" align="start" :side-offset="12" :collision-padding="12" @close-auto-focus="menu.flush">
              <DropdownMenuLabel class="app-menu__label">實驗功能</DropdownMenuLabel>
              <DropdownMenuItem class="app-menu__item" @select="setView('radar')">
                <Radar aria-hidden="true" />雷達<span v-if="items.stats.radar" class="app-menu__end">{{ items.stats.radar }}</span>
              </DropdownMenuItem>
              <DropdownMenuItem class="app-menu__item" @select="menu.defer(() => (ui.showWatchModal = true))"><ScanEye aria-hidden="true" />專案監看</DropdownMenuItem>
              <DropdownMenuItem class="app-menu__item" @select="menu.defer(() => (ui.showDailyDeckModal = true))"><Sparkles aria-hidden="true" />每日回顧</DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenuPortal>
        </DropdownMenuRoot>
      </nav>

      <!-- 4. Settings: one labelled row; everything that used to be an icon is a named item in its menu -->
      <div class="shrink-0 border-t border-hairline px-3 pb-[max(0.5rem,env(safe-area-inset-bottom))] pt-2">
        <DropdownMenuRoot>
          <DropdownMenuTrigger as-child>
            <SidebarRow label="設定" :rail="rail">
              <Settings aria-hidden="true" />
            </SidebarRow>
          </DropdownMenuTrigger>
          <DropdownMenuPortal>
            <DropdownMenuContent class="app-menu" :side="rail ? 'right' : 'top'" :align="rail ? 'end' : 'start'" :side-offset="8" :collision-padding="12" @close-auto-focus="menu.flush">
              <DropdownMenuItem class="app-menu__item" @select="menu.defer(() => ui.openSettings())"><Settings aria-hidden="true" />設定</DropdownMenuItem>
              <DropdownMenuSub>
                <DropdownMenuSubTrigger class="app-menu__item">
                  <Palette aria-hidden="true" />外觀主題
                  <span class="app-menu__end">{{ labels[mode] }}<ChevronRight aria-hidden="true" /></span>
                </DropdownMenuSubTrigger>
                <DropdownMenuPortal>
                  <DropdownMenuSubContent class="app-menu" :side-offset="10" :collision-padding="12">
                    <DropdownMenuLabel class="app-menu__label">主題</DropdownMenuLabel>
                    <!-- Choosing keeps the menu open, so themes can be tried one after another -->
                    <DropdownMenuRadioGroup :model-value="mode" @update:model-value="setTheme($event as ThemeMode)">
                      <DropdownMenuRadioItem v-for="option in THEME_MODES" :key="option" :value="option" class="app-menu__item" @select.prevent>
                        {{ labels[option] }}
                        <span class="app-menu__end"><DropdownMenuItemIndicator><Check aria-hidden="true" /></DropdownMenuItemIndicator></span>
                      </DropdownMenuRadioItem>
                    </DropdownMenuRadioGroup>
                    <DropdownMenuSeparator class="app-menu__rule" />
                    <DropdownMenuLabel class="app-menu__label">強調色</DropdownMenuLabel>
                    <DropdownMenuRadioGroup :model-value="accent" @update:model-value="setAccent($event as AccentColor)">
                      <DropdownMenuRadioItem v-for="opt in accents" :key="opt.id" :value="opt.id" class="app-menu__item" @select.prevent>
                        <span class="app-menu__swatch" :style="{ backgroundColor: opt.color }" aria-hidden="true" />{{ opt.label }}
                        <span class="app-menu__end"><DropdownMenuItemIndicator><Check aria-hidden="true" /></DropdownMenuItemIndicator></span>
                      </DropdownMenuRadioItem>
                    </DropdownMenuRadioGroup>
                  </DropdownMenuSubContent>
                </DropdownMenuPortal>
              </DropdownMenuSub>
              <DropdownMenuItem class="app-menu__item" @select="menu.defer(() => openPanel(() => (ui.showPushModal = true)))"><Bell aria-hidden="true" />通知</DropdownMenuItem>
              <DropdownMenuItem class="app-menu__item" @select="menu.defer(() => openPanel(() => (ui.showSessionModal = true)))"><KeyRound aria-hidden="true" />社群平台登入</DropdownMenuItem>
              <DropdownMenuItem class="app-menu__item" @select="menu.defer(() => openPanel(() => (ui.showImportModal = true)))"><FolderInput aria-hidden="true" />匯入書籤</DropdownMenuItem>
              <DropdownMenuItem class="app-menu__item" @select="menu.defer(() => openPanel(() => (ui.showShortcutsModal = true)))"><Keyboard aria-hidden="true" />鍵盤快捷鍵</DropdownMenuItem>
              <DropdownMenuSeparator class="app-menu__rule" />
              <DropdownMenuItem class="app-menu__item" @select="emit('logout')"><LogOut aria-hidden="true" />登出</DropdownMenuItem>
              <DropdownMenuLabel class="app-menu__label">OmniKeep v{{ appVersion }}</DropdownMenuLabel>
            </DropdownMenuContent>
          </DropdownMenuPortal>
        </DropdownMenuRoot>
      </div>
    </TooltipProvider>
  </aside>
</template>
