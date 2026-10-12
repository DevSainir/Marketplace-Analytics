/**
 * «Загрузить отчёт»: the page follows the worker to its answer and says it.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { fetchSettlementUpload, uploadSettlementReport } from '@/modules/finreports/api'
import { useReportUpload } from '@/modules/finreports/useReportUpload'

vi.mock('@/modules/finreports/api', () => ({
  uploadSettlementReport: vi.fn(),
  fetchSettlementUpload: vi.fn(),
}))

const FILE = new File(['zip'], 'Еженедельный детализированный отчет №992915233_9383646.zip')

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
        message: 'Отчёт за 5–11 окт загружен — 3 257 строк.',
      })
    const upload = useReportUpload(store, instant)

    await upload.upload(FILE)

    expect(upload.notice.value).toBe('Отчёт за 5–11 окт загружен — 3 257 строк.')
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
      message: 'Этот отчёт у нас уже есть — совпадает с файлом до строки.',
    })
    const upload = useReportUpload(store, instant)

    await upload.upload(FILE)

    expect(upload.notice.value).toContain('уже есть')
    expect(store.loadReport).not.toHaveBeenCalled()
  })

  it('shows a refusal as an error, in the worker’s words', async () => {
    uploadSettlementReport.mockResolvedValue({ id: 'u1', status: 'queued' })
    fetchSettlementUpload.mockResolvedValue({
      id: 'u1',
      status: 'failed',
      message: 'Неделя 12–18 окт ещё не закончилась — отчёта за неё пока нет.',
    })
    const upload = useReportUpload(fakeStore(), instant)

    await upload.upload(FILE)

    expect(upload.error.value).toContain('ещё не закончилась')
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

    expect(upload.notice.value).toContain('ещё читается')
    expect(upload.busy.value).toBe(false)
  })
})
