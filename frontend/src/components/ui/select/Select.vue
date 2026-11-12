<script setup lang="ts">
import { Check, ChevronDown } from 'lucide-vue-next'
import {
  SelectRoot, SelectTrigger, SelectValue, SelectPortal, SelectContent, SelectViewport, SelectItem,
  SelectItemText, SelectItemIndicator,
} from 'reka-ui'

export interface SelectOption {
  value: string
  label: string
  disabled?: boolean
}

/** Pick one of a few options: a 40px trigger whose list is styled like every other menu. */
defineProps<{
  modelValue: string
  options: SelectOption[]
  placeholder?: string
  disabled?: boolean
  ariaLabel?: string
  id?: string
  block?: boolean
  small?: boolean
}>()
const emit = defineEmits<{ (e: 'update:modelValue', value: string): void }>()
</script>

<template>
  <SelectRoot :model-value="modelValue" :disabled="disabled" @update:model-value="emit('update:modelValue', String($event))">
    <SelectTrigger :id="id" class="ui-select" :class="{ 'ui-select--block': block, 'ui-select--small': small }" :aria-label="ariaLabel">
      <SelectValue :placeholder="placeholder" />
      <ChevronDown aria-hidden="true" />
    </SelectTrigger>
    <SelectPortal>
      <SelectContent class="app-menu ui-select__list" position="popper" :side-offset="4" :collision-padding="12">
        <SelectViewport>
          <SelectItem v-for="option in options" :key="option.value" :value="option.value" :disabled="option.disabled" class="app-menu__item">
            <SelectItemText>{{ option.label }}</SelectItemText>
            <span class="app-menu__end"><SelectItemIndicator><Check aria-hidden="true" /></SelectItemIndicator></span>
          </SelectItem>
        </SelectViewport>
      </SelectContent>
    </SelectPortal>
  </SelectRoot>
</template>
