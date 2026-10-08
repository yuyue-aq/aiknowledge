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
