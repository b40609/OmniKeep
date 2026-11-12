<script setup lang="ts">
import AiConnections from './AiConnections.vue'
import SettingBlock from './SettingBlock.vue'
import FieldRow from './FieldRow.vue'
import SaveBar from './SaveBar.vue'
import CheckButton from './CheckButton.vue'

/** 設定 › AI: the connections and task lists, and how questions are answered. */
const ASK_KEYS = ['BRAIN_PROVIDER', 'BRAIN_BASE_URL', 'BRAIN_MODEL', 'BRAIN_MAX_CITATIONS', 'BRAIN_NUM_CTX']
</script>

<template>
  <AiConnections />

  <SettingBlock id="ask" title="提問" description="用收藏的內容回答你的問題，並附上引用的收藏。">
    <FieldRow field-key="BRAIN_PROVIDER" stacked />
    <FieldRow field-key="BRAIN_BASE_URL" />
    <FieldRow field-key="BRAIN_MODEL" placeholder="例如 qwen3:8b" />
    <FieldRow field-key="BRAIN_MAX_CITATIONS" />
    <FieldRow field-key="BRAIN_NUM_CTX" />
    <template #foot>
      <SaveBar :keys="ASK_KEYS" />
      <CheckButton service="brain" label="測試本機模型" :keys="ASK_KEYS" />
    </template>
  </SettingBlock>
</template>
