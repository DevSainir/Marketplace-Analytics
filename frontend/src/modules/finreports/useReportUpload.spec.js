/**
 * "Upload report": the page follows the worker to its answer and says it.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { fetchSettlementUpload, uploadSettlementReport } from '@/modules/finreports/api'
import { useReportUpload } from '@/modules/finreports/useReportUpload'

vi.mock('@/modules/finreports/api', () => ({
  uploadSettlementReport: vi.fn(),
  fetchSettlementUpload: vi.fn(),
}))

const FILE = new File(['zip'], 'weekly-detailed-report-992915233_9383646.zip')

function fakeStore() {
  return { loadWeeks: vi.fn(), loadReport: vi.fn(), loadHarvestState: vi.fn() }
}

const instant = { sleep: () => Promise.resolve(), now: () => 0 }

beforeEach(() => {
  vi.clearAllMocks()
})

describe('useReportUpload', () => {
  it('waits for the worker and shows its sentence once the rows are in', async () => {
    const store = fakeStore()
    uploadSettlementReport.mockResolvedValue({ id: 'u1', status: 'queued' })
    fetchSettlementUpload
      .mockResolvedValueOnce({ id: 'u1', status: 'processing' })
      .mockResolvedValueOnce({
        id: 'u1',
        status: 'written',
        message: 'Report for 5–11 Oct loaded — 3,257 rows.',
      })
    const upload = useReportUpload(store, instant)

    await upload.upload(FILE)

    expect(upload.notice.value).toBe('Report for 5–11 Oct loaded — 3,257 rows.')
    expect(store.loadWeeks).toHaveBeenCalled()
    expect(store.loadReport).toHaveBeenCalled()
    expect(upload.busy.value).toBe(false)
  })

  it('reloads nothing when we already held the report', async () => {
    // Nothing changed on the page, so a reload would only cost a request.
    const store = fakeStore()
    uploadSettlementReport.mockResolvedValue({ id: 'u1', status: 'queued' })
    fetchSettlementUpload.mockResolvedValue({
      id: 'u1',
      status: 'already_held',
      message: 'This report is already on file — it matches the upload row for row.',
    })
    const upload = useReportUpload(store, instant)

    await upload.upload(FILE)

    expect(upload.notice.value).toContain('already on file')
    expect(store.loadReport).not.toHaveBeenCalled()
  })

  it('shows a refusal as an error, in the worker’s words', async () => {
    uploadSettlementReport.mockResolvedValue({ id: 'u1', status: 'queued' })
    fetchSettlementUpload.mockResolvedValue({
      id: 'u1',
      status: 'failed',
      message: 'The week of 12–18 Oct is not over yet — there is no report for it.',
    })
    const upload = useReportUpload(fakeStore(), instant)

    await upload.upload(FILE)

    expect(upload.error.value).toContain('not over yet')
    expect(upload.notice.value).toBe('')
  })

  it('says the file is still being read rather than polling forever', async () => {
    let clock = 0
    uploadSettlementReport.mockResolvedValue({ id: 'u1', status: 'queued' })
    fetchSettlementUpload.mockResolvedValue({ id: 'u1', status: 'processing' })
    const upload = useReportUpload(fakeStore(), {
      sleep: () => {
        clock += 60_000
        return Promise.resolve()
      },
      now: () => clock,
    })

    await upload.upload(FILE)

    expect(upload.notice.value).toContain('Still reading')
    expect(upload.busy.value).toBe(false)
  })
})
