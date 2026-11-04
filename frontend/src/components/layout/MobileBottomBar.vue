<script setup lang="ts">
import { computed } from 'vue'
import {
  Inbox, Radio, Sparkles, Bot, Plus, Search
} from 'lucide-vue-next'
import { useItemsStore } from '@/stores/items'
import { useUiStore } from '@/stores/ui'

const items = useItemsStore()
const ui = useUiStore()

const isRadarActive = computed(() => items.triageView === 'radar')

function toggleInboxRadar() {
  if (items.triageView === 'radar') {
    items.triageView = 'inbox'
  } else {
    items.triageView = 'radar'
  }
  items.loadItems()
}
</script>

<template>
  <nav
    class="fixed bottom-0 inset-x-0 z-30 flex md:hidden items-center justify-around border-t border-hairline bg-card/90 backdrop-blur-xl px-2 py-1.5 safe-bottom shadow-[0_-4px_20px_rgba(0,0,0,0.06)]"
    aria-label="行動端快捷導航"
  >
    <!-- 1. Triage Toggle (Inbox vs Radar) -->
    <button
      class="flex flex-1 flex-col items-center justify-center gap-1 py-1 rounded-xl transition cursor-pointer"
      :class="items.triageView === 'inbox' || items.triageView === 'radar' ? 'text-primary font-semibold' : 'text-muted-foreground hover:text-foreground'"
      @click="toggleInboxRadar"
    >
      <div class="relative flex items-center justify-center">
        <Radio v-if="isRadarActive" class="size-5" />
        <Inbox v-else class="size-5" />
        <span
          v-if="isRadarActive ? items.stats.radar : items.stats.inbox"
          class="absolute -top-1 -right-2 flex min-w-4 items-center justify-center rounded-full bg-primary px-1 text-3xs font-mono font-bold text-primary-foreground tabular-nums leading-tight"
        >
          {{ isRadarActive ? items.stats.radar : items.stats.inbox }}
        </span>
      </div>
      <span class="text-3xs font-medium">
        {{ isRadarActive ? '雷達發現' : '收件匣' }}
      </span>
    </button>

    <!-- 2. Command Palette / Search -->
    <button
      class="flex flex-1 flex-col items-center justify-center gap-1 py-1 rounded-xl transition cursor-pointer text-muted-foreground hover:text-foreground"
      @click="ui.showCommandPalette = true"
    >
      <div class="flex size-7 items-center justify-center rounded-full bg-muted/60 text-foreground">
        <Search class="size-4" />
      </div>
      <span class="text-3xs font-medium">指令搜尋</span>
    </button>

    <!-- 3. Daily Deck (Primary Action Island) -->
    <button
      class="flex flex-1 flex-col items-center justify-center gap-1 py-1 rounded-xl transition cursor-pointer text-amber-500 hover:text-amber-600"
      @click="ui.showDailyDeckModal = true"
    >
      <div class="flex size-7 items-center justify-center rounded-full bg-amber-500/15 text-amber-500 shadow-xs">
        <Sparkles class="size-4" />
      </div>
      <span class="text-3xs font-semibold">每日回顧</span>
    </button>

    <!-- 4. Ask Brain -->
    <button
      class="flex flex-1 flex-col items-center justify-center gap-1 py-1 rounded-xl transition cursor-pointer text-foreground hover:text-primary"
      @click="ui.showBrainModal = true"
    >
      <div class="flex size-7 items-center justify-center rounded-full bg-primary/10 text-primary shadow-xs">
        <Bot class="size-4" />
      </div>
      <span class="text-3xs font-medium">對話大腦</span>
    </button>

    <!-- 5. Quick Note / Ingest -->
    <button
      class="flex flex-1 flex-col items-center justify-center gap-1 py-1 rounded-xl transition cursor-pointer text-muted-foreground hover:text-foreground"
      @click="ui.showNoteModal = true"
    >
      <div class="flex size-7 items-center justify-center rounded-full bg-muted text-foreground">
        <Plus class="size-4" />
      </div>
      <span class="text-3xs font-medium">新增筆記</span>
    </button>
  </nav>
</template>
