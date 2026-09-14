<script setup>
/**
 * «Команда» — who is in the company, what they may reach, and how they got in.
 *
 * The roster on its own is a thin page: most companies here have two or three
 * managers, and a three-row table is not a screen. What fills it is the rest of
 * the same question, and both halves already existed in the API with nothing
 * rendering them:
 *
 *  - **Приглашения.** Issuing one showed its link once and then forgot it, so
 *    a link handed to the wrong person was untrackable and unrevokable from the
 *    product — and an invitation is a door standing open until it expires.
 *  - **Журнал доступа.** The audit rows have been written since the trail was
 *    built and read only over psql. «Кто убрал этого менеджера» is the question
 *    an owner actually asks, and until now the product could not answer it.
 *
 * They also order themselves: the roster is who is in, invitations are who is
 * on the way in, the log is who went in or out already.
 */
import { onMounted, ref } from 'vue'

import AccessLog from '@/modules/labs/components/profile/AccessLog.vue'
import InvitationList from '@/modules/labs/components/profile/InvitationList.vue'
import ProfileTeam from '@/modules/labs/components/profile/ProfileTeam.vue'
import TeamDrawers from '@/modules/labs/components/profile/TeamDrawers.vue'
import { useLabTeam } from '@/modules/labs/labTeam'
import { fetchAuditLog, fetchInvitations, revokeInvitation } from '@/modules/labs/profileApi'

const team = useLabTeam()

/** `{ kind: 'invite' | 'access', manager? }` or null. */
const drawer = ref(null)

const invitations = ref([])
const revoking = ref(null)

const auditEntries = ref([])
const auditLoading = ref(true)

async function loadInvitations() {
  try {
    invitations.value = await fetchInvitations()
  } catch {
    // Owner-only, like the roster. An account the API refuses simply gets no
    // list; the page above it still works.
    invitations.value = []
  }
}

async function loadAudit() {
  auditLoading.value = true
  try {
    auditEntries.value = await fetchAuditLog(20)
  } catch {
    auditEntries.value = []
  } finally {
    auditLoading.value = false
  }
}

onMounted(async () => {
  await team.load()
  await Promise.all([loadInvitations(), loadAudit()])
})

async function onInvite({ onIssued, ...payload }) {
  const invitation = await team.invite(payload)
  if (!invitation) return
  onIssued(invitation)
  // The new link belongs in the list below, and issuing one is an audited act.
  await Promise.all([loadInvitations(), loadAudit()])
}

async function onSaveAccess(grant) {
  const ok = await team.saveAccess(drawer.value.manager.user_id, grant)
  if (!ok) return
  drawer.value = null
  await loadAudit()
}

async function onRemoveMember(userId) {
  const ok = await team.remove(userId)
  if (ok) await loadAudit()
}

async function onRevokeInvitation(invitationId) {
  revoking.value = invitationId
  try {
    await revokeInvitation(invitationId)
    await Promise.all([loadInvitations(), loadAudit()])
  } finally {
    revoking.value = null
  }
}
</script>

<template>
  <div class="lp-section">
    <p v-if="team.error.value" class="lp-alert">{{ team.error.value }}</p>

    <ProfileTeam
      :managers="team.managers.value"
      :saving="team.saving.value"
      can-invite
      @invite="drawer = { kind: 'invite' }"
      @edit="(manager) => (drawer = { kind: 'access', manager })"
      @remove="onRemoveMember"
    />

    <InvitationList :invitations="invitations" :busy="revoking" @revoke="onRevokeInvitation" />

    <AccessLog :entries="auditEntries" :loading="auditLoading" />

    <TeamDrawers
      :drawer="drawer"
      :member-saving="team.saving.value"
      @close="drawer = null"
      @invite="onInvite"
      @save-access="onSaveAccess"
    />
  </div>
</template>
