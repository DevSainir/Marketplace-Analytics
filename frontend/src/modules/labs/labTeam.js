/**
 * The team roster for the profile sandbox, loaded and written on its own.
 *
 * `useMembersStore` would have done this, except for one gate: it asks for the
 * roster only when the effective role is exactly `owner`, and a developer
 * account collapses to `dev` however it is a member of its company. A dev
 * therefore got an empty list and no «Команда» panel at all — on the real page
 * too, which is where the gap was found.
 *
 * The endpoints allow a dev (checked live: `GET /v1/organizations/members`
 * answers 200 for one). So the sandbox asks for itself, and the panel appears
 * for anyone the API would actually answer.
 *
 * Module-level state rather than per-caller: three pages read the roster (the
 * team page renders it, «Общие» counts it, the nav badges it) and a composable
 * with local refs would fetch it once per page and once per navigation. Not a
 * Pinia store, because nothing outside the sandbox may see it and a store in
 * `labs/` would be one more thing to delete when the sandbox goes.
 */
import { computed, ref } from 'vue'

import { extractErrorMessage } from '@/core/api/axios'
import {
  createInvitation,
  fetchMembers,
  removeMember,
  updateMemberAccess,
} from '@/modules/labs/profileApi'

const members = ref([])
/** Whether the API answered at all — the panel is hidden until it did. */
const available = ref(false)
/** A user_id being written, or 'invite'. */
const saving = ref(null)
const error = ref('')
/** Set once the first load finished, so a second page does not re-ask. */
const loaded = ref(false)

/** The owner's own row is not editable — see the backend's refusal. */
const managers = computed(() => members.value.filter((m) => m.role !== 'owner'))

export function useLabTeam() {
  async function load({ force = false } = {}) {
    if (loaded.value && !force) return
    try {
      members.value = await fetchMembers()
      available.value = true
    } catch {
      // 403 for an account that may not see a roster, 404 for one with no
      // company. Both mean the same thing here: draw no panel. Not an error
      // worth a red banner — it is an answer.
      available.value = false
    } finally {
      loaded.value = true
    }
  }

  async function saveAccess(userId, grant) {
    saving.value = userId
    error.value = ''
    try {
      const updated = await updateMemberAccess(userId, grant)
      // Replace rather than mutate: the server is the authority on what was
      // stored, and echoing the request would hide a rejected value.
      members.value = members.value.map((m) => (m.user_id === userId ? updated : m))
      return true
    } catch (err) {
      error.value = extractErrorMessage(err)
      return false
    } finally {
      saving.value = null
    }
  }

  async function remove(userId) {
    saving.value = userId
    error.value = ''
    try {
      await removeMember(userId)
      // Re-read rather than splice: the server decides who is a member, and a
      // local removal the request did not make shows a roster you cannot act on.
      await load({ force: true })
      return true
    } catch (err) {
      error.value = extractErrorMessage(err)
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
      error.value = extractErrorMessage(err)
      return null
    } finally {
      saving.value = null
    }
  }

  return { members, managers, available, saving, error, load, saveAccess, remove, invite }
}
