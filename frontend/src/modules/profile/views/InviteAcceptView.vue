<script setup>
/**
 * Joining a company with an invitation.
 *
 * This screen did not exist, which made the whole invite feature a dead end:
 * an owner could issue an invitation and the profile page showed them the
 * token under the words "The link is shown once", but it was not a link
 * and there was nowhere for the person receiving it to put it. The API had
 * `/invitations/accept` all along, and its request schema even calls this
 * "the link flow" — the link just had no page to land on.
 *
 * It is now `/invite?token=…`, so following the link accepts on arrival; the
 * token can also be pasted, for anyone who was sent the bare value or whose
 * mail client mangled the URL.
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { useMembersStore } from '@/modules/profile/membersStore'

const members = useMembersStore()
const route = useRoute()
const router = useRouter()

const token = ref(typeof route.query.token === 'string' ? route.query.token : '')
const joined = ref(false)

// Shown when the invitation was addressed to this account: it names the
// company, so the person can tell an expected invitation from a stray link.
const waiting = computed(() => members.invitations[0] ?? null)

async function submit() {
  if (!token.value.trim() || members.saving === 'invitation') return
  joined.value = await members.acceptInvite(token.value.trim())
}

onMounted(async () => {
  await members.ensureLoaded().catch(() => {})
  // A token in the URL means the person followed the link. Redeem it without
  // making them press a second button for something they already chose.
  if (token.value && !members.hasOrganization) await submit()
})
</script>

<template>
  <div class="app-container py-16 phone:py-lg sm:py-24">
    <div class="mx-auto flex w-full max-w-md flex-col">
      <header class="text-center">
        <h1 class="text-h2 font-bold tracking-tight text-primary">
          {{ joined ? "You're in the company" : 'Invitation' }}
        </h1>
        <p class="mt-xs text-tiny font-medium text-muted">
          <template v-if="joined">Access is open. You can start working.</template>
          <template v-else-if="waiting">
            You're invited to {{ waiting.organization_name ?? 'a company' }}.
          </template>
          <template v-else> Paste the invitation code the company owner sent you. </template>
        </p>
      </header>

      <section class="mt-lg rounded-card border border-border-subtle bg-surface p-lg shadow-card">
        <button
          v-if="joined"
          type="button"
          class="ui-btn ui-btn--primary w-full"
          @click="router.push('/')"
        >
          Home
        </button>

        <!-- Already a member: accepting a second invitation is refused by the
             API (409), so the screen says so instead of offering the attempt. -->
        <p v-else-if="members.hasOrganization" class="text-center text-base text-muted">
          This account already belongs to a company.
        </p>

        <form v-else class="flex flex-col gap-sm" @submit.prevent="submit">
          <label class="block">
            <span class="mb-xs block text-tiny font-medium text-muted">Invitation code</span>
            <input
              v-model="token"
              type="text"
              required
              autocomplete="off"
              spellcheck="false"
              class="ui-input w-full"
            />
          </label>

          <p v-if="members.error" class="invite-error">{{ members.error }}</p>

          <button
            type="submit"
            :disabled="members.saving === 'invitation' || !token.trim()"
            class="ui-btn ui-btn--primary w-full"
          >
            {{ members.saving === 'invitation' ? 'Checking…' : 'Accept invitation' }}
          </button>
        </form>
      </section>
    </div>
  </div>
</template>

<style scoped>
.invite-error {
  @apply rounded-input border px-md py-sm text-tiny font-medium;
  border-color: color-mix(in srgb, var(--ui-neg) 30%, transparent);
  background-color: color-mix(in srgb, var(--ui-neg) 10%, transparent);
  color: var(--ui-neg);
}
</style>
