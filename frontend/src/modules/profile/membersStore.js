/**
 * Manager access: who is in the company, and what each of them may reach.
 *
 * A store of its own rather than more surface on `useWorkspaceStore`. That one
 * is about which WB account you are looking at and is loaded on every page;
 * this is owner-only, loaded on one panel, and mixing them would make every
 * view pay for a members list it never renders.
 *
 * The effective role comes from `/v1/organizations/me`, not from `/v1/auth/me`.
 * The second answers "dev or ordinary account", which is not the question the
 * panel is gated on — an owner is an owner by their MEMBERSHIP.
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { extractErrorMessage } from '@/core/api/axios'
import {
  acceptInvitation,
  activateOrganization,
  createInvitation,
  fetchMembers,
  fetchMyInvitations,
  fetchOrganizationMe,
  updateMemberAccess,
} from '@/modules/profile/api'

/** Every grantable surface, in the order the UI lists them. */
export const MODULES = [
  { key: 'monitoring', label: 'Мониторинг', hint: 'Включая «Графики»' },
  { key: 'finreports', label: 'Прибыли и убытки', hint: 'P&L и себестоимость' },
  { key: 'ab_tests', label: 'A/Б-тесты', hint: 'Ротация фото' },
]

export const useMembersStore = defineStore('members', () => {
  const role = ref(null)
  // against our own data and our own legal case. The API has always answered
  // with this flag and the SPA never read it, so the routes and the nav link
  // were open to every signed-in customer — the pages rendered, and only the
  // XHR behind them came back 403.
  const internalFeatures = ref(false)
  // `organization` is null for an account that registered and never redeemed a
  // code. The API has always said so; the SPA showed such a person the whole
  // app with every panel empty and no explanation of what was missing.
  const organization = ref(null)
  //: Invitations addressed to this account's address, loaded only when it has
  //: no organisation — a member has nothing to accept.
  const invitations = ref([])
  const members = ref([])
  const loading = ref(false)
  const saving = ref(null)
  const error = ref('')
  const loaded = ref(false)

  /** Only an owner may see or change anyone's access. */
  const isOwner = computed(() => role.value === 'owner')

  /**
   * Whether this account has been let into a company yet.
   *
   * Answers `true` until `ensureLoaded` has run, so the app does not flash the
   * activation overlay at every member on every cold load. The gate that
   * matters is the API's, which never guesses.
   */
  const hasOrganization = computed(() => !loaded.value || organization.value !== null)

  /** The owner's own row is not editable — see the backend's refusal. */
  const managers = computed(() => members.value.filter((m) => m.role !== 'owner'))

  async function ensureLoaded() {
    if (loaded.value) return
    loading.value = true
    error.value = ''
    try {
      const me = await fetchOrganizationMe()
      role.value = me.role
      internalFeatures.value = Boolean(me.internal_features)
      organization.value = me.organization ?? null
      // Only for an account with nowhere to be. Asking otherwise spends a round
      // trip on a list that is always empty.
      if (organization.value === null) {
        invitations.value = await fetchMyInvitations().catch(() => [])
      }
      // Asked for only when it can be answered: /members is owner-only, and a
      // manager opening their profile would otherwise take a guaranteed 403.
      if (me.role === 'owner') members.value = await fetchMembers()
      loaded.value = true
    } catch (err) {
      error.value = err?.response?.data?.detail ?? 'Не удалось загрузить участников.'
    } finally {
      loading.value = false
    }
  }

  async function saveAccess(userId, grant) {
    saving.value = userId
    error.value = ''
    try {
      const updated = await updateMemberAccess(userId, grant)
      // Replace rather than mutate in place: the server is the authority on
      // what was stored, and echoing the request would hide a rejected value.
      members.value = members.value.map((m) => (m.user_id === userId ? updated : m))
      return true
    } catch (err) {
      error.value = err?.response?.data?.detail ?? 'Не удалось сохранить доступ.'
      return false
    } finally {
      saving.value = null
    }
  }

  async function invite(payload) {
    saving.value = 'invite'
    error.value = ''
    try {
      return await createInvitation(payload)
    } catch (err) {
      error.value = err?.response?.data?.detail ?? 'Не удалось создать приглашение.'
      return null
    } finally {
      saving.value = null
    }
  }

  /**
   * Redeem an activation code. Returns true when the account is now inside a
   * company, false with `error` set otherwise.
   */
  async function activate(code) {
    saving.value = 'activation'
    error.value = ''
    try {
      organization.value = await activateOrganization(code)
      // Everything downstream keyed off the old answer — the role, the module
      // grants, the workspace list. Re-read rather than patch.
      loaded.value = false
      await ensureLoaded()
      return true
    } catch (err) {
      error.value = extractErrorMessage(err)
      return false
    } finally {
      saving.value = null
    }
  }

  /**
   * Join a company with the token from an invitation.
   *
   * Same shape as `activate`: true on success, false with `error` set. Both
   * end the same way — re-reading everything, because the role, the module
   * grants and the workspace list are all downstream of the answer that just
   * changed.
   */
  async function acceptInvite(token) {
    saving.value = 'invitation'
    error.value = ''
    try {
      await acceptInvitation(token)
      loaded.value = false
      await ensureLoaded()
      return organization.value !== null
    } catch (err) {
      error.value = extractErrorMessage(err)
      return false
    } finally {
      saving.value = null
    }
  }

  return {
    role,
    organization,
    invitations,
    acceptInvite,
    hasOrganization,
    activate,
    internalFeatures,
    members,
    managers,
    isOwner,
    loading,
    saving,
    error,
    ensureLoaded,
    saveAccess,
    invite,
  }
})
