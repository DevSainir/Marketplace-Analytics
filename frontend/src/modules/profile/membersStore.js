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

import {
  createInvitation,
  fetchMembers,
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
  const members = ref([])
  const loading = ref(false)
  const saving = ref(null)
  const error = ref('')
  const loaded = ref(false)

  /** Only an owner may see or change anyone's access. */
  const isOwner = computed(() => role.value === 'owner')

  /** The owner's own row is not editable — see the backend's refusal. */
  const managers = computed(() => members.value.filter((m) => m.role !== 'owner'))

  async function ensureLoaded() {
    if (loaded.value) return
    loading.value = true
    error.value = ''
    try {
      const me = await fetchOrganizationMe()
      role.value = me.role
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

  return {
    role,
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
