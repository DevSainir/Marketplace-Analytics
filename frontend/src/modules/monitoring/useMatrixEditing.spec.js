import { defineComponent, h } from 'vue'
import { mount } from '@vue/test-utils'

import { useMatrixEditing } from '@/modules/monitoring/useMatrixEditing'

/** A store stand-in: real refs, and every commit recorded rather than sent. */
function fakeStore(overrides = {}) {
  return {
    matrixView: { days: [{ iso: '2026-07-01' }], rows: [] },
    matrixSaving: false,
    matrixRefreshing: false,
    canUndoMatrix: true,
    canRedoMatrix: true,
    calls: [],
    applyCellEdit(edit) {
      this.calls.push(['cell', edit])
    },
    saveDayComment(day, patch) {
      this.calls.push(['comment', day, patch])
    },
    saveDayAction(day, patch) {
      this.calls.push(['action', day, patch])
    },
    undoMatrixEdit() {
      this.calls.push(['undo'])
    },
    redoMatrixEdit() {
      this.calls.push(['redo'])
    },
    ...overrides,
  }
}

/**
 * The composable needs an owner component: it registers keyboard lifecycle.
 *
 * Captured in a plain variable, NOT a `ref` — a ref would deep-unwrap the
 * computeds inside and the assertions would be reading values where they mean
 * to read the refs themselves.
 */
function mountWith(store) {
  let api = null
  const wrapper = mount(
    defineComponent({
      setup() {
        api = useMatrixEditing(store)
        return () => h('div')
      },
    }),
  )
  return { api, wrapper }
}

describe('useMatrixEditing', () => {
  it('exposes the store’s matrix rather than a copy of it', () => {
    // The store patches cells in place on edit/undo/redo; re-wrapping the rows
    // here would break that and re-render the whole table on every keystroke.
    const store = fakeStore()
    const { api } = mountWith(store)

    expect(api.matrix.value).toBe(store.matrixView)
  })

  it('locks editing while a save or a refresh is in flight', () => {
    expect(mountWith(fakeStore()).api.editingLocked.value).toBe(false)
    expect(mountWith(fakeStore({ matrixSaving: true })).api.editingLocked.value).toBe(true)
    expect(mountWith(fakeStore({ matrixRefreshing: true })).api.editingLocked.value).toBe(true)
  })

  it('forwards each commit to the store untouched', () => {
    // The backend owns the arithmetic — a cell edit back-solves and recomputes
    // dependents there — so nothing may be adjusted on the way through.
    const store = fakeStore()
    const { api } = mountWith(store)

    api.onCellEdit({ day: '2026-07-01', bucket: 'total', metric: 'spend', value: 12 })
    api.onCommentEdit({ day: '2026-07-01', patch: { body: 'что-то' } })
    api.onActionEdit({ day: '2026-07-01', patch: { price_change: true } })

    expect(store.calls).toEqual([
      ['cell', { day: '2026-07-01', bucket: 'total', metric: 'spend', value: 12 }],
      ['comment', '2026-07-01', { body: 'что-то' }],
      ['action', '2026-07-01', { price_change: true }],
    ])
  })

  it('wires undo and redo to the keyboard', () => {
    const store = fakeStore()
    const { wrapper } = mountWith(store)

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'z', ctrlKey: true }))
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'z', ctrlKey: true, shiftKey: true }))

    expect(store.calls).toEqual([['undo'], ['redo']])
    wrapper.unmount()
  })

  it('ignores the history keys while a save is running', () => {
    // Undoing into a save in flight would race the request it is undoing.
    const store = fakeStore({ matrixSaving: true })
    mountWith(store)

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'z', ctrlKey: true }))

    expect(store.calls).toEqual([])
  })
})
