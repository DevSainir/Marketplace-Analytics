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

import WorkspaceAdminPanel from '@/modules/profile/components/WorkspaceAdminPanel.vue'
import WorkspaceSwitcher from '@/modules/profile/components/WorkspaceSwitcher.vue'
import { useWorkspaceStore } from '@/modules/profile/store'

const store = useWorkspaceStore()

/** Lazily loaded token statuses per workspace id (dev panel). */
const tokenStatuses = reactive({})

onMounted(() => {
  store.ensureLoaded().catch(() => {
    // The store keeps the error message; the template renders it.
  })
})

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
            class="flex items-center justify-between gap-md phone:flex-col phone:items-start phone:gap-xs"
          >
            <dt class="text-tiny font-medium text-muted">Роль</dt>
            <dd>
              <span
                class="rounded-btn px-sm py-xs text-tiny font-semibold"
                :class="
                  store.isDev
                    ? 'bg-accent-indigo/10 text-accent-indigo'
                    : 'bg-action/10 text-action'
                "
              >
                {{ store.me?.role ?? '—' }}
              </span>
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

      <WorkspaceAdminPanel
        v-if="store.isDev"
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
