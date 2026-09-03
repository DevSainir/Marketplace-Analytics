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
import ManagerAccessPanel from '@/modules/profile/components/ManagerAccessPanel.vue'
import ManagerInviteForm from '@/modules/profile/components/ManagerInviteForm.vue'
import WorkspaceAdminPanel from '@/modules/profile/components/WorkspaceAdminPanel.vue'
import WorkspaceSwitcher from '@/modules/profile/components/WorkspaceSwitcher.vue'
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
  store.select(id)
  // Full reload: guarantees every cached per-workspace dataset is dropped.
  window.location.assign('/monitoring')
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
          <div
            class="flex items-center justify-between gap-md phone:flex-col phone:items-start phone:gap-0"
          >
            <dt class="text-tiny font-medium text-muted">Активное пространство</dt>
            <dd class="min-w-0 truncate text-base font-medium text-primary phone:w-full">
              {{ store.currentWorkspace?.name ?? '—' }}
            </dd>
          </div>
        </dl>
      </section>

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

      <WorkspaceSwitcher
        :workspaces="store.workspaces"
        :current-id="store.currentWorkspaceId"
        @select="onSelect"
      />

      <template v-if="members.isOwner">
        <ManagerAccessPanel
          :managers="members.managers"
          :saving="members.saving"
          @save="onSaveAccess"
        />
        <ManagerInviteForm :saving="members.saving" @invite="onInvite" />
        <p
          v-if="members.error"
          class="rounded-card border border-status-negative/30 bg-status-negative/10 px-md py-sm text-base font-medium text-status-negative"
        >
          {{ members.error }}
        </p>
      </template>

      <!-- Owners too, not just devs: `POST /v1/workspaces` is `_owner_only` and
           has been the whole time, so gating the only UI for it on the platform
           dev role left owners with no way to add one. -->
      <WorkspaceAdminPanel
        v-if="store.isDev || members.isOwner"
        :workspaces="store.workspaces"
        :token-statuses="tokenStatuses"
        :busy="store.loading"
        @create="onCreate"
        @remove="onRemove"
        @expand="onExpand"
        @save-tokens="onSaveTokens"
      />
    </div>
  </div>
</template>
