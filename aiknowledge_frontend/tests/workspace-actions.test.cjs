const { test } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('typescript')

// Execute the actual page callbacks with state/API ports. No copied business logic.
const source = ts.createSourceFile('index.tsx', fs.readFileSync(path.join(__dirname, '../src/pages/index/index.tsx'), 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
function loadAction(name, ports) {
  let callback
  function visit(node) {
    if (ts.isVariableDeclaration(node) && node.name.getText(source) === name) callback = node.initializer.arguments[0]
    ts.forEachChild(node, visit)
  }
  visit(source)
  assert.ok(callback, `missing callback ${name}`)
  const code = ts.transpileModule(`const action = ${callback.getText(source)}; action`, {
    compilerOptions: { target: ts.ScriptTarget.ES2022 }
  }).outputText
  return vm.runInNewContext(code, ports)
}

for (const [name, api, args] of [
  ['handleToggleCategory', 'updateCategory', [{ id: 'category', space_id: 'real-space', is_open: true }]],
  ['handleRevoke', 'revokeShareLink', [{ id: 'share', space_id: 'real-space' }]],
  ['handleVisibilityChange', 'updateSpace', ['PRIVATE']],
  ['handleCreateCategory', 'createCategory', ['分类']],
  ['handleShare', 'createShareLink', []],
  ['handleFeedback', 'sendFeedback', ['real-message', 'HELPFUL']],
  ['handleCreateSpace', 'createSpace', [{ name: '空间', description: '', visibility: 'PRIVATE' }]]
]) {
  test(`${name}: failed real request keeps state and reports error`, async () => {
    const changes = []
    const toasts = []
    const ports = {
      currentSpace: { id: 'real-space', visibility: 'PUBLIC' }, categories: [], evalCases: [], usingDemo: false,
      isDemoSpace: () => false, localId: () => 'local', now: () => 'now', ApiRequestError: Error,
      [api]: async () => { throw new Error('服务暂时不可用') },
      setToast: (value) => toasts.push(value), setLoadingEval: () => {}, setCreating: () => {}, setFeedbackBusy: () => {},
      loadSpaceData: async () => changes.push('loadSpaceData')
    }
    for (const setter of ['setCategories', 'setShareLinks', 'setCurrentSpace', 'setSpaces', 'setUsingDemo', 'setEvalResult', 'setEvalRuns']) ports[setter] = () => changes.push(setter)
    await loadAction(name, ports)(...args)
    assert.deepEqual(changes, [])
    assert.equal(toasts.at(-1)?.tone, 'error')
  })
}

test('category success applies returned server state', async () => {
  const category = { id: 'category', space_id: 'real-space', is_open: true }
  let state = [category]
  const toasts = []
  const action = loadAction('handleToggleCategory', {
    updateCategory: async () => ({ ...category, is_open: false }), isDemoSpace: () => false,
    setCategories: (update) => { state = update(state) }, setToast: (value) => toasts.push(value)
  })
  await action(category)
  assert.equal(state[0].is_open, false)
  assert.equal(toasts.at(-1).tone, 'info')
})
