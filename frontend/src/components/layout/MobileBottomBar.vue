<script setup lang="ts">
import { Inbox, Star, Bot, Plus, Search } from 'lucide-vue-next'
import { useItemsStore, type TriageView } from '@/stores/items'
import { useUiStore } from '@/stores/ui'

const items = useItemsStore()
const ui = useUiStore()

function setView(view: TriageView) {
  items.triageView = view
  items.loadItems()
}
</script>

<template>
  <nav
    class="safe-bottom fixed inset-x-0 bottom-0 z-30 flex items-stretch border-t border-hairline bg-shell px-1 md:hidden"
    aria-label="快捷導覽"
  >
    <button class="bottom-tab" :aria-pressed="items.triageView === 'inbox'" @click="setView('inbox')">
      <Inbox aria-hidden="true" />
      <span>收件匣<span v-if="items.stats.inbox" class="ml-1 tabular-nums">{{ items.stats.inbox }}</span></span>
    </button>
    <button class="bottom-tab" :aria-pressed="items.triageView === 'starred'" @click="setView('starred')">
      <Star aria-hidden="true" />
      <span>加星</span>
    </button>
    <button class="bottom-tab" @click="ui.searchFocusRequests++">
      <Search aria-hidden="true" />
      <span>搜尋</span>
    </button>
    <button class="bottom-tab" @click="ui.showBrainModal = true">
      <Bot aria-hidden="true" />
      <span>問大腦</span>
    </button>
    <button class="bottom-tab" @click="ui.showNoteModal = true">
      <Plus aria-hidden="true" />
      <span>新增筆記</span>
    </button>
  </nav>
</template>

<style scoped>
.bottom-tab {
  display: flex;
  min-width: 0;
  min-height: 52px;
  flex: 1;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 3px;
  font-size: 12px;
  line-height: 16px;
  color: var(--muted-foreground);
}
.bottom-tab svg {
  width: 20px;
  height: 20px;
}
.bottom-tab[aria-pressed='true'] {
  font-weight: 600;
  color: var(--foreground);
}
</style>
