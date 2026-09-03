<script setup>
import { computed, watch } from 'vue'
import { RouterView, useRoute, useRouter } from 'vue-router'

import AppHeaderNext from '@/core/components/AppHeaderNext.vue'
import UiPage from '@/core/components/UiPage.vue'
import { useAuthStore } from '@/modules/auth'
import { ActivationGate, useMembersStore, useWorkspaceStore } from '@/modules/profile'

const auth = useAuthStore()
const workspace = useWorkspaceStore()
const members = useMembersStore()
const router = useRouter()
const route = useRoute()

// Which routes the activation overlay may cover. Everything behind the session
// except the profile page, which has to stay legible to somebody who has not
// been let into a company yet.
const gated = computed(
  () => Boolean(route.meta.requiresAuth) && !route.meta.allowWithoutOrganization,
)

// The header switcher needs the list on every authed route, not just the ones
// the workspace guard covers. `ensureLoaded` is idempotent, so this is cheap.
watch(
  () => auth.isAuthenticated,
  (authed) => {
    if (!authed) return
    workspace.ensureLoaded().catch(() => {
      // No list → the switcher hides itself; the profile page reports the error.
    })
    // Who this is decides whether the internal links are drawn at all. It
    // swallows its own errors and leaves the flag false, which is the right
    // way to fail: a link we do not draw costs us one navigation, a link a
    // customer sees costs us an explanation.
    members.ensureLoaded().catch(() => {})
  },
  { immediate: true },
)

async function onLogout() {
  await auth.logout()
  router.push({ name: 'login' })
}

function onSelectWorkspace(id) {
  if (id === workspace.currentWorkspaceId) return
  workspace.select(id) // persists the id (localStorage + X-Workspace-Id header)
  // Reload the CURRENT page, not a redirect to /monitoring: a full reload is the
  // simplest guarantee that every cached per-workspace dataset is dropped, and
  // reloading the same URL leaves the user where they were. The «Войти» flash
  // this used to show is fixed in the header (it no longer renders the guest
  // state while auth is still bootstrapping — see :auth-resolved).
  window.location.reload()
}
</script>

<template>
  <!-- `UiPage` is the design system's shell: it paints the ambient ground and
       gives the app its content layer. Every route sits inside it. -->
  <UiPage class="flex min-h-screen flex-col">
    <AppHeaderNext
      :is-authenticated="auth.isAuthenticated"
      :auth-resolved="auth.status !== 'unknown'"
      :user-email="auth.userEmail"
      :workspaces="workspace.workspaces"
      :current-workspace-id="workspace.currentWorkspaceId"
      :internal-features="members.internalFeatures"
      @logout="onLogout"
      @select-workspace="onSelectWorkspace"
    />

    <!-- `pb-safe` clears the home indicator once for every route, so no view
         has to end in a hand-rolled bottom spacer (see main.css). -->
    <main class="flex-1 pb-safe">
      <ActivationGate v-if="gated">
        <RouterView />
      </ActivationGate>
      <RouterView v-else />
    </main>
  </UiPage>
</template>
