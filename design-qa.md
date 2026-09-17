# UI 验收记录

日期：2026-09-12

## 已完成

- `python .../audit_project.py . --mode strict`：0 errors / 0 warnings。
- `npx tsc --noEmit --skipLibCheck`：通过。
- `npx eslint src/pages/index/index.tsx src/api/client.ts --max-warnings=0`：通过。
- `npx -p @google/design.md designmd lint DESIGN.md`：0 errors / 0 warnings（1 条 token-summary 信息）。
- `npm run build:h5`：通过，Taro 4.2.1 生成生产产物；认证卡宽度、输入层级规则已进入产物。
- `npm run build:weapp`：通过，生成微信小程序页面产物。
- 本轮追加 `npx tsc --noEmit`、`npm run build:h5`、`npm run build:weapp`：均通过；编译产物分别保留 `taro-input-core` 与 `.h5-input` 的居中规则。

## 本轮视觉修复

- 认证双栏改为稳定的内容比例，认证卡桌面最大宽度收敛为 360px，表单控件回到 40px 桌面基线并保留移动端触控空间。
- Taro `Button` 默认 100% 宿主宽度改为共享按钮内容宽度；密码显示按钮使用 mini 尺寸并关闭默认伪边框，避免覆盖密码输入框。
- 认证说明组与卡片标题/描述统一落在各自容器中心轴；输入宿主固定高度并清除上下内边距，按钮统一明确行高和双轴居中，修复文字在框内偏移。
- 右下角截图中的黑黄“英/简/半”条未在 `src` 或构建产物中出现，属于操作系统输入法/浏览器浮层，非小程序页面层。

## 浏览器验收阻塞

已尝试通过 Codex 桌面浏览器打开本地 H5 页面，但当前会话的浏览器清单返回空，且底层 `nodeRepl.fetch` 报错，因此无法取得可验证的页面截图或可访问性树。该环境限制不影响静态审计、类型检查和生产构建结果；启动浏览器后应按 `UX-CONTRACT.md` 的验证列逐页检查登录入口、空间 CRUD、上传失败/重试、所有者引用、公开 token 边界和移动端底部导航。

## 2026-09-15 回归补充

- frontend-design-premium strict audit：0 errors / 0 warnings。
- `npx tsc --noEmit --skipLibCheck`：通过；`npx eslint src`：通过。
- Owner/Public 问答新增 SSE `delta → answer → done` 事件；生成中按钮可停止请求，移动端仍保留 JSON 降级。
- 对话恢复优先读取服务端空间列表，避免只依赖本地缓存；后端同步增加 GET 对话列表和安全限流/Origin 响应头。
- 真实浏览器截图仍需在 Docker/浏览器服务恢复后补做；本轮未改变原型视觉 token 和页面比例。
