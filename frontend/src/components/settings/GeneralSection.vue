<script setup lang="ts">
import { computed } from 'vue'
import Select from '@/components/ui/select/Select.vue'
import SettingBlock from './SettingBlock.vue'
import SettingRow from './SettingRow.vue'
import FieldRow from './FieldRow.vue'
import SaveBar from './SaveBar.vue'
import { useTheme, type AccentColor } from '@/composables/useTheme'
import { THEME_MODES, type ThemeMode } from '@/lib/themeMode'
import { useUiStore } from '@/stores/ui'

/** 設定 › 一般: how it looks (kept in this browser) and what the analysis knows about the owner. */
const { mode, accent, accents, labels, set: setTheme, setAccent } = useTheme()
const themeOptions = computed(() => THEME_MODES.map((value) => ({ value, label: labels[value] })))
const ui = useUiStore()
const openOptions = [{ value: 'full', label: '整頁閱讀' }, { value: 'side', label: '側邊預覽（清單留在旁邊）' }]
const sideOptions = [{ value: 'right', label: '畫面右邊' }, { value: 'left', label: '畫面左邊' }]
const PROFILE_KEYS = ['USER_BACKGROUND', 'LOCAL_HARDWARE']
</script>

<template>
  <SettingBlock id="appearance" title="外觀" description="只影響這個瀏覽器。">
    <SettingRow name="主題" help="整個介面的明暗。" for="setting-theme">
      <Select id="setting-theme" :model-value="mode" :options="themeOptions" @update:model-value="setTheme($event as ThemeMode)" />
    </SettingRow>
    <SettingRow name="點開文章" help="寬螢幕上點開一篇時怎麼顯示；閱讀畫面右上角的按鈕也能切換。手機一律整頁。" for="setting-reader-open">
      <Select id="setting-reader-open" :model-value="ui.readerOpen" :options="openOptions" @update:model-value="ui.readerOpen = $event as 'full' | 'side'" />
    </SettingRow>
    <SettingRow name="側邊預覽的位置" help="選「側邊預覽」時，閱讀面板開在畫面哪一邊，清單在另一邊。" for="setting-reader-side">
      <Select id="setting-reader-side" :model-value="ui.readerSide" :options="sideOptions" @update:model-value="ui.readerSide = $event as 'right' | 'left'" />
    </SettingRow>
    <SettingRow name="強調色" help="主要按鈕和目前所在位置的顏色。" stacked>
      <div class="flex flex-wrap gap-2" role="radiogroup" aria-label="強調色">
        <button
          v-for="option in accents"
          :key="option.id"
          type="button"
          class="set-swatch"
          role="radio"
          :aria-checked="accent === option.id"
          :aria-label="option.label"
          :title="option.label"
          @click="setAccent(option.id as AccentColor)"
        ><span :style="{ backgroundColor: option.color }" /></button>
      </div>
    </SettingRow>
  </SettingBlock>

  <SettingBlock id="analysis" title="分析">
    <FieldRow field-key="ANALYSIS_DEPTH" auto stacked />
  </SettingBlock>

  <SettingBlock id="profile" title="關於你" description="會寫進分析用的提示，和收藏內容一起送給你設定的 AI 連線。">
    <FieldRow field-key="USER_BACKGROUND" placeholder="例如：資料工程師，在做個人記帳 App" />
    <FieldRow field-key="LOCAL_HARDWARE" placeholder="例如：8 核心處理器、12GB 顯示卡、32GB 記憶體" />
    <template #foot><SaveBar :keys="PROFILE_KEYS" /></template>
  </SettingBlock>
</template>
