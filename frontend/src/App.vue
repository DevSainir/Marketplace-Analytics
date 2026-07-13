<script setup>
import { RouterView, useRouter } from 'vue-router'

import AppHeader from '@/core/components/AppHeader.vue'
import { useAuthStore } from '@/modules/auth'

const auth = useAuthStore()
const router = useRouter()

async function onLogout() {
  await auth.logout()
  router.push({ name: 'login' })
}
</script>

<template>
  <div class="flex min-h-screen flex-col">
    <AppHeader
      :is-authenticated="auth.isAuthenticated"
      :user-email="auth.userEmail"
      @logout="onLogout"
    />

    <main class="flex-1">
      <RouterView />
    </main>
  </div>
</template>
