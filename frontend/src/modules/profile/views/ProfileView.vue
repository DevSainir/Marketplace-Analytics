<script setup>
/**
 * Profile page (smart view).
 *
 * Account identity, the workspace switcher (any user), and — for accounts
 * with the `dev` role — the workspace administration panel (create/delete
 * workspaces, WB tokens). All data flows through the workspace store;
 * components below are dumb (props in, events out).
 *
 * Switching a workspace hard-reloads into the monitoring view: per-workspace
 * caches (monitoring store) must not survive a tenancy switch.
 */
import { onMounted, reactive } from 'vue'
import { RouterLink } from 'vue-router'

import ActivationKeyForm from '@/modules/profile/components/ActivationKeyForm.vue'
import BackfillProgress from '@/modules/profile/components/BackfillProgress.vue'
import ManagerAccessPanel from '@/modules/profile/components/ManagerAccessPanel.vue'
import ManagerInviteForm from '@/modules/profile/components/ManagerInviteForm.vue'
import WorkspacesPanel from '@/modules/profile/components/WorkspacesPanel.vue'
import { useMembersStore } from '@/modules/profile/membersStore'
import { useWorkspaceStore } from '@/modules/profile/store'

const store = useWorkspaceStore()
const members = useMembersStore()

/** Lazily loaded token statuses per workspace id (dev panel). */
const tokenStatuses = reactive({})

onMounted(() => {
  store.ensureLoaded().catch(() => {
    // The store keeps the error message; the template renders it.
  })
  // Its own call, and its own failure: an owner whose members list does not
  // load should still get the rest of their profile.
  members.ensureLoaded()
})

async function onSaveAccess({ userId, grant }) {
  await members.saveAccess(userId, grant)
}

async function onInvite({ onIssued, ...payload }) {
  const invitation = await members.invite(payload)
  if (!invitation) return
  onIssued(invitation)
}

function onSelect(id) {
  if (id === store.currentWorkspaceId) return
  store.select(id) // persists the id (localStorage + X-Workspace-Id header)
  // Reload THIS page rather than redirecting to /monitoring. The reload is what
  // guarantees no per-workspace dataset survives the switch; the destination
  // was incidental, and sending everyone to Мониторинг put a manager who was
  // not granted it on «Раздел недоступен» for the crime of changing workspace.
  // The header switcher already worked this way — this copy was left behind.
  window.location.reload()
}

async function onExpand(id) {
  if (tokenStatuses[id]) return
  try {
    tokenStatuses[id] = await store.tokenStatus(id)
  } catch {
    // The panel shows «Не задан» placeholders; saving still works.
  }
}

async function onCreate(name) {
  await store.create(name)
}

async function onRemove(id) {
  await store.remove(id)
  delete tokenStatuses[id]
}

async function onSaveTokens({ workspaceId, tokens }) {
  const status = await store.saveTokens(workspaceId, tokens)
  if (status) tokenStatuses[workspaceId] = status
}
</script>

<template>
  <!-- `.app-container` is the shared canvas width + safe-area gutter (main.css). -->
  <div class="app-container py-lg">
    <div class="mx-auto flex w-full max-w-2xl flex-col gap-lg phone:gap-md">
      <!-- Account card -->
      <section class="rounded-card border border-border-subtle bg-surface p-lg shadow-card">
        <h1 class="text-h2 font-bold text-primary">Профиль</h1>
        <!-- Label opposite value reads well at desktop width; on a phone an
             email or a workspace name takes the whole line, so the pair stacks
             and the value is free to use it. -->
        <dl class="mt-md flex flex-col gap-sm phone:gap-md">
          <div
            class="flex items-center justify-between gap-md phone:flex-col phone:items-start phone:gap-0"
          >
            <dt class="text-tiny font-medium text-muted">Email</dt>
            <dd class="min-w-0 truncate text-base font-medium text-primary phone:w-full">
              {{ store.me?.email ?? '—' }}
            </dd>
          </div>
        </dl>
      </section>

      <!-- Directly under the account card, because it is the answer to the
           question a new seller is actually asking on this screen: the app is
           open, the data is not all here yet, and nothing is broken. It hides
           itself once every lane is done. -->
      <BackfillProgress v-if="store.currentWorkspaceId" :workspace-id="store.currentWorkspaceId" />

      <!-- Only while it is the thing standing between them and the app. Once an
           organisation exists the key is spent, and a form for redeeming
           another would invite people to try. -->
      <section
        v-if="!members.hasOrganization"
        class="rounded-card border border-border-subtle bg-surface p-lg shadow-card"
      >
        <h2 class="text-h2 font-bold text-primary">Ключ активации</h2>
        <p class="mt-xs text-tiny font-medium text-muted">
          Аккаунт ещё не привязан к компании. Введите ключ активации — или
          <RouterLink class="font-semibold text-action" :to="{ name: 'invite' }"
            >примите приглашение</RouterLink
          >, если владелец компании вам его прислал.
        </p>
        <ActivationKeyForm class="mt-md" align="left" />
      </section>

      <p
        v-if="store.error"
        class="rounded-card border border-status-negative/30 bg-status-negative/10 px-md py-sm text-base font-medium text-status-negative"
      >
        {{ store.error }}
      </p>

      <template v-if="members.isOwner">
        <ManagerAccessPanel
          :managers="members.managers"
          :saving="members.saving"
          @save="onSaveAccess"
          @remove="members.removeManager"
        />
        <ManagerInviteForm :saving="members.saving" @invite="onInvite" />
        <p
          v-if="members.error"
          class="rounded-card border border-status-negative/30 bg-status-negative/10 px-md py-sm text-base font-medium text-status-negative"
        >
          {{ members.error }}
        </p>
      </template>

      <!-- Rendered for everyone, because switching is everyone's; `can-manage`
           is what an owner has and a manager does not, matching `_owner_only`
           on create/delete/tokens. -->
      <WorkspacesPanel
        :workspaces="store.workspaces"
        :current-id="store.currentWorkspaceId"
        :token-statuses="tokenStatuses"
        :busy="store.loading"
        :can-manage="store.isDev || members.isOwner"
        @select="onSelect"
        @create="onCreate"
        @remove="onRemove"
        @expand="onExpand"
        @save-tokens="onSaveTokens"
      />
    </div>
  </div>
</template>
