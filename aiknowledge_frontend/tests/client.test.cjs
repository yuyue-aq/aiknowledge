const { test } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('typescript')

const source = fs.readFileSync(path.join(__dirname, '../src/api/client.ts'), 'utf8')
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }
}).outputText
const session = (token = 'old') => ({ user: { id: 'owner' }, tokens: { access_token: token, refresh_token: 'refresh' } })

test('chunk preview and rebuild bind source version and explicit configuration', async () => {
  const calls=[]
  const {client}=loadClient(async options=>{calls.push(options);return {statusCode:options.url.endsWith('/rechunk') ? 202 : 200,data:{fingerprint:'proof',version_id:'new',processing_enqueued:true}}})
  await client.previewDocumentChunks('space','doc',{strategy:'structure',max_tokens:384,overlap_characters:80,offset:12,limit:12})
  await client.rebuildDocumentChunks('space','doc',{strategy:'structure',max_tokens:384,overlap_characters:80,expected_version_id:'active',fingerprint:'proof'})
  assert.equal(calls[0].url,'/api/v1/owner/spaces/space/documents/doc/chunk-preview')
  assert.equal(calls[0].method,'POST');assert.equal(calls[0].data.offset,12)
  assert.equal(calls[1].url,'/api/v1/owner/spaces/space/documents/doc/rechunk')
  assert.equal(calls[1].data.expected_version_id,'active');assert.equal(calls[1].data.fingerprint,'proof')
})

function loadClient(request, extras = {}) {
  const storage = new Map()
  const taro = {
    request,
    getStorageSync: (key) => storage.get(key),
    setStorageSync: (key, value) => storage.set(key, value),
    removeStorageSync: (key) => storage.delete(key)
  }
  const context = {
    exports: {}, require: () => ({ default: taro }), process: { env: { TARO_ENV: 'h5' } },
    ReadableStream, TextDecoder, Uint8Array, URLSearchParams, ...extras
  }
  vm.runInNewContext(compiled, context)
  return { client: context.exports, storage }
}

test('version upload targets document route, reports progress and resolves accepted job', async () => {
  let xhr
  class File {}
  class FormData { append() {} }
  class XMLHttpRequest {
    constructor() { xhr = this; this.upload = {} }
    open(method, url) { this.method = method; this.url = url }
    setRequestHeader() {}
    send() { this.upload.onprogress({ lengthComputable: true, loaded: 5, total: 10 }); this.status = 202; this.response = { version_id: 'new', processing_enqueued: true }; this.onload() }
  }
  const { client } = loadClient(null, { File, FormData, XMLHttpRequest, AbortController })
  const progress = []
  const result = await client.uploadDocumentVersion('doc', new File(), value => progress.push(value))
  assert.equal(xhr.url, '/api/v1/documents/doc/versions')
  assert.equal(xhr.method, 'POST')
  assert.deepEqual(progress, [50])
  assert.equal(result.version_id, 'new')
})

test('cancelling a version upload aborts its active request', async () => {
  let xhr
  class File {}
  class FormData { append() {} }
  class XMLHttpRequest {
    constructor() { xhr = this; this.upload = {} }
    open() {}
    setRequestHeader() {}
    send() {}
    abort() { this.aborted = true; this.onabort() }
  }
  const { client } = loadClient(null, { File, FormData, XMLHttpRequest, AbortController })
  const controller = new AbortController()
  const pending = client.uploadDocumentVersion('doc', new File(), undefined, controller.signal)
  controller.abort()
  await assert.rejects(pending, { code: 'REQUEST_ABORTED' })
  assert.equal(xhr.aborted, true)
})

for (const remember of [false, true]) {
  test(`refresh preserves remember=${remember}`, async () => {
    let calls = 0
    const { client, storage } = loadClient(async ({ url }) => {
      if (url.endsWith('/auth/refresh')) return { statusCode: 200, data: session('new') }
      return ++calls === 1 ? { statusCode: 401 } : { statusCode: 200, data: [] }
    })
    client.saveAuthSession(session(), remember)
    await client.listSpaces()
    assert.equal(storage.has('aiknowledge.auth.session'), remember)
  })
}

test('public 401 neither refreshes nor clears the owner session', async () => {
  let refreshes = 0
  const { client, storage } = loadClient(async ({ url }) => {
    if (url.endsWith('/auth/refresh')) refreshes++
    return { statusCode: 401, data: { message: '访客会话失效' } }
  })
  client.saveAuthSession(session())
  await assert.rejects(client.getPublicSpace(), { status: 401 })
  assert.equal(refreshes, 0)
  assert.equal(storage.has('aiknowledge.auth.session'), true)
})

test('late refresh cannot sign a logged-out owner back in', async () => {
  let resolveRefresh
  let refreshStarted
  const started = new Promise((resolve) => { refreshStarted = resolve })
  const { client, storage } = loadClient(async ({ url }) => {
    if (url.endsWith('/auth/refresh')) {
      refreshStarted()
      return new Promise((resolve) => { resolveRefresh = resolve })
    }
    return { statusCode: 401 }
  })
  client.saveAuthSession(session())
  const request = client.listSpaces()
  await started
  client.clearAuthSession()
  resolveRefresh({ statusCode: 200, data: session('new') })
  await assert.rejects(request, { status: 401 })
  assert.equal(storage.size, 0)
})

