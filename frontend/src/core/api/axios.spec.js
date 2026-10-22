import MockAdapter from 'axios-mock-adapter'

import apiClient, {
  clearAccessToken,
  extractErrorMessage,
  setAccessToken,
  setUnauthorizedHandler,
} from '@/core/api/axios'

let mock

beforeEach(() => {
  mock = new MockAdapter(apiClient)
  clearAccessToken()
})

afterEach(() => {
  mock.restore()
})

describe('request interceptor', () => {
  it('attaches the in-memory access token as a Bearer header', async () => {
    setAccessToken('token-1')
    mock.onGet('/v1/x').reply((config) => [200, { auth: config.headers.Authorization }])

    const { data } = await apiClient.get('/v1/x')

    expect(data.auth).toBe('Bearer token-1')
  })

  it('sends no Authorization header without a token', async () => {
    mock.onGet('/v1/x').reply((config) => [200, { auth: config.headers.Authorization ?? null }])

    const { data } = await apiClient.get('/v1/x')

    expect(data.auth).toBeNull()
  })

  it('lets a FormData body pick its own Content-Type', async () => {
    // The instance default is `application/json`, and an instance default
    // outranks the per-request type Axios would infer. A multipart body sent
    // under it reaches the server unparseable — the boundary is missing, so
    // there are no fields at all — and the upload fails as a malformed
    // request, which is what broke every A/B photo upload in the browser
    // while every unit and component test stayed green.
    const form = new FormData()
    form.append('file', new Blob(['x']), 'variant.jpg')
    mock.onPost('/v1/upload').reply((config) => [200, { type: config.headers['Content-Type'] }])

    const { data } = await apiClient.post('/v1/upload', form)

    expect(data.type).not.toBe('application/json')
  })

  it('still sends JSON for an ordinary object body', async () => {
    mock.onPost('/v1/thing').reply((config) => [200, { type: config.headers['Content-Type'] }])

    const { data } = await apiClient.post('/v1/thing', { name: 'x' })

    expect(data.type).toBe('application/json')
  })
})

describe('401 refresh-retry interceptor', () => {
  it('rotates the refresh token once and retries the original request', async () => {
    mock.onGet('/v1/data').replyOnce(401)
    mock.onPost('/v1/auth/refresh').replyOnce(200, { access_token: 'fresh' })
    mock.onGet('/v1/data').reply((config) => [200, { auth: config.headers.Authorization }])

    const { data } = await apiClient.get('/v1/data')

    expect(data.auth).toBe('Bearer fresh')
    expect(mock.history.post.filter((r) => r.url === '/v1/auth/refresh')).toHaveLength(1)
  })

  it('deduplicates concurrent 401s into a single refresh call', async () => {
    mock.onGet('/v1/a').replyOnce(401)
    mock.onGet('/v1/b').replyOnce(401)
    mock.onPost('/v1/auth/refresh').reply(200, { access_token: 'fresh' })
    mock.onGet('/v1/a').reply(200, { ok: 'a' })
    mock.onGet('/v1/b').reply(200, { ok: 'b' })

    const [a, b] = await Promise.all([apiClient.get('/v1/a'), apiClient.get('/v1/b')])

    expect(a.data.ok).toBe('a')
    expect(b.data.ok).toBe('b')
    expect(mock.history.post.filter((r) => r.url === '/v1/auth/refresh')).toHaveLength(1)
  })

  it('invokes the unauthorized handler when the refresh itself fails', async () => {
    const onUnauthorized = vi.fn()
    setUnauthorizedHandler(onUnauthorized)
    mock.onGet('/v1/data').replyOnce(401)
    mock.onPost('/v1/auth/refresh').reply(401, { detail: 'expired' })

    await expect(apiClient.get('/v1/data')).rejects.toThrow()

    expect(onUnauthorized).toHaveBeenCalledTimes(1)
  })

  it('does not try to refresh when an auth endpoint itself returns 401', async () => {
    mock.onPost('/v1/auth/login').reply(401, { detail: 'bad credentials' })

    await expect(apiClient.post('/v1/auth/login', {})).rejects.toThrow()

    expect(mock.history.post.filter((r) => r.url === '/v1/auth/refresh')).toHaveLength(0)
  })
})

describe('extractErrorMessage', () => {
  it('reads the domain error envelope', () => {
    const err = { response: { data: { error: { code: 'x', message: 'Domain error' } } } }
    expect(extractErrorMessage(err)).toBe('Domain error')
  })

  it('reads FastAPI string detail', () => {
    const err = { response: { data: { detail: 'Invalid or expired access token.' } } }
    expect(extractErrorMessage(err)).toBe('Invalid or expired access token.')
  })

  it('reads the first FastAPI validation error', () => {
    const err = { response: { data: { detail: [{ msg: 'value is not a valid email' }] } } }
    expect(extractErrorMessage(err)).toBe('value is not a valid email')
  })

  it('answers an Axios transport failure in Russian, not in Axios English', () => {
    // Reversed on purpose. This used to return `error.message` verbatim, which
    // put 'Network Error' and 'timeout of 5000ms exceeded' in front of Russian
    // users — the SPA shows this string unaltered.
    const err = { isAxiosError: true, message: 'Network Error' }
    expect(extractErrorMessage(err)).toBe(
      "Can't reach the server. Check your connection and try again.",
    )
  })

  it('says a proxy timeout in words that point at the way out', () => {
    // nginx answers 504 with no body of ours; «Request failed with status code
    // 504» reached the logistics page verbatim before this.
    const err = { isAxiosError: true, response: { status: 504, data: '<html>' } }

    expect(extractErrorMessage(err)).toBe('The server ran out of time. Try a shorter period.')
  })

  it('distinguishes a server answer it cannot read from no answer at all', () => {
    const err = { isAxiosError: true, response: { status: 500, data: {} } }
    expect(extractErrorMessage(err)).toBe('Unexpected error. Please try again later.')
  })

  it('keeps a message the app raised itself', () => {
    // Our own throws are already written for the reader, in Russian. Replacing
    // them with a generic transport line is how the monitoring store's
    // poll-ceiling explanation got lost.
    expect(extractErrorMessage(new Error('The refresh did not finish in time'))).toBe(
      'The refresh did not finish in time',
    )
  })
})
