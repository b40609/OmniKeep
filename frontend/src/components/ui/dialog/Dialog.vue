<script setup lang="ts">
import { DialogRoot, type DialogRootEmits, type DialogRootProps } from 'reka-ui'

// Preserve Reka UI's modal & unmountOnHide defaults (Vue coerces omitted boolean props to false otherwise).
const props = withDefaults(defineProps<DialogRootProps>(), {
  modal: true,
  unmountOnHide: true,
})
const emits = defineEmits<DialogRootEmits>()
</script>

<template>
  <DialogRoot v-bind="props" @update:open="emits('update:open', $event)">
    <slot />
  </DialogRoot>
</template>
