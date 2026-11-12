<script setup lang="ts">
/** A titled group of setting rows. `id` is what a settings link scrolls to. */
defineProps<{ id?: string; title: string; description?: string }>()
</script>

<template>
  <section :id="id ? `settings-${id}` : undefined" class="set-block">
    <h3 class="set-block__title">{{ title }}</h3>
    <p v-if="description" class="set-block__desc">{{ description }}</p>
    <slot name="above" />
    <div class="set-block__rows"><slot /></div>
    <div v-if="$slots.foot" class="set-block__foot"><slot name="foot" /></div>
  </section>
</template>
