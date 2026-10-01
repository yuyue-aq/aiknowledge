# 离线原型交互约定

所有业务动作仅模拟。公开页面不显示私密原文、检索分数和内部文档路径。删除、撤销、改变开放范围与公开稿审核需要确认；原型确认不执行真实操作。

## Canonical UI Map

| Capability | Canonical owner | Source of truth | Allowed variants | Verification |
| --- | --- | --- | --- | --- |
| Table Selection | native checkbox | assets/prototype.js | checked/unchecked | keyboard and pointer |
| Select/Listbox | native select | assets/prototype.js | single | keyboard selection |
| Date | native | assets/prototype.js | static date text only | no date picker |
| Form | shared submit handler | assets/prototype.js | retrieval/chat/feedback/case | empty error and simulated submit |
| Scrollbar | native | assets/prototype.css | table/body/dialog | mobile overflow |
| Toast | toast() | assets/prototype.js | success/info | visible in active dialog |
| CRUD | confirmAction() | assets/prototype.js | simulated only | cancel/confirm/focus restore |

空输入有内联提示；处理中禁用主动作；弹窗支持 Escape、焦点约束和关闭后焦点恢复。手机保留主要任务和底部导航。画廊缩略图 inert，仅「查看」可进入交互。
