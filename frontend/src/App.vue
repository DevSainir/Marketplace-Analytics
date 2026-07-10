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
    <!-- Decorative gradient blobs: dynamic shapes for the glass cards'
         backdrop-blur to refract. Fixed behind all content (-z-10 paints
         above the propagated canvas background but under everything else). -->
    <div aria-hidden="true" class="pointer-events-none fixed inset-0 -z-10 overflow-hidden">
      <div
        class="absolute -top-32 right-[8%] h-[28rem] w-[28rem] rounded-full bg-action/10 blur-[120px]"
      ></div>
      <div
        class="absolute -bottom-32 left-[6%] h-[26rem] w-[26rem] rounded-full bg-status-positive/10 blur-[120px]"
      ></div>
    </div>

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
