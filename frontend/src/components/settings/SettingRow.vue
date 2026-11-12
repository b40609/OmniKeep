<script setup lang="ts">
/**
 * One setting: its name and a line of help on the left, the control on the right.
 * `stacked` puts the control under the name, for anything long to type.
 */
defineProps<{ name: string; help?: string; stacked?: boolean; for?: string }>()
</script>

<template>
  <div class="set-row" :class="{ 'set-row--stacked': stacked }">
    <div class="set-row__text">
      <div class="set-row__name">
        <label v-if="$props.for" :for="$props.for">{{ name }}</label>
        <span v-else>{{ name }}</span>
        <slot name="mark" />
      </div>
      <p v-if="help" class="set-row__help">{{ help }}</p>
      <slot name="below" />
    </div>
    <div v-if="$slots.default" class="set-row__control"><slot /></div>
  </div>
</template>
