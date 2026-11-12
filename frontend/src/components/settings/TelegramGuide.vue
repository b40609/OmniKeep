<script setup lang="ts">
import { ExternalLink } from 'lucide-vue-next'
import { TELEGRAM_DOC_URL, TELEGRAM_STEPS } from '@/lib/telegramGuide'

/** The three steps to connect Telegram; shown in 設定 › 收錄管道 and in the first-run guide. */
</script>

<template>
  <div class="set-guide">
    <ol class="set-guide__steps">
      <li v-for="(step, index) in TELEGRAM_STEPS" :key="step.title">
        <span class="set-guide__number" aria-hidden="true">{{ index + 1 }}</span>
        <div>
          <p class="set-guide__title">{{ step.title }}</p>
          <p class="set-guide__body">{{ step.body }}</p>
        </div>
      </li>
    </ol>
    <a :href="TELEGRAM_DOC_URL" target="_blank" rel="noopener noreferrer" class="set-link inline-flex items-center gap-1 text-sm">
      完整說明（docs/telegram_bot.md）<ExternalLink class="size-3.5" aria-hidden="true" />
    </a>
  </div>
</template>
