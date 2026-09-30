/**
 * The norm store's edit history: Ctrl+Z puts the previous norm back and saves
 * it, Ctrl+Shift+Z re-applies it, and a fresh edit drops what was undone.
 */
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as api from '@/modules/heatmap/api'
import { useHeatmapNormsStore } from '@/modules/heatmap/normsStore'

vi.mock('@/modules/heatmap/api', () => ({
  fetchNorms: vi.fn(),
  saveNorm: vi.fn(async () => ({})),
  deleteNorm: vi.fn(async () => {}),
}))

describe('norm history', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('undoes an edit by saving the previous norm back', async () => {
    const norms = useHeatmapNormsStore()
    await norms.save(1, 'orders', 50)
    await norms.save(1, 'orders', 80)

    norms.undo()

    expect(norms.normOf(1, 'orders')).toBe(50)
    expect(api.saveNorm).toHaveBeenLastCalledWith(1, 'orders', 50)
  })

  it('undoes a first norm by clearing it, and redoes it', async () => {
    const norms = useHeatmapNormsStore()
    await norms.save(1, 'orders', 50)

    norms.undo()
    expect(norms.normOf(1, 'orders')).toBeNull()
    expect(api.deleteNorm).toHaveBeenCalledWith(1, 'orders')

    norms.redo()
    expect(norms.normOf(1, 'orders')).toBe(50)
  })

  it('drops the undone changes on a fresh edit', async () => {
    const norms = useHeatmapNormsStore()
    await norms.save(1, 'orders', 50)
    norms.undo()
    await norms.save(1, 'orders', 70)

    norms.redo()

    expect(norms.normOf(1, 'orders')).toBe(70)
  })
})
