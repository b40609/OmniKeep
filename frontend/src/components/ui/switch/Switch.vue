<script setup lang="ts">
import { SwitchRoot, SwitchThumb } from 'reka-ui'

/** On/off control. The caller owns the value: `update:modelValue` asks for a change. */
defineProps<{ modelValue: boolean; disabled?: boolean; ariaLabel?: string; id?: string }>()
const emit = defineEmits<{ (e: 'update:modelValue', value: boolean): void }>()
</script>

<template>
  <SwitchRoot
    :id="id"
    class="ui-switch"
    :model-value="modelValue"
    :disabled="disabled"
    :aria-label="ariaLabel"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <SwitchThumb class="ui-switch__thumb" />
  </SwitchRoot>
</template>
