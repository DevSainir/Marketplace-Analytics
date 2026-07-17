<script setup>
import { watch } from 'vue'
import { RouterView, useRouter } from 'vue-router'

import AppHeader from '@/core/components/AppHeader.vue'
import { useAuthStore } from '@/modules/auth'
import { useWorkspaceStore } from '@/modules/profile'

const auth = useAuthStore()
const workspace = useWorkspaceStore()
const router = useRouter()

// The header switcher needs the list on every authed route, not just the ones
// the workspace guard covers. `ensureLoaded` is idempotent, so this is cheap.
watch(
  () => auth.isAuthenticated,
  (authed) => {
    if (!authed) return
    workspace.ensureLoaded().catch(() => {
      // No list → the switcher hides itself; the profile page reports the error.
    })
  },
  { immediate: true },
)

async function onLogout() {
  await auth.logout()
  router.push({ name: 'login' })
}

function onSelectWorkspace(id) {
  if (id === workspace.currentWorkspaceId) return
  workspace.select(id)
  // Full reload: guarantees every cached per-workspace dataset is dropped.
  window.location.assign('/monitoring')
}
</script>

<template>
  <div class="flex min-h-screen flex-col">
    <AppHeader
      :is-authenticated="auth.isAuthenticated"
      :user-email="auth.userEmail"
      :workspaces="workspace.workspaces"
      :current-workspace-id="workspace.currentWorkspaceId"
      @logout="onLogout"
      @select-workspace="onSelectWorkspace"
    />

    <main class="flex-1">
      <RouterView />
    </main>
  </div>
</template>
