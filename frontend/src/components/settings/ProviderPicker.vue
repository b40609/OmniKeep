<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ChevronDown } from 'lucide-vue-next'
import type { AiCard, AiCardGroup, AiRecommendation } from '@/lib/api'
import { cardUses, groupCards, recommendedSteps } from '@/lib/setup'

/**
 * 選一個 AI 服務, shared by 設定 › AI and the first-run guide (2026-11-23, layout D): the
 * suggested fallback combo first, then every service folded under its kind of free, so a
 * newcomer is not handed 23 cards at once and someone comparing can still open any group.
 */
const props = withDefaults(defineProps<{
  cards: AiCard[]
  groups: AiCardGroup[]
  recommended?: AiRecommendation[]
  /** Card ids that already have a connection: their step shows 已連上. */
  connected?: string[]
  /** The card currently chosen (the guide), highlighted and kept in view. */
  selected?: string
  /** Each service is a radio (the guide picks one) rather than a plain button. */
  radio?: boolean
  /** Text of the button that adds the whole combo; none hides it. */
  comboLabel?: string
}>(), { recommended: () => [], connected: () => [], selected: '', radio: false, comboLabel: '' })

const emit = defineEmits<{ pick: [id: string]; combo: [] }>()

const steps = computed(() => recommendedSteps(props.cards, props.recommended, props.connected))
const pending = computed(() => steps.value.filter((s) => !s.done).length)
const grouped = computed(() => groupCards(props.cards, props.groups))

const open = ref(new Set<string>())
function toggle(id: string) {
  const next = new Set(open.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  open.value = next
}
// The chosen card's group opens by itself, so a choice never sits hidden in a folded group.
watch(() => [props.selected, grouped.value] as const, ([id]) => {
  const g = grouped.value.find((x) => x.cards.some((c) => c.id === id))
  if (g && !open.value.has(g.group.id)) open.value = new Set([...open.value, g.group.id])
}, { immediate: true })

const pickAttrs = (id: string) => (props.radio ? { role: 'radio', 'aria-checked': props.selected === id } : {})
</script>

<template>
  <div>
    <div v-if="steps.length" class="rounded-xl border border-border p-4">
      <p class="text-sm font-semibold">建議：{{ steps.length }} 條免費連線輪流用</p>
      <p class="set-text mt-0.5">都能免費長期用。第一條撞到上限，自動換下一條。</p>
      <ol class="mt-3 grid gap-2 sm:grid-cols-3">
        <li v-for="(s, i) in steps" :key="s.card.id" class="min-w-0">
          <button
            type="button"
            v-bind="pickAttrs(s.card.id)"
            class="flex h-full w-full cursor-pointer flex-col rounded-lg border p-2.5 text-left transition-colors"
            :class="selected === s.card.id ? 'border-primary bg-primary/10' : 'border-border hover:bg-surface-2'"
            @click="emit('pick', s.card.id)"
          >
            <span class="text-xs text-muted-foreground">第 {{ i + 1 }} 條<span v-if="s.done" class="text-success">・已連上</span></span>
            <span class="mt-0.5 text-sm font-semibold [overflow-wrap:anywhere]">{{ s.card.label }}</span>
            <span class="mt-0.5 text-xs text-muted-foreground [overflow-wrap:anywhere]">{{ s.why }}</span>
          </button>
        </li>
      </ol>
      <template v-if="comboLabel">
        <button v-if="pending" type="button" class="set-button mt-3" @click="emit('combo')">{{ comboLabel }}</button>
        <p v-else class="set-text mt-3">這 {{ steps.length }} 條都已連上。</p>
      </template>
    </div>

    <div :class="steps.length ? 'mt-4' : ''">
      <section v-for="g in grouped" :key="g.group.id" class="border-t border-hairline last:border-b">
        <template v-if="g.group.title">
          <button
            type="button"
            class="flex min-h-11 w-full cursor-pointer items-center justify-between gap-3 px-1 py-2 text-left text-sm"
            :aria-expanded="open.has(g.group.id)"
            @click="toggle(g.group.id)"
          >
            <span class="font-medium">{{ g.group.title }}</span>
            <span class="flex shrink-0 items-center gap-1 text-xs text-muted-foreground">
              {{ g.cards.length }} 個
              <ChevronDown class="size-4 transition-transform" :class="open.has(g.group.id) ? 'rotate-180' : ''" aria-hidden="true" />
            </span>
          </button>
        </template>
        <div v-if="!g.group.title || open.has(g.group.id)" class="pb-3">
          <p v-if="g.group.how" class="set-text px-1">{{ g.group.how }}</p>
          <ul class="mt-2">
            <li v-for="c in g.cards" :key="c.id" class="border-t border-hairline first:border-t-0">
              <button
                type="button"
                v-bind="pickAttrs(c.id)"
                class="w-full cursor-pointer rounded-lg px-2 py-2.5 text-left transition-colors"
                :class="selected === c.id ? 'bg-primary/10' : 'hover:bg-surface-2'"
                @click="emit('pick', c.id)"
              >
                <span class="flex items-baseline justify-between gap-3">
                  <span class="text-sm font-semibold [overflow-wrap:anywhere]">{{ c.label }}</span>
                  <span class="shrink-0 text-right text-xs text-muted-foreground">{{ c.cost }}</span>
                </span>
                <span class="mt-0.5 block text-sm text-muted-foreground [overflow-wrap:anywhere]">{{ c.limits }}</span>
                <span class="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                  <span v-if="c.ended" class="set-tag">活動已結束</span>
                  <span v-for="use in cardUses(c)" :key="use" class="set-tag">{{ use }}</span>
                  <span>{{ c.verified }} 查證</span>
                </span>
              </button>
            </li>
          </ul>
        </div>
      </section>
    </div>
  </div>
</template>
