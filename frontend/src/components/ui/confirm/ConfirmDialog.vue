<script setup lang="ts">
import {
  AlertDialogRoot, AlertDialogPortal, AlertDialogOverlay, AlertDialogContent, AlertDialogTitle,
  AlertDialogDescription, AlertDialogCancel,
} from 'reka-ui'

/**
 * Asks before something that cannot be taken back. The confirm button names the
 * action itself ("刪除連線"), never "確定". Extra content goes in the default slot.
 */
withDefaults(
  defineProps<{
    open: boolean
    title: string
    description?: string
    confirmLabel: string
    cancelLabel?: string
    /** A destructive action: the confirm button is filled with the danger colour. */
    danger?: boolean
    busy?: boolean
  }>(),
  { description: '', cancelLabel: '取消', danger: false, busy: false },
)
const emit = defineEmits<{ (e: 'update:open', value: boolean): void; (e: 'confirm'): void }>()
</script>

<template>
  <AlertDialogRoot :open="open" @update:open="emit('update:open', $event)">
    <AlertDialogPortal>
      <AlertDialogOverlay class="ui-confirm__overlay" />
      <AlertDialogContent class="ui-confirm">
        <AlertDialogTitle class="ui-confirm__title">{{ title }}</AlertDialogTitle>
        <AlertDialogDescription class="ui-confirm__text">{{ description }}</AlertDialogDescription>
        <slot />
        <div class="ui-confirm__actions">
          <AlertDialogCancel class="set-button">{{ cancelLabel }}</AlertDialogCancel>
          <!-- A plain button: the caller closes the dialog once the action has gone through. -->
          <button
            type="button"
            class="set-button"
            :class="danger ? 'set-button--danger-solid' : 'set-button--primary'"
            :disabled="busy"
            @click="emit('confirm')"
          >{{ confirmLabel }}</button>
        </div>
      </AlertDialogContent>
    </AlertDialogPortal>
  </AlertDialogRoot>
</template>
