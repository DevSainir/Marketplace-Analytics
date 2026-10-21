import { createPinia, setActivePinia } from 'pinia'

import { fetchMe, fetchWorkspaces, updateWorkspaceSettings } from '@/modules/profile/api'
import { useWorkspaceStore } from '@/modules/profile/store'

vi.mock('@/core/api/axios', () => ({
  extractErrorMessage: () => 'Нет прав на изменение',
  getWorkspaceId: () => 'ws-1',
  setWorkspaceId: vi.fn(),
}))

vi.mock('@/modules/profile/api', () => ({
  createWorkspace: vi.fn(),
  deleteWorkspace: vi.fn(),
  fetchMe: vi.fn(),
  fetchTokenStatus: vi.fn(),
  fetchWorkspaces: vi.fn(),
  updateTokens: vi.fn(),
  updateWorkspaceSettings: vi.fn(),
}))

/** A store with one workspace selected, its «Промо-бонусы» switch on. */
async function loadedStore() {
  fetchMe.mockResolvedValue({ email: 'a@b.c', role: 'user' })
  fetchWorkspaces.mockResolvedValue([{ id: 'ws-1', name: 'Демо', ads_show_bonus: true }])
  const store = useWorkspaceStore()
  await store.ensureLoaded()
  return store
}

describe('workspace settings — the «Промо-бонусы» switch of the кабинет', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('is saved on the server and kept on the кабинет', async () => {
    const store = await loadedStore()
    updateWorkspaceSettings.mockResolvedValue({
      id: 'ws-1',
      name: 'Демо',
      ads_show_bonus: false,
    })

    await store.saveSettings({ ads_show_bonus: false })

    expect(updateWorkspaceSettings).toHaveBeenCalledWith({ ads_show_bonus: false })
    expect(store.currentWorkspace.ads_show_bonus).toBe(false)
  })

  it('goes back to what it was when the server refuses', async () => {
    const store = await loadedStore()
    updateWorkspaceSettings.mockRejectedValue(new Error('403'))

    await store.saveSettings({ ads_show_bonus: false })

    expect(store.currentWorkspace.ads_show_bonus).toBe(true)
    expect(store.error).toBe('Нет прав на изменение')
  })
})