test('stream retries authentication only once', async () => {
  let refreshes = 0
  let requests = 0
  const { client } = loadClient(async () => {
    refreshes++
    // Bound the regression even with the original recursive retry bug.
    return refreshes <= 3 ? { statusCode: 200, data: session('new') } : { statusCode: 401 }
  }, { fetch: async () => { requests++; return { status: 401, ok: false, json: async () => ({}) } } })
  client.saveAuthSession(session())
  await assert.rejects(client.streamOwnerAnswer('conversation', '问题', () => {}), { status: 401 })
  assert.equal(refreshes, 1)
  assert.equal(requests, 2)
})

test('unreadable SSE body uses the existing response without sending a duplicate question', async () => {
  let requests = 0
  let jsonRequests = 0
  const answer = { answer: '已回答', status: 'ANSWERED', message_id: 'message' }
  const { client } = loadClient(async () => { jsonRequests++; return { statusCode: 200, data: answer } }, {
    fetch: async () => {
      requests++
      return { ok: true, status: 200, headers: new Headers({ 'content-type': 'text/event-stream' }),
        body: null, text: async () => `event: answer\r\ndata: ${JSON.stringify(answer)}\r\n\r\nevent: done\r\ndata: {}\r\n\r\n` }
    }
  })
  assert.equal((await client.streamOwnerAnswer('conversation', '问题', () => {})).answer, answer.answer)
  assert.equal(requests, 1)
  assert.equal(jsonRequests, 0)
})

test('SSE parser handles split CRLF frames', async () => {
  const answer = { answer: '中文回答', status: 'ANSWERED' }
  const bytes = new TextEncoder().encode(`event: delta\r\ndata: {"text":"中文"}\r\n\r\nevent: answer\r\ndata: ${JSON.stringify(answer)}\r\n\r\n`)
  const { client } = loadClient(async () => { throw new Error('unexpected JSON request') }, {
    fetch: async () => new Response(new ReadableStream({ start(controller) {
      for (let i = 0; i < bytes.length; i += 3) controller.enqueue(bytes.slice(i, i + 3))
      controller.close()
    } }), { headers: { 'content-type': 'text/event-stream' } })
  })
  const updates = []
  assert.equal((await client.streamPublicAnswer('conversation', '问题', (text) => updates.push(text))).answer, answer.answer)
  assert.deepEqual(updates, ['中文', '中文回答'])
})

test('share URLs use the configured H5 page and encode the token', () => {
  const { client } = loadClient(async () => {})
  const url = new URL(client.publicShareUrl('token&x=1', 'https://example.com/'))
  assert.equal(url.pathname, '/')
  assert.equal(url.hash, '#/pages/public/public?token=token%26x%3D1')
})

test('embed and copied share link resolve to the same public page', () => {
  const { client } = loadClient(async () => {})
  const target = { appendChild(frame) { this.frame = frame } }
  const context = { window: {}, document: { querySelector: () => target, createElement: () => ({ style: {} }) } }
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../src/static/aiknowledge-embed.js'), 'utf8'), context)
  const iframe = context.window.AiKnowledgeEmbed.mount({ token: 'share-token', target: '#widget', publicUrl: 'https://example.com/' })
  assert.equal(iframe.src, client.publicShareUrl('share-token', 'https://example.com/'))
  assert.equal(target.frame, iframe)
})

test('V2 retrieval sends question and K to authenticated diagnostics without generation', async () => {
  const calls = []
  const { client } = loadClient(async (request) => {
    calls.push(request)
    return { statusCode: 201, data: { run_id: 'actual-run', items: [] } }
  })
  const run = await client.searchKnowledge('space-id', '范围规则', 5)
  assert.equal(run.run_id, 'actual-run')
  assert.ok(calls[0].url.endsWith('/owner/spaces/space-id/retrieval-runs'))
  assert.equal(calls[0].data.question, '范围规则')
  assert.equal(calls[0].data.top_k, 5)
  assert.equal(calls.length, 1)
})

test('keyword diagnostics transmit BM25 strategy without changing chat requests', async () => {
  const calls = []
  const { client } = loadClient(async (options) => { calls.push(options); return { statusCode: 201, data: { run_id: 'keyword' } } })
  await client.searchKnowledge('space', 'SCOPE_CHANGED', 5, undefined, 'bm25')
  assert.equal(calls.length, 1)
  assert.equal(calls[0].data.strategy, 'bm25')
  assert.match(calls[0].url, /retrieval-runs$/)
})

