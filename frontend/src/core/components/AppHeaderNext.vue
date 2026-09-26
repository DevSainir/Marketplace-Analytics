<script setup>
/**
 * Page chrome on the `ui-next` design system.
 *
 * The app's header. Same props and emits as the `AppHeader` it replaced, and
 * the same anatomy — mark, wordmark, nav links, workspace switcher, profile —
 * rendered as glass floating over the ambient ground rather than as a flat
 * canvas strip with a border under it.
 */
import { computed, nextTick, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'

import WorkspaceMenu from '@/core/components/WorkspaceMenu.vue'

const props = defineProps({
  isAuthenticated: { type: Boolean, default: false },
  // False while the session is still bootstrapping. The guest UI renders only
  // once auth RESOLVES as guest — otherwise a reload flashes «Войти» for the
  // fraction of a second the silent cookie-refresh takes.
  authResolved: { type: Boolean, default: false },
  userEmail: { type: String, default: null },
  workspaces: { type: Array, default: () => [] },
  currentWorkspaceId: { type: String, default: null },
  // Whether the viewer is one of us. Governs the links to surfaces built for a
  // single seller — see `require_internal` on the API side.
  internalFeatures: { type: Boolean, default: false },
  // Which sections this account may reach. A link to one it cannot is not a
  // shortcut, it is an invitation to a locked door.
  modules: { type: Array, default: () => [] },
})

const emit = defineEmits(['logout', 'select-workspace'])

const NAV = [
  { to: '/', label: 'Главная', exact: true },
  { to: '/monitoring', label: 'Мониторинг', module: 'monitoring' },
  // Both grants, like the route and the API behind it: the page shows
  // «Отчёты» money next to «Мониторинг» demand, so one grant alone must
  // not advertise it.
  { to: '/summary', label: 'Сводка', modules: ['monitoring', 'finreports'] },
  { to: '/finreports', label: 'P&L', module: 'finreports' },
  { to: '/ab-tests', label: 'A/Б-тесты', module: 'ab_tests' },
]

// Hiding the link is cosmetic — `installInternalGuard` is what actually
// refuses the route, and the API refuses it again. This only stops us
// advertising a section the person is then told does not exist.
const visibleNav = computed(() =>
  NAV.filter(
    (link) =>
      (!link.internal || props.internalFeatures) &&
      (!link.module || props.modules.includes(link.module)) &&
      (link.modules ?? []).every((key) => props.modules.includes(key)),
  ),
)

// On a phone the links outrun the pill and the nav scrolls sideways — which
// left the section you are IN off-screen at the right: on «P&L» the header
// showed «Главная · Мониторинг · Сво…». So the active link is scrolled into
// view whenever the route or the set of links changes. `inline: 'nearest'`
// moves nothing when it is already visible, which is always, on a desktop.
const nav = ref(null)
const route = useRoute()
watch(
  () => [route.path, visibleNav.value.length],
  async () => {
    await nextTick()
    nav.value
      ?.querySelector('.is-on')
      ?.scrollIntoView({ inline: 'nearest', block: 'nearest', behavior: 'instant' })
  },
  { immediate: true },
)
</script>

<template>
  <header class="ui-header">
    <!-- `.app-container` gives the pill the SAME width and gutters as the page
         content below it, so its edges line up with the cards instead of
         overhanging them. -->
    <div class="app-container">
      <div class="ui-header__inner ui-glass">
        <RouterLink to="/" class="ui-header__brand">
          <span class="ui-header__mark" aria-hidden="true">М</span>
          <span class="ui-header__word">
            Аналитика<span class="ui-header__qualifier"> · WB</span>
          </span>
        </RouterLink>

        <nav ref="nav" class="ui-header__nav" aria-label="Разделы">
          <RouterLink
            v-for="link in visibleNav"
            :key="link.to"
            :to="link.to"
            class="ui-header__link"
            :active-class="link.exact ? '' : 'is-on'"
            :exact-active-class="link.exact ? 'is-on' : ''"
          >
            {{ link.label }}
          </RouterLink>
        </nav>

        <div class="ui-header__right">
          <WorkspaceMenu
            v-if="isAuthenticated"
            class="ui-header__workspace"
            :workspaces="workspaces"
            :current-id="currentWorkspaceId"
            @select="emit('select-workspace', $event)"
          />

          <RouterLink
            v-if="isAuthenticated"
            to="/profile"
            class="ui-header__avatar"
            :title="userEmail || 'Профиль'"
            aria-label="Профиль"
          >
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="1.8"
              stroke-linecap="round"
              stroke-linejoin="round"
            >
              <path d="M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8ZM5 20a7 7 0 0 1 14 0" />
            </svg>
          </RouterLink>

          <RouterLink v-else-if="authResolved" to="/login" class="ui-header__login">
            Войти
          </RouterLink>

          <button
            v-if="isAuthenticated"
            type="button"
            class="ui-header__avatar"
            aria-label="Выйти"
            title="Выйти"
            @click="emit('logout')"
          >
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="1.8"
              stroke-linecap="round"
              stroke-linejoin="round"
            >
              <path d="M15 17l5-5-5-5M20 12H9M12 19H6a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h6" />
            </svg>
          </button>
        </div>
      </div>
    </div>
  </header>
</template>

<style scoped src="@/core/components/styles/AppHeaderNext.css"></style>
