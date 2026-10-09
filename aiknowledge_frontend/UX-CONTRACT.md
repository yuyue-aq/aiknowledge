# UX Contract

## Product context

- Audience: 知识空间所有者与通过分享链接访问的访客。
- Primary jobs: 整理资料、控制公开分类、进行带证据问答、查看反馈与质量自测。
- Target market(s): 中文团队内部知识协作与受控公开问答。
- Active locales: zh-CN。
- Language/content register and native-review policy: 简体中文工作台语气；状态和错误文案由产品需求文档维护。
- Timezone/calendar policy: 浏览器本地时区，日期显示 `zh-CN`。
- Accessibility target: WCAG 2.2 AA。

## Business-context sources

| Domain / scope | Authoritative source | Source type | Reviewed date |
|---|---|---|---|
| Permission model | `MVP第一版方案.md` §8、§12 | Product/permission spec | 2026-09-15 |
| Data lifecycle | `MVP第一版方案.md` §10 | API/domain spec | 2026-09-15 |
| Deletion / retention | `MVP第一版方案.md` §12.4 | Product acceptance criteria | 2026-09-15 |
| Billing / payment | Not in MVP | Out of scope | 2026-09-15 |
| Legal / regulatory copy | `需求分析文档.md` | Product brief | 2026-09-15 |
| Market / content conventions | `需求分析文档.md`、`UI原型图-A方案-优化版/最终版/` | Product brief / visual reference | 2026-09-15 |

## Visual contract

- Project `DESIGN.md`: `DESIGN.md`。
- Token ownership model (`DESIGN.md` generated / existing runtime canonical): Existing runtime canonical.
- Runtime design-system/token source: `src/app.scss` CSS variables。
- Mapping/export/adapters: 本次 MVP 仅 H5，Taro 编译 React/CSS；用户已排除小程序。
- Token drift gate: 手工核对 `DESIGN.md` 与 `src/app.scss`，并运行 frontend-design-premium `audit_project.py`。
- Supported themes: 浅色主题；系统深色主题不在 MVP 范围。
- Design-context owner/review policy: 页面新增组件必须复用现有 token、状态和间距，视觉改动需对照最终原型复核。

## Canonical UI Map

| Capability | Canonical owner | Source of truth | Allowed variants | Verification |
|---|---|---|---|---|
| Table Selection | 反馈/评测页面 | `index.tsx` | page results | keyboard + typecheck |
| Select/Listbox | native | H5 select（V2）/ Taro Picker（沿用 V1） | 分类、题集、Top K 共用原生选择语义 | keyboard + H5 responsive |
| Date | 列表时间 | `formatDate` | typed display | locale smoke |
| Form | 空间、分类、分享、上传 | page form components | create/edit | validation/API tests |
| Scrollbar | 工作区与问答 | `src/app.scss` | stable scroll regions | responsive build |
| Toast | `AppToast` | `index.tsx` | success/warning/info/error | live `role=status` |
| CRUD | space/document/category/share | page action handlers | return-to-workspace | API + failure paths |

## Component behavior

| Component | Default | Hover | Focus | Active | Disabled | Busy | Error |
|---|---|---|---|---|---|---|---|
| Button | token color, 40px | color/1px lift | 3px focus ring | same geometry | opacity .58 | stable label | toast/inline |
| Icon button | transparent | tinted surface | focus ring | same size | opacity .58 | disabled while mutation | aria-label |
| Input | bordered white | border cobalt | focus ring | caret visible | opacity .58 | preserved value | inline field text |
| Secret input | masked | border cobalt | focus ring | toggle visibility | opacity .58 | not applicable | never echo value |
| Search | clear + immediate | border cobalt | focus ring | query retained | opacity .58 | not applicable | empty state |
| Textarea | resize none | border unchanged | focus ring | input retained | disabled while generating | stop button remains enabled | question error |
| Table/list | stable rows | row tint | row focus | selected tint | n/a | skeleton/empty copy | retry action |

## Dataset navigation

- Admin tables: 反馈和评测结果。
- Exploratory lists: 空间、资料、分类和分享链接。
- URL state: 当前 MVP 使用页面状态；不把私有内容放进 URL。
- Page size: MVP 一次加载当前空间数据；后续分页由 API contract 决定。
- Empty/no-results/error/loading treatment: 空状态提供下一步提示；错误提供重试；加载保留稳定占位高度。
- Back/scroll restoration: 返回空间保留当前空间；移动端底栏不覆盖输入和回答末尾。
- Selection scope: 当前页面结果；批量操作不在 MVP。

