<script setup lang="ts">
import { ref } from 'vue'
import { FolderInput } from 'lucide-vue-next'
import SettingBlock from './SettingBlock.vue'
import SettingRow from './SettingRow.vue'
import FieldRow from './FieldRow.vue'
import SaveBar from './SaveBar.vue'
import CheckButton from './CheckButton.vue'
import TelegramPairing from './TelegramPairing.vue'
import MobilePairing from './MobilePairing.vue'
import SessionPanel from './SessionPanel.vue'
import { useSettingsForm } from '@/composables/useSettingsForm'
import { useUiStore } from '@/stores/ui'

/** 設定 › 收錄管道: every way content gets in, and the sign-ins used to read it. */
const ui = useUiStore()
const form = useSettingsForm()
const telegram = ref<InstanceType<typeof TelegramPairing> | null>(null)

const TELEGRAM_KEYS = ['TELEGRAM_BOT_TOKEN', 'TELEGRAM_ALLOWED_USER_IDS']
const LINE_KEYS = ['LINE_CHANNEL_SECRET', 'LINE_CHANNEL_ACCESS_TOKEN', 'LINE_ALLOWED_USER_IDS']
const GITHUB_KEYS = ['GITHUB_TOKEN']

/** A pairing finished: show the new account, unless the block is being edited. */
function onTelegramRefreshed(boundIds: number[]) {
  const shown = form.byKey.value.get('TELEGRAM_ALLOWED_USER_IDS')?.value
  if (!form.changeCount(TELEGRAM_KEYS) && JSON.stringify(boundIds.map(String)) !== JSON.stringify(shown)) {
    void form.refreshKeys(TELEGRAM_KEYS)
  }
}
</script>

<template>
  <SettingBlock id="telegram" title="Telegram" description="把連結傳給你的 Telegram 機器人，就會收進來。">
    <FieldRow field-key="TELEGRAM_BOT_TOKEN" />
    <FieldRow field-key="TELEGRAM_ALLOWED_USER_IDS" placeholder="或手動輸入帳號編號">
      <template #ids><TelegramPairing ref="telegram" @refreshed="onTelegramRefreshed" /></template>
    </FieldRow>
    <template #foot>
      <SaveBar :keys="TELEGRAM_KEYS" @saved="telegram?.refresh()" />
      <CheckButton service="telegram" label="測試機器人" :keys="TELEGRAM_KEYS" />
    </template>
  </SettingBlock>

  <SettingBlock id="line" title="LINE" description="把連結傳給你的 LINE 官方帳號，就會收進來。">
    <FieldRow field-key="LINE_CHANNEL_SECRET" />
    <FieldRow field-key="LINE_CHANNEL_ACCESS_TOKEN" />
    <FieldRow field-key="LINE_ALLOWED_USER_IDS" placeholder="輸入 LINE User ID" />
    <template #foot>
      <SaveBar :keys="LINE_KEYS" />
      <CheckButton service="line" label="測試 LINE" :keys="LINE_KEYS" />
    </template>
  </SettingBlock>

  <MobilePairing />

  <SessionPanel />

  <SettingBlock id="import" title="匯入書籤">
    <SettingRow name="從瀏覽器或其他工具匯入" help="上傳書籤檔、貼上一批連結，或在書籤列放一顆收錄按鈕。">
      <button type="button" class="set-button" @click="ui.openImport('file')"><FolderInput aria-hidden="true" />開啟匯入</button>
    </SettingRow>
  </SettingBlock>

  <SettingBlock id="github" title="GitHub">
    <FieldRow field-key="GITHUB_TOKEN" />
    <template #foot>
      <SaveBar :keys="GITHUB_KEYS" />
      <CheckButton service="github" label="測試權杖" :keys="GITHUB_KEYS" />
    </template>
  </SettingBlock>
</template>
