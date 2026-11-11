<script setup lang="ts">
import { UserRound, Settings, Palette, Bell, KeyRound, FolderInput, Keyboard, LogOut, ChevronRight, Check } from 'lucide-vue-next'
import {
  DropdownMenuRoot, DropdownMenuTrigger, DropdownMenuPortal, DropdownMenuContent, DropdownMenuItem,
  DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuSub, DropdownMenuSubTrigger, DropdownMenuSubContent,
  DropdownMenuRadioGroup, DropdownMenuRadioItem, DropdownMenuItemIndicator,
} from 'reka-ui'
import { useUiStore } from '@/stores/ui'
import { useTheme, type AccentColor } from '@/composables/useTheme'
import { useMenuAction } from '@/composables/useMenuAction'
import { THEME_MODES, type ThemeMode } from '@/lib/themeMode'

/**
 * The avatar at the end of the top bar and the menu behind it: settings, theme,
 * sign-in to other platforms, import, shortcuts, sign-out. There is one user and
 * no account name, so the avatar is a neutral disc with a person in it.
 */
const emit = defineEmits<{ (e: 'logout'): void }>()

const ui = useUiStore()
const { mode, accent, accents, labels, set: setTheme, setAccent } = useTheme()
const appVersion = __APP_VERSION__
// Items open their dialog once the menu has closed (see useMenuAction).
const menu = useMenuAction()
</script>

<template>
  <DropdownMenuRoot>
    <DropdownMenuTrigger class="icon-button" aria-label="設定選單" title="設定">
      <span class="avatar"><UserRound aria-hidden="true" /></span>
    </DropdownMenuTrigger>
    <DropdownMenuPortal>
      <DropdownMenuContent class="app-menu" align="end" :side-offset="8" :collision-padding="12" @close-auto-focus="menu.flush">
        <DropdownMenuItem class="app-menu__item" @select="menu.defer(() => ui.openSettings())"><Settings aria-hidden="true" />設定</DropdownMenuItem>
        <DropdownMenuSub>
          <DropdownMenuSubTrigger class="app-menu__item">
            <Palette aria-hidden="true" />外觀主題
            <span class="app-menu__end">{{ labels[mode] }}<ChevronRight aria-hidden="true" /></span>
          </DropdownMenuSubTrigger>
          <DropdownMenuPortal>
            <DropdownMenuSubContent class="app-menu" :side-offset="10" :collision-padding="12">
              <DropdownMenuLabel class="app-menu__label">主題</DropdownMenuLabel>
              <!-- Choosing keeps the menu open, so themes can be tried one after another -->
              <DropdownMenuRadioGroup :model-value="mode" @update:model-value="setTheme($event as ThemeMode)">
                <DropdownMenuRadioItem v-for="option in THEME_MODES" :key="option" :value="option" class="app-menu__item" @select.prevent>
                  {{ labels[option] }}
                  <span class="app-menu__end"><DropdownMenuItemIndicator><Check aria-hidden="true" /></DropdownMenuItemIndicator></span>
                </DropdownMenuRadioItem>
              </DropdownMenuRadioGroup>
              <DropdownMenuSeparator class="app-menu__rule" />
              <DropdownMenuLabel class="app-menu__label">強調色</DropdownMenuLabel>
              <DropdownMenuRadioGroup :model-value="accent" @update:model-value="setAccent($event as AccentColor)">
                <DropdownMenuRadioItem v-for="opt in accents" :key="opt.id" :value="opt.id" class="app-menu__item" @select.prevent>
                  <span class="app-menu__swatch" :style="{ backgroundColor: opt.color }" aria-hidden="true" />{{ opt.label }}
                  <span class="app-menu__end"><DropdownMenuItemIndicator><Check aria-hidden="true" /></DropdownMenuItemIndicator></span>
                </DropdownMenuRadioItem>
              </DropdownMenuRadioGroup>
            </DropdownMenuSubContent>
          </DropdownMenuPortal>
        </DropdownMenuSub>
        <!-- From tablets up the bell in the top bar opens this; a phone has no room for the bell -->
        <DropdownMenuItem class="app-menu__item md:hidden" @select="menu.defer(() => (ui.showPushModal = true))"><Bell aria-hidden="true" />通知設定</DropdownMenuItem>
        <DropdownMenuItem class="app-menu__item" @select="menu.defer(() => (ui.showSessionModal = true))"><KeyRound aria-hidden="true" />社群平台登入</DropdownMenuItem>
        <DropdownMenuItem class="app-menu__item" @select="menu.defer(() => (ui.showImportModal = true))"><FolderInput aria-hidden="true" />匯入書籤</DropdownMenuItem>
        <DropdownMenuItem class="app-menu__item" @select="menu.defer(() => (ui.showShortcutsModal = true))"><Keyboard aria-hidden="true" />鍵盤快捷鍵</DropdownMenuItem>
        <DropdownMenuSeparator class="app-menu__rule" />
        <DropdownMenuItem class="app-menu__item" @select="emit('logout')"><LogOut aria-hidden="true" />登出</DropdownMenuItem>
        <DropdownMenuLabel class="app-menu__label">OmniKeep {{ appVersion }}</DropdownMenuLabel>
      </DropdownMenuContent>
    </DropdownMenuPortal>
  </DropdownMenuRoot>
</template>
