<script setup lang="ts">
import { TooltipRoot, TooltipTrigger, TooltipPortal, TooltipContent } from 'reka-ui'

/**
 * One sidebar row: icon (default slot), label, optional count on the right.
 * In the collapsed rail only the icon shows, and the label moves into a tooltip.
 * Extra attributes land on the button, so a menu can use the row as its trigger.
 */
defineOptions({ inheritAttrs: false })
withDefaults(
  defineProps<{
    label: string
    count?: number | null
    /** Leave unset for rows that open something instead of being a selected destination. */
    active?: boolean
    rail?: boolean
    minor?: boolean
  }>(),
  { count: null, active: undefined, rail: false, minor: false },
)
</script>

<template>
  <TooltipRoot :disabled="!rail">
    <TooltipTrigger as-child>
      <button
        type="button"
        class="nav-row"
        :class="{ 'nav-row--rail': rail, 'nav-row--minor': minor }"
        :aria-pressed="active"
        :aria-label="rail ? (count != null ? `${label}，${count} 則` : label) : undefined"
        v-bind="$attrs"
      >
        <slot />
        <template v-if="!rail">
          <span class="nav-row__label">{{ label }}</span>
          <span v-if="count != null" class="nav-row__count">{{ count }}</span>
        </template>
      </button>
    </TooltipTrigger>
    <!-- Only exists in the rail, so a tooltip cannot outlive the switch back to full rows -->
    <TooltipPortal v-if="rail">
      <TooltipContent side="right" :side-offset="12" class="nav-tip">
        {{ label }}<template v-if="count != null">　{{ count }}</template>
      </TooltipContent>
    </TooltipPortal>
  </TooltipRoot>
</template>