test('explicit hybrid handoff reaches owner generation and evaluation requests', async () => {
  const calls=[]
  const {client}=loadClient(async options=>{calls.push(options);return {statusCode:201,data:{answer:'真实响应',run_id:'run'}}})
  await client.streamOwnerAnswer('conversation','问题',()=>{},undefined,'hybrid')
  assert.equal(calls[0].data.strategy,'hybrid')
  await client.enqueueEvaluation('space','hybrid')
  assert.ok(calls[1].url.endsWith('/eval-runs/async?strategy=hybrid'))
})

test('V2 evaluation uses immediate async endpoints and polls the saved run', async () => {
  const calls = []
  const { client } = loadClient(async ({ url }) => {
    calls.push(url)
    return { statusCode: 202, data: { id: 'run-id', status: 'PENDING' } }
  })
  await client.enqueueEvaluation('space-id')
  await client.enqueueEvalVersion('version-id')
  await client.getEvalRun('run-id')
  await client.retryEvalRun('run-id')
  assert.ok(calls[0].endsWith('/spaces/space-id/eval-runs/async'))
  assert.ok(calls[1].endsWith('/eval-versions/version-id/runs/async'))
  assert.ok(calls[2].endsWith('/eval-runs/run-id'))
  assert.ok(calls[3].endsWith('/eval-runs/run-id/retry'))
})

test('scope revocation during SSE clears stale partial text and returns the explicit error', async () => {
  const { client } = loadClient(async () => {}, {
    fetch: async () => new Response('event: delta\ndata: {"text":"旧范围内容"}\n\nevent: error\ndata: {"code":"SCOPE_CHANGED","message":"范围已变化"}\n\n',
      { headers: { 'content-type': 'text/event-stream' } })
  })
  const updates = []
  await assert.rejects(client.streamPublicAnswer('c', '问题', text => updates.push(text)), { code: 'SCOPE_CHANGED', status: 409 })
  assert.deepEqual(updates, ['旧范围内容', ''])
})

test('an already-cancelled diagnostic request never reaches the API', async () => {
  let calls = 0
  const { client } = loadClient(async () => { calls++; return { statusCode: 200, data: {} } })
  const controller = new AbortController()
  controller.abort()
  await assert.rejects(client.searchKnowledge('s', '问题', 5, controller.signal), { code: 'REQUEST_ABORTED' })
  assert.equal(calls, 0)
})

test('failed V2 evaluation enqueue reports server failure without creating a completed result', async () => {
  let calls = 0
  const { client } = loadClient(async () => { calls++; return { statusCode: 503, data: { code: 'UNAVAILABLE', message: '服务暂时不可用' } } })
  await assert.rejects(client.enqueueEvaluation('space-id'), { code: 'UNAVAILABLE', status: 503 })
  assert.equal(calls, 1)
})

test('document evidence browsing uses the authenticated scoped detail endpoint without a query', async () => {
  const calls = []
  const { client } = loadClient(async request => { calls.push(request); return { statusCode: 200, data: { document: { id: 'doc-id' }, chunks: [], versions: [] } } })
  const result = await client.getOwnerDocumentDetail('space-id', 'doc-id')
  assert.equal(result.document.id, 'doc-id')
  assert.ok(calls[0].url.endsWith('/owner/spaces/space-id/documents/doc-id'))
  assert.equal(calls.length, 1)
})

test('API requests bypass previously cached SPA responses', async () => {
  const optionsSeen = []
  const { client } = loadClient(async (options) => {
    optionsSeen.push(options)
    return { statusCode: 200, data: { items: [] } }
  })
  await client.listSpaces()
  assert.equal(optionsSeen[0].cache, 'reload')
})

test('retrieval allows cold model initialization and reports a timeout explicitly', async () => {
  let seen
  const { client } = loadClient(async options => {
    seen = options
    throw { errMsg: 'request:fail timeout' }
  })
  await assert.rejects(client.searchKnowledge('space', '检索问题', 5), { code: 'REQUEST_TIMEOUT' })
  assert.equal(seen.timeout, 660000)
})

test('H5 fetch timeout is distinct from an explicit user cancellation', async () => {
  const { client } = loadClient(async () => { throw { name: 'AbortError', message: 'The user aborted a request.' } })
  await assert.rejects(client.searchKnowledge('space', '检索问题'), { code: 'REQUEST_TIMEOUT' })
  const controller = new AbortController()
  controller.abort()
  await assert.rejects(client.searchKnowledge('space', '检索问题', 5, controller.signal), { code: 'REQUEST_ABORTED' })
})


test('real rerank strategy reaches diagnostic owner answer and frozen evaluation', async () => {
  const calls=[]
  const {client}=loadClient(async options=>{calls.push(options);return {statusCode:201,data:{answer:'响应',run_id:'actual'}}})
  await client.searchKnowledge('space','问题',5,undefined,'hybrid_rerank')
  await client.streamOwnerAnswer('conversation','问题',()=>{},undefined,'hybrid_rerank')
  await client.enqueueEvaluation('space','hybrid_rerank')
  assert.equal(calls[0].data.strategy,'hybrid_rerank')
  assert.equal(calls[1].data.strategy,'hybrid_rerank')
  assert.ok(calls[2].url.endsWith('strategy=hybrid_rerank'))
})