## Flow ledger

| Operation | Trigger | Pending | Success destination | Success feedback | Failure recovery | Focus outcome | Source ref |
|---|---|---|---|---|---|---|---|
| Create | 新建空间/分类/对话 | button busy | 当前空间/问答 | success toast | inline error, keep values | action button | `MVP第一版方案.md` §9 |
| Edit | 保存设置/分类 | button busy | 当前页面 | success toast | keep editor open | field remains | `MVP第一版方案.md` §8 |
| Delete | 删除资料/对话/链接 | confirm + busy | list refresh | success toast | retry | return to row | `MVP第一版方案.md` §12 |
| Search | 顶部搜索 | immediate | filtered list | no toast | empty state | query retained | UI prototype |
| Bulk action | Not in MVP | n/a | n/a | n/a | n/a | n/a | scope note |
| Upload/background job | file select | progress + poll | document list | ready toast | retry failed doc | row remains visible | `MVP第一版方案.md` §10 |
| Cancel/back | stop generation/back | AbortController | composer/previous page | no error toast | retry question | input remains usable | `MVP开发计划.md` §11.7 |
| Soft-delete | revoke/delete | confirm | list hides item | success toast | retry | next visible row | `MVP第一版方案.md` §12.4 |
| Hard-delete (irreversible) | Not exposed in MVP | n/a | n/a | n/a | n/a | n/a | scope note |

## Navigation and responsive behavior

- Route document title policy: `登录/知识空间/可信问答/资料管理/回答反馈/质量自测/空间设置 · 知溯`。
- Route error / 403 page behavior: 公开链接失效显示边界页面并允许重新输入 token；工作台错误保留页面并提供 toast/重试。
- Breadcrumb/tab/route-state policy: SpaceHeader tabs control workspace page; public page is a separate route。
- Sidebar/drawer/bottom-sheet transformation: fixed desktop sidebar becomes 67px mobile bottom bar。
- Responsive table strategy: grid rows become cards or horizontal-scroll tables below 760px。
- Truncation/full-value access: file names truncate visually, accessible label retains full value。
- Focus restoration and sticky-obstruction policy: actions keep focus; composer remains after long-answer scroll。

## Overlays and feedback

- Dialog primitive: Taro Button/View confirmation pattern owned by page action layer。
- Destructive confirmation levels: delete document/conversation/link requires explicit confirm。
- Toast placement/duration/deduplication: bottom-right, 4s, one current toast。
- Alert/banner scope and persistence: scope and model notes remain until state changes。
- Tooltip delay/dismissal: aria-label for icon-only controls; no hover-only critical content。
- Unsaved-changes behavior: preserve editor values on API failure; no silent navigation。
- Layer/z-index contract: dialog > sidebar/topbar > toast; toast uses 80。

## Async and resilience

- Mutation default: optimistic document row with server reconciliation; other mutations pessimistic。
- Idempotency and duplicate-submit policy: disable mutation buttons while busy; question composer disables duplicate send and exposes stop。
- Auto-save/draft recovery: conversation id stored per space; composer text is not persisted。
- Offline/read-stale/write behavior: API errors show demo data only in explicit demo/local IDs; real-space mutations surface errors。
- Retry/backoff/timeout behavior: document polling uses bounded 2s retries; model client has configured timeout/retry。
- Version conflict and multi-tab behavior: server remains source of truth; refresh list after mutation。
- Session expiry/re-authentication: Owner 401 最多刷新重试一次，保持用户的“记住我”选择；退出或更换账户后，旧刷新响应不得恢复/覆盖会话；Public 401/403 只处理访客会话，不清除 Owner 登录。
- Long-running progress and return path: document processing remains visible and can retry; generation shows incremental text。
- Stale-request cancellation/invalidation and pending-state ownership: AbortController belongs to page; unmount and stop cancel active stream。
- Dialog/form preservation and retry after mutation failure: retain values and show a targeted retry action。

## Validation

- Schema/validation layer: Pydantic backend schemas and lightweight page guards。
- Trigger timing: trim on submit; field length and required checks at submit。
- Error summary/inline policy: route-level request errors use toast; field errors stay beside fields。
- Server error mapping: `ApiRequestError` maps status/code to stable Chinese copy。
- Sensitive-value handling: never render share token in toast or public response; cookie is HttpOnly。
- `noValidate`, first-invalid focus, duplicate-submit prevention, unsaved changes, and submit recovery: button busy state prevents duplicate submits; failed forms keep input for retry。

