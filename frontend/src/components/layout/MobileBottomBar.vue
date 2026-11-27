<script setup lang="ts">
import { Inbox, Scale, Star, Plus, Search, Loader2 } from 'lucide-vue-next'
import { useItemsStore, type TriageView } from '@/stores/items'
import { useUiStore } from '@/stores/ui'
import { useEvaluationsStore } from '@/stores/evaluations'
import { useExperimentsStore } from '@/stores/experiments'

const items = useItemsStore()
const ui = useUiStore()
const evaluations = useEvaluationsStore()
const experiments = useExperimentsStore()

function setView(view: TriageView) {
  items.triageView = view
  items.currentCategory = '全部'
  items.loadItems()
}
</script>

<template>
  <nav
    class="bottom-bar fixed inset-x-0 bottom-0 z-30 flex items-stretch border-t border-hairline bg-shell px-1 md:hidden"
    aria-label="快捷導覽"
  >
    <button type="button" class="bottom-tab" :aria-pressed="!ui.showEvalModal && items.triageView === 'inbox'" @click="setView('inbox')">
      <span class="bottom-tab__icon">
        <Inbox aria-hidden="true" />
      </span>
      <span>收件匣</span>
    </button>
    <button v-if="experiments.flags.eval" type="button" class="bottom-tab" :aria-pressed="ui.showEvalModal" @click="ui.openEvaluations()">
      <span class="bottom-tab__icon">
        <Scale aria-hidden="true" />
        <span
          v-if="evaluations.counts.needs_decision"
          class="bottom-tab__badge"
          :aria-label="`${evaluations.counts.needs_decision} 項待拍板`"
        >{{ evaluations.counts.needs_decision > 99 ? '99+' : evaluations.counts.needs_decision }}</span>
      </span>
      <span>待決</span>
    </button>
    <button type="button" class="bottom-tab" :aria-pressed="!ui.showEvalModal && items.triageView === 'starred'" @click="setView('starred')">
      <span class="bottom-tab__icon">
        <Star aria-hidden="true" />
      </span>
      <span>加星</span>
    </button>
    <button type="button" class="bottom-tab" @click="ui.searchFocusRequests++">
      <span class="bottom-tab__icon">
        <Search aria-hidden="true" />
      </span>
      <span>搜尋</span>
    </button>
    <button type="button" class="bottom-tab" @click="ui.openAdd()">
      <span class="bottom-tab__icon">
        <Loader2 v-if="ui.isIngesting" class="animate-spin text-primary" aria-hidden="true" />
        <Plus v-else aria-hidden="true" />
      </span>
      <span>新增</span>
    </button>
  </nav>
</template>

<style scoped>
.bottom-bar {
  padding-bottom: max(4px, env(safe-area-inset-bottom));
}
.bottom-tab {
  display: flex;
  min-width: 0;
  min-height: 54px;
  flex: 1;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 3px;
  padding: 6px 2px 4px;
  font-size: 12px;
  line-height: 16px;
  color: var(--muted-foreground);
  transition: color 150ms ease-out;
}
.bottom-tab__icon {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 22px;
}
.bottom-tab__icon > svg {
  width: 20px;
  height: 20px;
}
.bottom-tab__badge {
  position: absolute;
  top: -4px;
  left: 14px;
  min-width: 16px;
  height: 16px;
  padding: 0 4px;
  border-radius: 6px;
  background: var(--primary);
  color: var(--primary-foreground);
  font-size: 12px;
  font-weight: 600;
  line-height: 16px;
  text-align: center;
  font-variant-numeric: tabular-nums;
}
.bottom-tab[aria-pressed='true'] {
  font-weight: 600;
  color: var(--primary);
}
</style>
