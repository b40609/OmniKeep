<script setup lang="ts">
import { Download } from 'lucide-vue-next'
import SettingBlock from './SettingBlock.vue'
import SettingRow from './SettingRow.vue'
import FieldRow from './FieldRow.vue'
import SaveBar from './SaveBar.vue'
import { useUiStore } from '@/stores/ui'

/** 設定 › 資料與備份: where backups go and how often, and taking the collection out. */
const ui = useUiStore()
const BACKUP_KEYS = ['BACKUP_SINK', 'BACKUP_HOUR', 'BACKUP_KEEP', 'BACKUP_RCLONE_REMOTE', 'BACKUP_GIT_REPO_DIR']
</script>

<template>
  <SettingBlock id="backup" title="備份" description="每天自動備份一次資料庫。">
    <FieldRow field-key="BACKUP_SINK" />
    <FieldRow field-key="BACKUP_HOUR" />
    <FieldRow field-key="BACKUP_KEEP" />
    <FieldRow field-key="BACKUP_RCLONE_REMOTE" />
    <FieldRow field-key="BACKUP_GIT_REPO_DIR" />
    <template #foot><SaveBar :keys="BACKUP_KEYS" /></template>
  </SettingBlock>

  <SettingBlock id="export" title="匯出">
    <SettingRow name="匯出收藏" help="把收藏下載成 JSON 或 Markdown 檔，可以只匯出加星的。">
      <button type="button" class="set-button" @click="ui.openImport('export')"><Download aria-hidden="true" />開啟匯出</button>
    </SettingRow>
  </SettingBlock>
</template>
