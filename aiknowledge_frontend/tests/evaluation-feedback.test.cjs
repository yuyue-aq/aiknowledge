const { test } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('typescript')

const source = ts.createSourceFile('EvaluationView.tsx', fs.readFileSync(path.join(__dirname, '../src/components/EvaluationView.tsx'), 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
function callbacks(ports) {
  const definitions = {}
  function visit(node) {
    if (ts.isVariableDeclaration(node) && ['save', 'perform'].includes(node.name.getText(source))) definitions[node.name.getText(source)] = node.initializer.getText(source)
    ts.forEachChild(node, visit)
  }
  visit(source)
  const code = ts.transpileModule(`const perform = ${definitions.perform}; const save = ${definitions.save}; save`, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText
  return vm.runInNewContext(code, ports)
}
function scenario(changes = {}) {
  const errors = [], calls = [], destinations = [], focus = []
  const ports = {
    draft: { question: '用户原始问题', expected_answer: '人工修正答案', scope: 'OWNER', category_ids: [],
      answerable: true, expected_behavior: 'ANSWERED', expected_document_ids: ['doc-1'], evidence_refs: [{ document_id: 'doc-1' }],
      source_feedback_id: 'feedback-1', source_feedback_confirmed: true, ...changes },
    spaceId: 'space-1', mutating: { current: false }, alive: { current: true },
    setError: value => errors.push(value), setBusy: () => {}, failureText: error => error.message,
    document: { getElementById: id => ({ focus: () => focus.push(id) }) },
    createEvalCaseFromFeedback: async (...args) => { calls.push(['feedback', ...args]); return { id: 'case-1' } },
    createEvalCase: async (...args) => { calls.push(['generic', ...args]); return { id: 'case-1' } },
    updateEvalCase: async (...args) => { calls.push(['update', ...args]); return { id: 'case-1' } },
    setCases: () => {}, setPage: page => destinations.push(page), notify: () => {},
  }
  return { ports, errors, calls, destinations, focus }
}
test('source conversion requires an intentional confirmation before submitting', async () => {
  const state = scenario({ source_feedback_confirmed: false })
  await callbacks(state.ports)()
  assert.equal(state.calls.length, 0)
  assert.match(state.errors.at(-1), /确认/)
  assert.equal(state.focus.at(-1), 'source-feedback-confirmed')
})
test('answerable source conversion requires selected evidence', async () => {
  const state = scenario({ evidence_refs: [] })
  await callbacks(state.ports)()
  assert.equal(state.calls.length, 0)
  assert.match(state.errors.at(-1), /证据/)
})
test('confirmed source conversion creates one linked case through the source endpoint', async () => {
  const state = scenario()
  await callbacks(state.ports)()
  assert.equal(state.calls.length, 1)
  assert.equal(state.calls[0][0], 'feedback')
  assert.equal(state.calls[0][2], 'feedback-1')
  assert.equal(state.calls[0][3].source_feedback_confirmed, true)
  assert.deepEqual(state.destinations, ['cases'])
})
test('editing an existing linked case uses update without attempting a second conversion', async () => {
  const state = scenario({ id: 'case-1', source_feedback_confirmed: false })
  await callbacks(state.ports)()
  assert.equal(state.calls[0][0], 'update')
  assert.deepEqual(state.destinations, ['cases'])
})
test('duplicate-source conflict preserves the source editor and reports the server error', async () => {
  const state = scenario()
  state.ports.createEvalCaseFromFeedback = async () => { throw new Error('这条反馈已经加入回归题集。') }
  await callbacks(state.ports)()
  assert.deepEqual(state.destinations, [])
  assert.match(state.errors.at(-1), /已经加入/)
})
