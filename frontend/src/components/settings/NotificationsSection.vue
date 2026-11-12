<script setup lang="ts">
import PushPanel from './PushPanel.vue'
import SettingBlock from './SettingBlock.vue'
import SettingRow from './SettingRow.vue'
import FieldRow from './FieldRow.vue'
import SaveBar from './SaveBar.vue'
import { useUiStore } from '@/stores/ui'

/** 設定 › 通知: this device's push switch, and the contact address push services ask for. */
const ui = useUiStore()
const CONTACT_KEYS = ['VAPID_SUBJECT']
</script>

<template>
  <PushPanel />

  <SettingBlock id="telegram-notify" title="Telegram">
    <SettingRow name="傳到 Telegram" help="通知也會傳給已綁定的 Telegram 帳號，不受這台裝置的開關影響。">
      <button type="button" class="set-button" @click="ui.openSettings('channels', '', 'telegram')">管理綁定的帳號</button>
    </SettingRow>
  </SettingBlock>

  <SettingBlock id="contact" title="推播服務">
    <FieldRow field-key="VAPID_SUBJECT" placeholder="mailto:you@example.com" />
    <template #foot><SaveBar :keys="CONTACT_KEYS" /></template>
  </SettingBlock>
</template>
