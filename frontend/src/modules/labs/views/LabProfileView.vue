<script setup>
/**
 * DESIGN SANDBOX — /profile, relaid out.
 *
 * Unlike the monitoring sandbox this one runs on REAL data: the same stores,
 * the same endpoints, the same writes. Only the layout is new, so what you are
 * comparing is the layout.
 *
 * Two things the old page got wrong, and what replaced them:
 *
 *  1. It used a 672px column on a 1280px canvas. Everything was as narrow as a
 *     form because one thing on it was a form. Here a sticky rail holds the
 *     identity, the term and the section list, and the content takes the rest —
 *     lists get the width they need, editors get a drawer.
 *  2. Its blocks were ordered by who could see them, not by what they are
 *     about. Four sections now: who you are, who else is in the company, which
 *     WB accounts you are looking at, and what you can do to your own access.
 *
 * Deliberately NOT four routes. There is not enough on this page to fill four
 * screens, and anchors cost nothing.
 */
import { computed, onMounted, reactive, ref, watch } from 'vue'

import { useAuthStore } from '@/modules/auth'
import BackfillStrip from '@/modules/labs/components/profile/BackfillStrip.vue'
import ProfileDrawers from '@/modules/labs/components/profile/ProfileDrawers.vue'
import ProfileOverview from '@/modules/labs/components/profile/ProfileOverview.vue'
import ProfileRail from '@/modules/labs/components/profile/ProfileRail.vue'
import ProfileSecurity from '@/modules/labs/components/profile/ProfileSecurity.vue'
import ProfileTeam from '@/modules/labs/components/profile/ProfileTeam.vue'
import ProfileWorkspaces from '@/modules/labs/components/profile/ProfileWorkspaces.vue'
import { useLabTeam } from '@/modules/labs/labTeam'
import { revokeAllSessions } from '@/modules/labs/profileApi'
import { useMembersStore, useWorkspaceStore } from '@/modules/profile'

import '@/core/styles/ui-next/tokens.css'
import '@/core/styles/ui-next/components.css'
import '@/core/styles/ui-next/skin.css'
import '@/modules/labs/views/LabProfileView.css'

const store = useWorkspaceStore()
const members = useMembersStore()
const auth = useAuthStore()
// The roster comes from here, not from `members`: that store asks for it only
// for an effective role of exactly `owner`, which a dev account never has.
const team = useLabTeam()

const ROLE_LABELS = {
  dev: 'Разработчик',
  owner: 'Владелец',
  manager: 'Менеджер',
  user: 'Без компании',
}

/** Lazily loaded token statuses per workspace id. */
const tokenStatuses = reactive({})

/** `{ kind: 'invite' | 'access' | 'tokens', ... }` or null. */
const drawer = ref(null)
const securityBusy = ref(null)
const codeSent = ref(false)

const canManage = computed(() => store.isDev || members.isOwner)

const sections = computed(() =>
  [
    { id: 'lp-overview', label: 'Обзор' },
    team.available.value
      ? { id: 'lp-team', label: 'Команда', count: team.managers.value.length }
      : null,
    { id: 'lp-workspaces', label: 'Кабинеты', count: store.workspaces.length },
    { id: 'lp-security', label: 'Безопасность' },
  ].filter(Boolean),
)

/**
 * Token status for every workspace at once, so the list can SAY which ones are
 * wired up. The old page asked one at a time, on expand, which is why the list
 * could not answer the question the list is for.
 */
async function loadTokenStatuses() {
  if (!canManage.value) return
  await Promise.all(
    store.workspaces.map(async (ws) => {
      if (tokenStatuses[ws.id]) return
      try {
        tokenStatuses[ws.id] = await store.tokenStatus(ws.id)
      } catch {
        // The row shows «…» and the drawer still works.
      }
    }),
  )
}

onMounted(async () => {
  await store.ensureLoaded().catch(() => {})
  await members.ensureLoaded()
  await Promise.all([team.load(), loadTokenStatuses()])
})

watch(() => store.workspaces.length, loadTokenStatuses)

async function saveAccess(grant) {
  const ok = await team.saveAccess(drawer.value.manager.user_id, grant)
  if (ok) drawer.value = null
}

