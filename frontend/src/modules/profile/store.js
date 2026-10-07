/**
 * Workspace Pinia store (Composition-API setup style).
 *
 * Owns the workspace context of the whole app: the list of workspaces, the
 * active selection (mirrored into the core Axios client, which stamps every
 * request with the `X-Workspace-Id` header), and the current account's
 * profile (`/me` — email + role, gating the dev-only admin panel).
 *
 * `ensureLoaded()` runs once per session before any workspace-scoped view
 * loads (wired as a router guard in main.js), so the header is always set
 * before the first monitoring request fires.
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { extractErrorMessage, getWorkspaceId, setWorkspaceId } from '@/core/api/axios'
import {
  createWorkspace,
  deleteWorkspace,
  fetchMe,
  fetchTokenStatus,
  fetchWorkspaces,
  updateTokens,
  updateWorkspaceSettings,
} from '@/modules/profile/api'

export const useWorkspaceStore = defineStore('workspace', () => {
  // --- state -------------------------------------------------------------
  const workspaces = ref([])
  const currentWorkspaceId = ref(getWorkspaceId())
  const me = ref(null)
  const loading = ref(false)
  const error = ref(null)

  let loadPromise = null

  // --- getters -----------------------------------------------------------
  const currentWorkspace = computed(
    () => workspaces.value.find((ws) => ws.id === currentWorkspaceId.value) ?? null,
  )
  const isDev = computed(() => me.value?.role === 'dev')

  // --- internal helpers ----------------------------------------------------
  /** Adopt a workspace id as active (store + Axios header + localStorage). */
  function applySelection(id) {
    currentWorkspaceId.value = id
    setWorkspaceId(id)
  }

  /** Keep the stored selection when still valid; else fall back to the first. */
  function reconcileSelection() {
    const known = workspaces.value.some((ws) => ws.id === currentWorkspaceId.value)
    if (!known) {
      applySelection(workspaces.value[0]?.id ?? null)
    }
  }

  // --- actions -------------------------------------------------------------
  /**
   * Resolve the workspace context once per session: profile + workspace list,
   * then validate/repair the persisted selection. Concurrent callers share
   * one request chain; later calls are no-ops.
   */
  function ensureLoaded() {
    // `allSettled`, NOT `all`. `/v1/workspaces` sits behind `require_member`,
    // so it answers 403 for an account that has registered and not yet redeemed
    // an activation code — and `Promise.all` threw that rejection away together
    // with the `fetchMe()` result that HAD succeeded. The profile page then
    // rendered «—» for the email, the role and the workspace of a perfectly
    // valid session: the account looked broken when it was merely new.
    loadPromise ??= Promise.allSettled([fetchMe(), fetchWorkspaces()]).then(([profile, items]) => {
      if (profile.status === 'fulfilled') me.value = profile.value
      workspaces.value = items.status === 'fulfilled' ? items.value : []
      reconcileSelection()

      // Only a failure that leaves us unable to say WHO this is deserves the
      // error banner. An empty workspace list is the normal state of an
      // account waiting for activation, and the overlay explains it far
      // better than a red box would.
      if (profile.status === 'rejected') {
        loadPromise = null // let the next navigation retry
        error.value = extractErrorMessage(profile.reason)
        throw profile.reason
      }
    })
    return loadPromise
  }

  /** Re-fetch the workspace list (after create/delete). */
  async function refreshWorkspaces() {
    workspaces.value = await fetchWorkspaces()
    reconcileSelection()
  }

  /**
   * Switch the active workspace. The caller is expected to hard-reload into a
   * data view afterwards — cached per-workspace state (monitoring store) must
   * not survive a tenancy switch.
   */
  function select(id) {
    applySelection(id)
  }

  async function create(name) {
    error.value = null
    loading.value = true
    try {
      const created = await createWorkspace(name)
      await refreshWorkspaces()
      return created
    } catch (err) {
      error.value = extractErrorMessage(err)
      return null
    } finally {
      loading.value = false
    }
  }

  async function remove(id) {
    error.value = null
    loading.value = true
    try {
      await deleteWorkspace(id)
      await refreshWorkspaces()
      return true
    } catch (err) {
      error.value = extractErrorMessage(err)
      return false
    } finally {
      loading.value = false
    }
  }

  /**
   * Read a workspace's per-surface token configuration (dev only).
   * Returned, not stored: the admin panel owns this transient view state.
   */
  async function tokenStatus(id) {
    return fetchTokenStatus(id)
  }

  /** Set/rotate a workspace's WB tokens (dev only); returns the new status. */
  async function saveTokens(id, tokens) {
    error.value = null
    loading.value = true
    try {
      return await updateTokens(id, tokens)
    } catch (err) {
      error.value = extractErrorMessage(err)
      return null
    } finally {
      loading.value = false
    }
  }

  /**
   * Change the active кабинет's settings — shown at once, saved on the server,
   * and put back if the server refuses.
   */
  async function saveSettings(settings) {
    const current = currentWorkspace.value
    if (!current) return
    const before = { ...current }
    Object.assign(current, settings)
    error.value = null
    try {
      Object.assign(current, await updateWorkspaceSettings(settings))
    } catch (err) {
      Object.assign(current, before)
      error.value = extractErrorMessage(err)
    }
  }

  function clearError() {
    error.value = null
  }

  return {
    workspaces,
    currentWorkspaceId,
    currentWorkspace,
    me,
    isDev,
    loading,
    error,
    ensureLoaded,
    refreshWorkspaces,
    select,
    create,
    remove,
    tokenStatus,
    saveTokens,
    saveSettings,
    clearError,
  }
})
