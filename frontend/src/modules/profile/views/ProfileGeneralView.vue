<script setup>
/**
 * "General" — what this account is, and the workspaces it can look at.
 *
 * The facts strip replaces five stat tiles. A tile is for a number that moves
 * and that you came to read; a term ending in ten years and a count of two
 * workspaces are standing facts, checked once and then ignored, and four boxes
 * for four constants is a dashboard pretending something is happening.
 *
 * "Company" is gone from it entirely: the name is the owner's email for every
 * organisation created by an activation code, and nobody outside this repo
 * knows what an "organisation" is here. The role says the same thing usefully.
 * The term moved to the rail, where all three pages can see it.
 */
import { computed, onMounted, reactive, ref, watch } from 'vue'

import AccountFacts from '@/modules/profile/components/AccountFacts.vue'
import ActivationCodesPanel from '@/modules/profile/components/ActivationCodesPanel.vue'
import BackfillStrip from '@/modules/profile/components/BackfillStrip.vue'
import ProfileWorkspaces from '@/modules/profile/components/ProfileWorkspaces.vue'
import TokensDrawer from '@/modules/profile/components/TokensDrawer.vue'
import { useMembersStore } from '@/modules/profile/membersStore'
import { useWorkspaceStore } from '@/modules/profile/store'

const store = useWorkspaceStore()
const members = useMembersStore()

const ROLE_LABELS = {
  dev: 'Developer',
  owner: 'Owner',
  manager: 'Manager',
  user: 'No company',
}

/** Lazily loaded token statuses per workspace id. */
const tokenStatuses = reactive({})

/** The workspace whose tokens are open in the drawer, or null. */
const editing = reactive({ workspace: null })

const canManage = computed(() => store.isDev || members.isOwner)

/**
 * The workspaces this organisation owns. A head also sees other companies'
 * workspaces opened to them read-only (`is_guest`); those are in the switcher,
 * never here — their tokens, backfill and deletion belong to their owner.
 */
const ownWorkspaces = computed(() => store.workspaces.filter((ws) => !ws.is_guest))

/**
 * Token status for every workspace at once, so the list can SAY which ones are
 * wired up. The old page asked one at a time, on expand, which is why the list
 * could not answer the question the list is for.
 */
async function loadTokenStatuses() {
  if (!canManage.value) return
  await Promise.all(
    ownWorkspaces.value.map(async (ws) => {
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
watch(() => ownWorkspaces.value.length, loadTokenStatuses)

async function onSaveTokens(tokens) {
  const status = await store.saveTokens(editing.workspace.id, tokens)
  if (status) tokenStatuses[editing.workspace.id] = status
}

function onSelect(id) {
  if (id === store.currentWorkspaceId) return
  store.select(id)
  // A reload is what guarantees no per-workspace dataset survives the switch.
  window.location.reload()
}

/** A workspace is being created — its own flag, so "Creating…" never shows on a delete. */
const creating = ref(false)

async function onCreate(name) {
  creating.value = true
  try {
    await store.create(name)
  } finally {
    creating.value = false
  }
}

async function onRemove(id) {
  await store.remove(id)
  delete tokenStatuses[id]
}
</script>

<template>
  <div class="pf-section">
    <AccountFacts
      :role-label="ROLE_LABELS[members.role] ?? '—'"
      :workspaces="ownWorkspaces.length"
      :managers="members.canManageTeam ? members.managers.length : null"
    />

    <BackfillStrip
      v-if="store.currentWorkspaceId && !store.currentWorkspace?.is_guest"
      :workspace-id="store.currentWorkspaceId"
    />

    <ActivationCodesPanel v-if="members.canIssueCodes" />

    <ProfileWorkspaces
      :workspaces="ownWorkspaces"
      :current-id="store.currentWorkspaceId"
      :token-statuses="tokenStatuses"
      :can-manage="canManage"
      :busy="store.loading"
      :creating="creating"
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