## Permission and clipboard

- Permission UI strategy (hide vs disable vs 403 page): hide private source fields on public DTO/UI; expired public scope uses a 403 boundary page。
- Clipboard copy policy: share token is copied only from the explicit share dialog; toast confirms action without printing secret。
- Disabled-state explanation: disabled controls retain nearby busy/error text; icon controls have labels。

## Verification

- Required static commands: `npx tsc --noEmit --skipLibCheck`; `npm run build:h5`; `npx eslint src`; `npm run lint:style`。
- Browser/device/locale/theme matrix: H5 desktop and ≤760px mobile widths, zh-CN, light theme。
- Accessibility checks: keyboard focus-visible, labels/aria-live, contrast review of token palette。
- Native-language/domain review and target-user evidence: compare all copy with `需求分析文档.md` and final prototype。
- Component-state/visual regression coverage: inspect login/workspace/public/loading/error/busy screenshots after build。
- Canonical sibling flow used for comparison: owner QA and public QA share composer spacing and stream state semantics。
- Project audit command/result: `python .../frontend-design-premium/scripts/audit_project.py aiknowledge_frontend --mode strict` after this contract is committed。
- CRUD full-flow evidence: backend pytest plus runtime scripts when Docker dependencies are available。
- Failure-path evidence: API 401/403/404/429/5xx mappings, aborted stream, failed document and revoked share link tests。
- 2026-09-30 regression evidence: `npm test`（18 项）；`tests/browser-v1-smoke.js`（合成 API 浏览器 7 项）。真实空间变更失败不得创建演示结果或宣称成功；创建空间/分类失败保留输入。分享/嵌入统一使用 `/#/pages/public/public?token=...`。


## 2026-10-02 已确认的个人与团队权限补充

用户确认：个人空间仅有拥有者，拥有者同时承担管理员职责；团队空间有一位拥有者，可有多位管理员。团队管理员可查看原文引用、使用检索调试、管理资料与评测。访客仍只能在分享范围内提问，不能获取原文。此决议覆盖前文将上述管理能力仅限拥有者的描述。

空间类型 `PERSONAL / TEAM` 与可见性、套餐配额独立。新建时选择类型，类型暂不支持转换。团队创建默认使用现有 TEAM 演示配额（50 人），个人默认 FREE 配额；当前没有支付或自动扣费。已有 TEAM 配额或非拥有者成员的空间迁移为团队，其他空间归为个人。

拥有者仍独占成员邀请、角色分配、空间删除和分享设置；管理员不能自行提升为拥有者。编辑者与成员保留原有授权范围，管理员降级或移除后立即失去检索调试权限。后台强制校验，前端仅对团队拥有者显示成员邀请及角色调整控件。空间创建沿用原型中的分段按钮和极昼蓝样式，不变更既有版式。


## P1阶段A关键词检索（2026-10-07）

权限依据V2需求/方案2026-10-02补充：空间拥有者与团队管理员可诊断，访客/普通成员不可读取原文。复用RetrievalView、V2UI控件及原生H5选择器，弹出菜单由操作系统拥有；保持极昼蓝token不变。查询保留页面状态，不放入URL。方式/Top K/问题编辑取消旧请求并清空旧结果，清空按钮恢复输入焦点；仅显式提交和Enter查询，IME确认不提交。BM25分数与余弦分开标注，阶段A不改变问答策略。真实浏览器验收脚本eval/p1/bm25/ui_check.cjs。

## P1阶段B混合检索（2026-10-08）

复用批准原型05后续扩展的向量/BM25/RRF三列布局；760px以下依次堆叠，页面自然滚动，原文在下方来源面板查看。三路均使用真实服务结果，空分支明确显示无可用片段；融合分数保留六位并注明不是正确概率。各路候选按片段ID去重，排名不等于答案依据完整性。

选择混合方式后，“用此问题去问答”明确传递hybrid；问答页显示本次方式并提供恢复向量检索操作。空间切换重置为Dense。质量自测使用同一原生选择器明确选择Dense或Hybrid，策略冻结在运行快照中，后台Worker复用问答检索实现。历史引用统一称排序分数，不能把RRF误称为余弦相似度。

输入清空、空问题焦点、IME、参数变化取消、错误重试与阶段A一致。三路结果归属于同一个请求，任何参数改变均同时失效，避免把不同问题的排名拼接。真实浏览器证据由eval/p1/rrf/ui_check.cjs生成。


