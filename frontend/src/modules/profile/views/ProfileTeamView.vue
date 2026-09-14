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

import AccessLog from '@/modules/profile/components/AccessLog.vue'
import InvitationList from '@/modules/profile/components/InvitationList.vue'
import ProfileTeam from '@/modules/profile/components/ProfileTeam.vue'
import TeamDrawers from '@/modules/profile/components/TeamDrawers.vue'
import { useMembersStore } from '@/modules/profile/membersStore'

const members = useMembersStore()

/** `{ kind: 'invite' | 'access', manager? }` or null. */
const drawer = ref(null)

onMounted(async () => {
  await members.ensureLoaded()
  await members.loadTeamHistory()
})

async function onInvite({ onIssued, ...payload }) {
  const invitation = await members.invite(payload)
  if (!invitation) return
  onIssued(invitation)
  // The new link belongs in the list below, and issuing one is an audited act.
  await members.loadTeamHistory()
}

async function onSaveAccess(grant) {
  const ok = await members.saveAccess(drawer.value.manager.user_id, grant)
  if (!ok) return
  drawer.value = null
  await members.loadTeamHistory()
}

async function onRemoveMember(userId) {
  const ok = await members.removeManager(userId)
  if (ok) await members.loadTeamHistory()
}
</script>

<template>
  <div class="pf-section">
    <p v-if="members.error" class="pf-alert">{{ members.error }}</p>

    <ProfileTeam
      :managers="members.managers"
      :saving="members.saving"
      can-invite
      @invite="drawer = { kind: 'invite' }"
      @edit="(manager) => (drawer = { kind: 'access', manager })"
      @remove="onRemoveMember"
    />

    <InvitationList
      :invitations="members.issuedInvitations"
      :busy="members.saving"
      @revoke="members.revokeIssuedInvitation"
    />

    <AccessLog :entries="members.auditTrail" :loading="members.historyLoading" />

    <TeamDrawers
      :drawer="drawer"
      :member-saving="members.saving"
      @close="drawer = null"
      @invite="onInvite"
      @save-access="onSaveAccess"
    />
  </div>
</template>
