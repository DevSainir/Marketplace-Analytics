<script setup>
/**
 * «Общие» — what this account is, and the кабинеты it can look at.
 *
 * The facts strip replaces five stat tiles. A tile is for a number that moves
 * and that you came to read; a term ending in ten years and a count of two
 * кабинета are standing facts, checked once and then ignored, and four boxes
 * for four constants is a dashboard pretending something is happening.
 *
 * «Компания» is gone from it entirely: the name is the owner's email for every
 * organisation created by an activation code, and nobody outside this repo
 * knows what an «организация» is here. The role says the same thing usefully.
 * The term moved to the rail, where all three pages can see it.
 */
import { computed, onMounted, reactive, watch } from 'vue'

import AccountFacts from '@/modules/labs/components/profile/AccountFacts.vue'
import BackfillStrip from '@/modules/labs/components/profile/BackfillStrip.vue'
import ProfileWorkspaces from '@/modules/labs/components/profile/ProfileWorkspaces.vue'
import TokensDrawer from '@/modules/labs/components/profile/TokensDrawer.vue'
import { useLabTeam } from '@/modules/labs/labTeam'
import { useMembersStore, useWorkspaceStore } from '@/modules/profile'

const store = useWorkspaceStore()
const members = useMembersStore()
const team = useLabTeam()

const ROLE_LABELS = {
  dev: 'Разработчик',
  owner: 'Владелец',
  manager: 'Менеджер',
  user: 'Без компании',
}

/** Lazily loaded token statuses per кабинет id. */
const tokenStatuses = reactive({})

/** The кабинет whose tokens are open in the drawer, or null. */
const editing = reactive({ workspace: null })

const canManage = computed(() => store.isDev || members.isOwner)

/**
 * Token status for every кабинет at once, so the list can SAY which ones are
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

onMounted(loadTokenStatuses)
watch(() => store.workspaces.length, loadTokenStatuses)

async function onSaveTokens(tokens) {
  const status = await store.saveTokens(editing.workspace.id, tokens)
  if (status) tokenStatuses[editing.workspace.id] = status
}

function onSelect(id) {
  if (id === store.currentWorkspaceId) return
  store.select(id)
  // A reload is what guarantees no per-кабинет dataset survives the switch.
  window.location.reload()
}

async function onCreate(name) {
  await store.create(name)
}

async function onRemove(id) {
  await store.remove(id)
  delete tokenStatuses[id]
}
</script>

<template>
  <div class="lp-section">
    <AccountFacts
      :role-label="ROLE_LABELS[members.role] ?? '—'"
      :workspaces="store.workspaces.length"
      :managers="team.available.value ? team.managers.value.length : null"
    />

    <BackfillStrip v-if="store.currentWorkspaceId" :workspace-id="store.currentWorkspaceId" />

    <ProfileWorkspaces
      :workspaces="store.workspaces"
      :current-id="store.currentWorkspaceId"
      :token-statuses="tokenStatuses"
      :can-manage="canManage"
      :busy="store.loading"
      @create="onCreate"
      @select="onSelect"
      @tokens="(ws) => (editing.workspace = ws)"
      @remove="onRemove"
    />

    <TokensDrawer
      :workspace="editing.workspace"
      :configured="tokenStatuses[editing.workspace?.id]?.configured ?? []"
      :busy="store.loading"
      @close="editing.workspace = null"
      @save="onSaveTokens"
    />
  </div>
</template>
