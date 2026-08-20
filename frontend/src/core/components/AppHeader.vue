<script setup>
/**
 * Global application header (dumb layout atom).
 *
 * Stays module-agnostic per architecture rules: it takes auth *state* as props
 * and emits intent upward — App.vue wires it to the auth store. The only local
 * state is the burger-menu open flag (pure UI concern).
 *
 * Layout: logo stub on the left; on the right the workspace switcher, a
 * profile-icon stub for signed-in users (login/register for guests) and a
 * burger menu that reveals the navigation plus the auth zone.
 */
import { ref } from 'vue'
import { RouterLink } from 'vue-router'

import WorkspaceMenu from '@/core/components/WorkspaceMenu.vue'

defineProps({
  isAuthenticated: { type: Boolean, default: false },
  // False while the session is still bootstrapping (auth status 'unknown'). The
  // guest UI («Войти») renders only once auth is RESOLVED as guest — otherwise a
  // full reload (e.g. a workspace switch) flashes «Войти» for the fraction of a
  // second the silent cookie-refresh takes to confirm the session.
  authResolved: { type: Boolean, default: false },
  userEmail: { type: String, default: null },
  workspaces: { type: Array, default: () => [] },
  currentWorkspaceId: { type: String, default: null },
})

const emit = defineEmits(['logout', 'select-workspace'])

const menuOpen = ref(false)

function closeMenu() {
  menuOpen.value = false
}

function toggleMenu() {
  menuOpen.value = !menuOpen.value
}

function onLogout() {
  closeMenu()
  emit('logout')
}

const navLinks = [
  { to: '/', label: 'Главная', exact: true },
  { to: '/monitoring', label: 'Мониторинг', exact: false },
  // One entry for finreports, pointing at the P&L: the логистика claim and the
  // cost-price editor are reached from the statement, where their numbers live.
  { to: '/finreports', label: 'Прибыли и убытки', exact: false },
  { to: '/ab-tests', label: 'A/Б-тесты', exact: false },
]
</script>

<template>
  <!-- Chrome sits on the SAME canvas as the page (see design_system.md
       «Page Chrome & Canvas») — one plane, only cards are surfaces. -->
  <!-- `pt-safe`: with viewport-fit=cover the sticky header starts at the very
       top of the display, so it pads itself past the Dynamic Island and its
       canvas fills that strip instead of leaving a black bar. -->
  <header class="sticky top-0 z-30 border-b border-border-subtle bg-canvas pt-safe">
    <!-- `.app-container` is the shared width + safe-area gutter (main.css), so
         chrome and page keep the same side margins on every route. -->
    <nav class="app-container flex h-14 items-center justify-between">
      <!-- Logo (stub) -->
      <RouterLink to="/" class="flex min-w-0 items-center gap-sm" @click="closeMenu">
        <span
          class="flex h-8 w-8 flex-none items-center justify-center rounded-btn bg-action text-h3 font-bold text-white"
          aria-hidden="true"
        >
          М
        </span>
        <span class="truncate text-h3 font-semibold tracking-tight text-primary">
          <!-- On a phone the right cluster (switcher + profile + burger) needs
               the room more than the qualifier does — the mark stays. -->
          Аналитика<span class="text-muted phone:hidden"> · WB</span>
        </span>
      </RouterLink>

      <!-- Right cluster: workspace switcher + profile link (auth) / login link
           (guest) + burger -->
      <div class="flex flex-none items-center gap-sm">
        <WorkspaceMenu
          v-if="isAuthenticated"
          :workspaces="workspaces"
          :current-id="currentWorkspaceId"
          @select="emit('select-workspace', $event)"
        />

        <RouterLink
          v-if="isAuthenticated"
          to="/profile"
          class="flex h-8 w-8 items-center justify-center rounded-full border border-border-subtle bg-canvas text-muted transition hover:border-action hover:text-action"
          :title="userEmail || 'Профиль'"
          aria-label="Профиль"
          @click="closeMenu"
        >
          <svg
            class="h-4 w-4"
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
        <RouterLink
          v-else-if="authResolved"
          to="/login"
          class="hidden rounded-btn px-md py-xs text-base font-medium text-action transition hover:bg-action/10 sm:inline-flex"
          @click="closeMenu"
        >
          Войти
        </RouterLink>

        <button
          type="button"
          class="flex h-8 w-8 items-center justify-center rounded-btn text-primary transition hover:bg-surface"
          :aria-expanded="menuOpen"
          aria-label="Меню"
          @click="toggleMenu"
        >
          <svg
            class="h-5 w-5"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="1.8"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <path v-if="!menuOpen" d="M4 6h16M4 12h16M4 18h16" />
            <path v-else d="M6 6l12 12M6 18L18 6" />
          </svg>
        </button>
      </div>
    </nav>

    <!-- Burger dropdown -->
    <Transition
      enter-active-class="transition duration-150 ease-out"
      enter-from-class="-translate-y-2 opacity-0"
      leave-active-class="transition duration-100 ease-in"
      leave-to-class="-translate-y-2 opacity-0"
    >
      <div v-if="menuOpen" class="border-t border-border-subtle bg-canvas">
        <div class="app-container py-md">
          <div class="flex flex-col gap-xs">
            <RouterLink
              v-for="link in navLinks"
              :key="link.to"
              :to="link.to"
              class="rounded-btn px-md py-sm text-base font-medium text-muted transition hover:bg-surface hover:text-primary phone:py-md"
              :active-class="link.exact ? '' : 'bg-surface text-primary'"
              :exact-active-class="link.exact ? 'bg-surface text-primary' : ''"
              @click="closeMenu"
            >
              {{ link.label }}
            </RouterLink>
          </div>

          <div class="mt-sm border-t border-border-subtle pt-sm">
            <template v-if="isAuthenticated">
              <p v-if="userEmail" class="truncate px-md text-tiny font-medium text-muted">
                {{ userEmail }}
              </p>
              <RouterLink
                to="/profile"
                class="mt-xs block rounded-btn px-md py-sm text-base font-medium text-muted transition hover:bg-surface hover:text-primary phone:py-md"
                active-class="bg-surface text-primary"
                @click="closeMenu"
              >
                Профиль
              </RouterLink>
              <button
                type="button"
                class="mt-xs w-full rounded-btn px-md py-sm text-left text-base font-medium text-status-negative transition hover:bg-status-negative/10 phone:py-md"
                @click="onLogout"
              >
                Выйти
              </button>
            </template>
            <div v-else-if="authResolved" class="flex flex-col gap-xs">
              <RouterLink
                to="/login"
                class="rounded-btn bg-action px-md py-sm text-center text-base font-semibold text-white transition hover:bg-action-hover"
                @click="closeMenu"
              >
                Войти
              </RouterLink>
              <RouterLink
                to="/login?mode=register"
                class="rounded-btn border border-border-subtle px-md py-sm text-center text-base font-medium text-primary transition hover:bg-surface"
                @click="closeMenu"
              >
                Регистрация
              </RouterLink>
            </div>
          </div>
        </div>
      </div>
    </Transition>
  </header>
</template>
