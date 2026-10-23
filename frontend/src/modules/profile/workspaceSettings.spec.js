import { createPinia, setActivePinia } from 'pinia'

import { fetchMe, fetchWorkspaces, updateWorkspaceSettings } from '@/modules/profile/api'
import { useWorkspaceStore } from '@/modules/profile/store'

vi.mock('@/core/api/axios', () => ({
  extractErrorMessage: () => 'Not allowed to change this',
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

/** A store with one workspace selected, its "Promo bonuses" switch on. */
async function loadedStore() {
  fetchMe.mockResolvedValue({ email: 'a@b.c', role: 'user' })
  fetchWorkspaces.mockResolvedValue([{ id: 'ws-1', name: 'Demo', ads_show_bonus: true }])
  const store = useWorkspaceStore()
  await store.ensureLoaded()
  return store
}

describe('workspace settings — the "Promo bonuses" switch of the workspace', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('is saved on the server and kept on the workspace', async () => {
    const store = await loadedStore()
    updateWorkspaceSettings.mockResolvedValue({
      id: 'ws-1',
      name: 'Demo',
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
    expect(store.error).toBe('Not allowed to change this')
  })
})
