<script setup>
/**
 * The profile, as a section rather than a page.
 *
 * **Why three routes.** An earlier version of this page stacked every block in
 * one 672px column and was right to have no navigation: four short blocks are
 * "a little over one screen tall", and splitting that would have bought navigation
 * and sold four near-empty screens. What changed is the content — a real
 * security section (the password, and every device this account is signed in
 * on) and a team page carrying the outstanding invitations and the access log.
 * Three screens under one scrollbar is a page you scroll past rather than one
 * you navigate.
 *
 * This shell owns only what all three share: the account identity, the rail,
 * and the one bootstrap. Each page owns its own data and its own drawers.
 */
import { computed, onMounted } from 'vue'
import { RouterLink, RouterView } from 'vue-router'

import ActivationKeyForm from '@/modules/profile/components/ActivationKeyForm.vue'

import ProfileNav from '@/modules/profile/components/ProfileNav.vue'
import { useMembersStore } from '@/modules/profile/membersStore'
import { useWorkspaceStore } from '@/modules/profile/store'

import '@/core/styles/ui-next/tokens.css'
import '@/core/styles/ui-next/components.css'
import '@/core/styles/ui-next/skin.css'
import '@/modules/profile/views/ProfileView.css'

const store = useWorkspaceStore()
const members = useMembersStore()

const ROLE_LABELS = {
  dev: 'Developer',
  owner: 'Owner',
  manager: 'Manager',
  user: 'No company',
}

const SECTIONS = [
  { name: 'profile', label: 'General' },
  { name: 'profile-team', label: 'Team' },
  { name: 'profile-security', label: 'Security' },
  { name: 'profile-guests', label: 'Access' },
]

/** Only the sections this account can actually be shown. */
const sections = computed(() =>
  SECTIONS.filter((section) => {
    if (section.name === 'profile-team') return members.canManageTeam
    // Opening another company's workspace is a platform decision; the API
    // refuses everyone but a dev (`DevAccess`).
    if (section.name === 'profile-guests') return members.role === 'dev'
    return true
  }),
)

const roleLabel = computed(() =>
  members.guestOnly ? 'Guest access' : (ROLE_LABELS[members.role] ?? ''),
)

onMounted(async () => {
  await store.ensureLoaded().catch(() => {})
  await members.ensureLoaded()
})
</script>

<template>
  <div class="app-container py-lg">
    <div class="pf-layout">
      <aside class="pf-aside">
        <ProfileNav
          :email="store.me?.email ?? ''"
          :role-label="roleLabel"
          :sections="sections"
          :subscription="members.subscription"
        />
      </aside>

      <main class="pf-main">
        <p v-if="store.error || members.error" class="pf-alert">
          {{ store.error || members.error }}
        </p>

        <!-- The only screen an account without a company can reach anything
             from, so it carries the way out rather than describing it. -->
        <section v-if="!members.hasOrganization && !members.guestOnly" class="pf-activation">
          <h2 class="pf-panel__title">Activation code</h2>
          <p class="pf-panel__note">
            The account has no company yet. Enter an activation code, or
            <RouterLink class="pf-link" :to="{ name: 'invite' }">accept an invitation</RouterLink>
            if a company owner sent you one.
          </p>
          <ActivationKeyForm align="left" />
        </section>

        <RouterView />
      </main>
    </div>
  </div>
</template>