async function onInvite({ onIssued, ...payload }) {
  const invitation = await team.invite(payload)
  if (invitation) onIssued(invitation)
}

async function onSaveTokens(tokens) {
  const status = await store.saveTokens(drawer.value.workspace.id, tokens)
  if (status) tokenStatuses[drawer.value.workspace.id] = status
}

function onSelect(id) {
  if (id === store.currentWorkspaceId) return
  store.select(id)
  // A reload is what guarantees no per-workspace dataset survives the switch.
  window.location.reload()
}

async function onCreate(name) {
  await store.create(name)
}

async function onRemoveWorkspace(id) {
  await store.remove(id)
  delete tokenStatuses[id]
}

async function onChangePassword() {
  securityBusy.value = 'password'
  codeSent.value = await auth.askForPasswordReset(store.me?.email ?? '')
  securityBusy.value = null
}

async function onRevokeSessions() {
  securityBusy.value = 'sessions'
  try {
    await revokeAllSessions()
  } finally {
    securityBusy.value = null
  }
  // The server has ended this session too; drop it locally rather than let the
  // SPA keep talking to a server that has stopped honouring it.
  auth.markGuest()
  window.location.assign('/login')
}
</script>

<template>
  <div class="app-container py-lg">
    <div class="lp-layout">
      <aside class="lp-aside">
        <ProfileRail
          :email="store.me?.email ?? ''"
          :role-label="ROLE_LABELS[members.role] ?? ''"
          :org-name="members.organization?.name ?? ''"
          :subscription="members.subscription"
          :sections="sections"
        />
      </aside>

      <main class="lp-main">
        <p v-if="store.error || members.error || team.error.value" class="lp-alert">
          {{ store.error || members.error || team.error.value }}
        </p>

        <section v-if="!members.hasOrganization" class="lp-alert lp-alert--soft">
          Аккаунт ещё не привязан к компании. Ключ активации вводится на обычной странице профиля —
          этот макет только показывает раскладку.
        </section>

        <section id="lp-overview" class="lp-section">
          <h1 class="lp-panel__title">Профиль</h1>
          <ProfileOverview
            :org-name="members.organization?.name ?? ''"
            :is-primary-org="Boolean(members.organization?.is_primary)"
            :role-label="ROLE_LABELS[members.role] ?? '—'"
            :workspaces="store.workspaces.length"
            :max-workspaces="members.subscription?.max_workspaces ?? null"
            :managers="team.available.value ? team.managers.value.length : null"
            :max-managers="members.subscription?.max_managers ?? null"
            :modules="members.modules"
            :subscription="members.subscription"
          />
          <BackfillStrip v-if="store.currentWorkspaceId" :workspace-id="store.currentWorkspaceId" />
        </section>

        <section v-if="team.available.value" id="lp-team" class="lp-section">
          <ProfileTeam
            :managers="team.managers.value"
            :saving="team.saving.value"
            can-invite
            @invite="drawer = { kind: 'invite' }"
            @edit="(manager) => (drawer = { kind: 'access', manager })"
            @remove="team.remove"
          />
        </section>

        <section id="lp-workspaces" class="lp-section">
          <ProfileWorkspaces
            :workspaces="store.workspaces"
            :current-id="store.currentWorkspaceId"
            :token-statuses="tokenStatuses"
            :can-manage="canManage"
            :busy="store.loading"
            @create="onCreate"
            @select="onSelect"
            @tokens="(ws) => (drawer = { kind: 'tokens', workspace: ws })"
            @remove="onRemoveWorkspace"
          />
        </section>

        <section id="lp-security" class="lp-section">
          <h2 class="lp-panel__title">Безопасность</h2>
          <ProfileSecurity
            :email="store.me?.email ?? ''"
            :busy="securityBusy"
            :code-sent="codeSent"
            @change-password="onChangePassword"
            @revoke-sessions="onRevokeSessions"
          />
        </section>
      </main>
    </div>

    <ProfileDrawers
      :drawer="drawer"
      :member-saving="team.saving.value"
      :store-busy="store.loading"
      :token-statuses="tokenStatuses"
      @close="drawer = null"
      @invite="onInvite"
      @save-access="saveAccess"
      @save-tokens="onSaveTokens"
    />
  </div>
</template>