## P1阶段C真实重排（2026-10-08）
复用05原型两列重排前/后布局和极昼蓝tokens，760px以下自然堆叠。重排关闭维持RRF顺序，开启仅改变同一50条池的排序后再截断；模型原始分数单独标识，不是正确概率。显式“混合检索 + 模型重排”在检索、问答和评测共享语义；生成期间不能切换当前模式。
加载可能较长，保留问题并展示busy/首次加载提示，取消请求及参数变更清空两列旧结果；模型失败明确错误，不伪造分数或静默回退。成功数据必须来自已固定模型，来源面板显示完整当前原文。私有问题不写入URL，选择器仍由原生H5控件拥有。

## P1阶段D结构分块预览（2026-10-09）
沿用批准05原型两列对照、V2Panel/V2Heading、原生H5选择器及现有资料详情。左侧是当前活动版本实际已存片段，右侧是同源文件的所选策略预览；不伪装旧版本一定是长度策略。结果分页，每列12条，列明总数，点击片段显示完整正文及原文区间。私人正文及配置草稿不写URL或持久化浏览器存储。
修改策略/预算/重叠立即取消旧请求并清空预览，显式提交才重新计算；错误保留配置、允许重试。预览只读，不计算向量，不激活版本。应用通过现有ConfirmDialog确认新版本影响，提交中禁止改配置或重复提交；成功返回资料详情并跟踪Worker，新版本可用前继续使用旧版本。没有变化的配置禁止重复重建。所有权限、活动版本、时间及停用规则继续由服务端强制检查。

## P1阶段I资料更新影响诊断（2026-10-09）
质量自测页提供只读诊断：列出证据标注指向旧版本或当前不可用资料的回归题，并统计历史回答引用受影响范围；历史回答与评测快照不被自动修改。诊断接口只允许空间拥有者与团队管理员使用，服务端强制鉴权，不返回引用原文。需要修复的回归题由管理员进入编辑页重新选择当前证据。

“资料冲突”与“资料不足”分开核对：比较最近一次已完成运行的冻结题集预期标注和实际回答状态，分别报告正确、误分类及准确率。没有已完成运行或没有相应标注时显示空值，不把未标注题当作正确，也不依据模型答案自动改变人工标准。

## P1阶段H公开稿审核（2026-10-09）
在公开设置中沿用现有设置卡片与极昼蓝控件，管理者可编辑问题、标准答案、开放分类和可选来源资料。团队管理员可以建稿、编辑、送审及审核；只有拥有者可以发布或撤回。编辑已发布稿会立即撤下旧快照并回到草稿状态；来源资料更新后显示撤回原因，管理员重新关联当前资料版本并送审。

每个新分享链接可选“原文资料检索（默认）”或“仅检索已发布问答”。旧链接仍按原文资料检索，页面清楚标出已存链接的模式。选择仅已发布问答时，访客回答展示已审核问答自身的依据片段，不展示私有来源文件名、原始文档内容或内部调试信息。公开设置说明关联来源用途；窄屏下问答编辑器和审核列表自然纵向排列。

## P1阶段J访客常见问题（2026-10-09）
访客打开“仅检索已发布问答”的链接时，在空对话状态展示最多6条当前分享范围、开放分类内的已发布问题；不提前展示答案或来源资料。问题来自已发布快照，过滤条件与正常问答相同，包括分享链接状态、空间可见性、分类开放状态和关联来源版本有效性。点选问题会发起一次正常访客问答，仍执行实时范围校验并显示已审核问答引用。

“原文资料检索”链接继续使用既有通用示例问题，不显示已审核稿FAQ。常见问题查询失败时仍可进入空间，允许直接输入问题；没有已发布问题时显示明确空状态。窄屏沿用现有公开问答建议卡片布局。

## P1阶段K产品内辅助评测（2026-10-09）
评测详情中由管理者逐题显式请求模型评分建议，不自动批量调用。发送题目、冻结的标准答案/预期行为和实际回答至空间配置的模型，不发送原文片段。界面将建议分与人工评分分区展示；生成、失败和缺少冻结标注均有明确状态。失败尝试保留并允许重试，成功建议不会重复调用；建议不会自动写入人工分，也不计入答案准确率。

模型建议、人工评分、评分覆盖率和建议/人工一致率分别呈现；一致率只在两者都有结果的题目上计算，不能描述成模型准确率。历史题目必须使用运行时冻结标注；若旧运行没有标注快照，跳过评分并说明需要新建运行。团队管理员沿用评测管理权限，普通成员和访客不得读取或生成评分建议。
