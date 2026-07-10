<script setup>
/**
 * Global application header (dumb layout atom).
 *
 * Stays module-agnostic per architecture rules: it takes auth *state* as props
 * and emits intent upward — App.vue wires it to the auth store. The only local
 * state is the burger-menu open flag (pure UI concern).
 *
 * Layout: logo stub on the left; on the right a burger menu that reveals the
 * navigation plus the auth zone — login/register for guests, a profile-icon
 * stub for signed-in users.
 */
import { ref } from 'vue'
import { RouterLink } from 'vue-router'

defineProps({
  isAuthenticated: { type: Boolean, default: false },
  userEmail: { type: String, default: null },
})

const emit = defineEmits(['logout'])

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
]
</script>

<template>
  <header class="sticky top-0 z-30 border-b border-border-subtle bg-surface/90 backdrop-blur">
    <nav class="mx-auto flex h-14 w-full max-w-7xl items-center justify-between px-md sm:px-lg">
      <!-- Logo (stub) -->
      <RouterLink to="/" class="flex items-center gap-sm" @click="closeMenu">
        <span
          class="flex h-8 w-8 items-center justify-center rounded-btn bg-action text-h3 font-bold text-white"
          aria-hidden="true"
        >
          М
        </span>
        <span class="text-h3 font-semibold tracking-tight text-primary">
          Аналитика<span class="text-muted"> · WB</span>
        </span>
      </RouterLink>

      <!-- Right cluster: profile-icon stub (auth) / login link (guest) + burger -->
      <div class="flex items-center gap-sm">
        <span
          v-if="isAuthenticated"
          class="flex h-8 w-8 items-center justify-center rounded-full border border-border-subtle bg-canvas text-muted"
          :title="userEmail || 'Профиль'"
          aria-hidden="true"
        >
          <!-- profile icon (stub) -->
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
        </span>
        <RouterLink
          v-else
          to="/login"
          class="hidden rounded-btn px-md py-xs text-base font-medium text-action transition hover:bg-action/10 sm:inline-flex"
          @click="closeMenu"
        >
          Войти
        </RouterLink>

        <button
          type="button"
          class="flex h-8 w-8 items-center justify-center rounded-btn text-primary transition hover:bg-canvas"
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
      <div v-if="menuOpen" class="border-t border-border-subtle bg-surface">
        <div class="mx-auto w-full max-w-7xl px-md py-md sm:px-lg">
          <div class="flex flex-col gap-xs">
            <RouterLink
              v-for="link in navLinks"
              :key="link.to"
              :to="link.to"
              class="rounded-btn px-md py-sm text-base font-medium text-muted transition hover:bg-canvas hover:text-primary"
              :active-class="link.exact ? '' : 'bg-canvas text-primary'"
              :exact-active-class="link.exact ? 'bg-canvas text-primary' : ''"
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
              <button
                type="button"
                class="mt-xs w-full rounded-btn px-md py-sm text-left text-base font-medium text-status-negative transition hover:bg-status-negative/10"
                @click="onLogout"
              >
                Выйти
              </button>
            </template>
            <div v-else class="flex flex-col gap-xs">
              <RouterLink
                to="/login"
                class="rounded-btn bg-action px-md py-sm text-center text-base font-semibold text-white transition hover:bg-action-hover"
                @click="closeMenu"
              >
                Войти
              </RouterLink>
              <RouterLink
                to="/login?mode=register"
                class="rounded-btn border border-border-subtle px-md py-sm text-center text-base font-medium text-primary transition hover:bg-canvas"
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
