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
  fetchAuditLog,
  fetchInvitations,
  fetchMembers,
  fetchMyInvitations,
  fetchOrganizationMe,
  removeMember as removeMemberRequest,
  revokeInvitation,
  updateMemberAccess,
} from '@/modules/profile/api'

export const useMembersStore = defineStore('members', () => {
  const role = ref(null)
  // A/B tests and the labs are built for ONE seller, against our own data. The
  // API has always answered with this flag and the SPA never read it, so the
  // routes and the nav link were open to every signed-in customer — the pages
  // rendered, and only the XHR behind them came back 403.
  const internalFeatures = ref(false)
  //: «Ключи активации»: a dev, or the owner of the primary organisation. The API refuses
  //: everyone else (`require_code_issuer`); this only decides what is drawn.
  const canIssueCodes = ref(false)
  /** Whether the caller's role writes — false for a read-only manager. */
  const canWrite = ref(false)
  // `organization` is null for an account that registered and never redeemed a
  // code. The API has always said so; the SPA showed such a person the whole
  // app with every panel empty and no explanation of what was missing.
  const organization = ref(null)
  //: A head with no company of their own: `organization` is null and yet the
  //: app opens, on the workspaces a dev granted them, read-only. Without this
  //: the activation overlay would cover the very thing they were let in to see.
  const guestOnly = ref(false)
  //: The surfaces this account may reach, as the API resolves them — owners and
  //: devs come back with all of them. The SPA showed every nav link regardless
  //: and let a narrowed manager open a page whose every request then 403'd.
  const modules = ref([])
  //: The organisation's term, as `/me` reports it: `{ state, expires_at, ... }`
  //: or null. `state` is 'active' | 'grace' | 'expired'.
  const subscription = ref(null)
  //: Whether the tenant may reach the service AT ALL. False once the term is
  //: past its grace window, at which point every tenant-scoped route answers
  //: 403 and the app draws the paywall instead of a shell full of failures.
  //: The API decides this (`require_member`); the flag only lets us say so.
  const hasAccess = ref(true)
  //: Invitations addressed to this account's address, loaded only when it has
  //: no organisation — a member has nothing to accept.
  const invitations = ref([])
  const members = ref([])
  //: Invitations this company issued, and its access trail. Both are «Команда»
  //: state: nothing else in the app reads them, and loading them with the
  //: bootstrap would make every page pay for one screen.
  const issuedInvitations = ref([])
  const auditTrail = ref([])
  const historyLoading = ref(false)
  const loading = ref(false)
  const saving = ref(null)
  const error = ref('')
  const loaded = ref(false)

  /** Only an owner may see or change anyone's access. */
  const isOwner = computed(() => role.value === 'owner')

  /**
   * Whether this account may see and change the roster at all.
   *
   * `require_owner` on the API admits a **dev** as well as an owner, and a dev
   * account collapses to the `dev` effective role however it is a member of its
   * company. Gating on `isOwner` alone therefore hid «Команда», the invitations
   * and the access log from a developer — the API would have answered all
   * three (checked: 200, not 403), and only this flag said no.
   */
  const canManageTeam = computed(() => role.value === 'owner' || role.value === 'dev')

  /**
   * Whether this account has been let into a company yet.
   *
   * Answers `true` until `ensureLoaded` has run, so the app does not flash the
   * activation overlay at every member on every cold load. The gate that
   * matters is the API's, which never guesses.
   */
  const hasOrganization = computed(() => !loaded.value || organization.value !== null)

  /**
   * Whether the subscription has lapsed past its grace window.
   *
   * Answers `false` until `ensureLoaded` has run, for the same reason
   * `hasOrganization` answers `true`: a cold load must not flash a paywall at
   * somebody who has paid. The gate that decides is the API's.
   */
  const subscriptionExpired = computed(() => loaded.value && !hasAccess.value)

  /**
   * Whether a section is reachable.
   *
   * Answers `true` until the API has spoken, so no cold load flashes a locked
   * screen at somebody who is allowed in. The gate that decides is the API's;
   * this only stops us drawing what it would refuse.
   */
  function canReach(moduleKey) {
    if (!loaded.value) return true
    return modules.value.includes(moduleKey)
  }

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
      canIssueCodes.value = Boolean(me.can_issue_codes)
      canWrite.value = Boolean(me.can_write)
      organization.value = me.organization ?? null
      guestOnly.value = Boolean(me.is_guest_only)
      modules.value = me.modules ?? []
      subscription.value = me.subscription ?? null
      // `?? true` rather than `Boolean(...)`: an API that has not yet learned
      // to send the field must not read as "everyone is locked out".
      hasAccess.value = me.has_access ?? true
      // Only for an account with nowhere to be. Asking otherwise spends a round
      // trip on a list that is always empty.
      if (organization.value === null) {
        invitations.value = await fetchMyInvitations().catch(() => [])
      }
      // Asked for only when it can be answered: the roster is owner-or-dev, and
      // a manager opening their profile would otherwise take a guaranteed 403.
      // `hasAccess` is the second half of the same rule — /members sits behind
      // `require_member`, which refuses a lapsed tenant outright, and letting
      // that 403 throw here would leave `loaded` false and the paywall
      // undrawn: the one state the flag exists to render.
      if (canManageTeam.value && hasAccess.value) members.value = await fetchMembers()
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

  /**
   * Remove a manager from the organisation.
   *
   * The list is re-read rather than spliced: the server decides who is a
   * member, and a local removal that the request did not actually make would
   * show an owner a roster they cannot act on.
   */
  async function removeManager(userId) {
    saving.value = userId
    error.value = ''
    try {
      await removeMemberRequest(userId)
      members.value = await fetchMembers()
      return true
    } catch (err) {
      error.value = extractErrorMessage(err)
      return false
    } finally {
      saving.value = null
    }
  }

  /**
   * Re-read the roster from the server.
   *
   * Called after a change the server decided — a removal, a grant — rather than
   * patching the local list: the server is the authority on who is a member,
   * and a local edit the request did not actually make shows a roster nobody
   * can act on.
   */
  async function refreshMembers() {
    if (!canManageTeam.value) return
    members.value = await fetchMembers().catch(() => members.value)
  }

  /**
   * The invitations this company has issued, and its access trail.
   *
   * Loaded on demand rather than in `ensureLoaded`: only «Команда» renders
   * them, and every other page in the app pays for that bootstrap.
   */
  async function loadTeamHistory() {
    if (!canManageTeam.value) return
    historyLoading.value = true
    try {
      const [issued, trail] = await Promise.all([
        fetchInvitations().catch(() => []),
        // 100 rather than the endpoint's default: the list pages client-side,
        // and a page that shows ten of fifty entries silently is worse than one
        // that says there are five pages.
        fetchAuditLog(100).catch(() => []),
      ])
      issuedInvitations.value = issued
      auditTrail.value = trail
    } finally {
      historyLoading.value = false
    }
  }

  /** Stop an outstanding invitation working. */
  async function revokeIssuedInvitation(invitationId) {
    saving.value = invitationId
    error.value = ''
    try {
      await revokeInvitation(invitationId)
      await loadTeamHistory()
      return true
    } catch (err) {
      error.value = extractErrorMessage(err)
      return false
    } finally {
      saving.value = null
    }
  }

  return {
    canManageTeam,
    issuedInvitations,
    auditTrail,
    historyLoading,
    loadTeamHistory,
    refreshMembers,
    revokeIssuedInvitation,
    role,
    organization,
    subscription,
    hasAccess,
    subscriptionExpired,
    removeManager,
    modules,
    canReach,
    invitations,
    acceptInvite,
    hasOrganization,
    guestOnly,
    activate,
    internalFeatures,
    canIssueCodes,
    canWrite,
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
