---
version: alpha
name: "知溯"
description: "面向中文团队的可信知识工作台，以蓝图式层次和可追溯证据承载资料管理与问答。"
colors:
  primary: "#2F6FED"
  primary-dark: "#1D59C9"
  navy: "#0D213D"
  background: "#F3F7FD"
  surface: "#FFFFFF"
  border: "#D9E4F3"
  muted: "#6B7D98"
  success: "#0F9F8F"
  warning: "#F0A020"
  danger: "#C24156"
typography:
  sans:
    fontFamily: "MiSans, PingFang SC, Microsoft YaHei, sans-serif"
  mono:
    fontFamily: "ui-monospace, SFMono-Regular, Consolas, monospace"
rounded:
  DEFAULT: "9px"
  sm: "8px"
  md: "12px"
  lg: "18px"
spacing:
  section-gap: "24px"
  page-max: "1380px"
components:
  button: { minHeight: "40px", radius: "9px" }
  card: { radius: "14px", shadow: "var(--shadow-card)" }
  input: { minHeight: "40px", radius: "9px" }
  toast: { zIndex: "80", duration: "4s" }
---

# 知溯 Design System

## Overview

### Creative North Star

知溯像一张铺在桌面上的蓝色资料蓝图：深海军蓝负责结构，钴蓝负责可执行动作，薄冰蓝背景让白色资料卡和证据片段保持清晰。每个空间、分类和回答都像蓝图上的一块可定位图层。

### Product context and register

- **Audience and primary job:** 中文团队的知识空间所有者整理资料、校验公开范围，并获得带引用的可靠回答；访客只在分享范围内提问。
- **Target market(s) and evidence:** 中文本地化的知识管理 MVP；产品命名、界面文案和原型均来自 `需求分析文档.md`、`MVP第一版方案.md` 与 `UI原型图-A方案-优化版/最终版/`。
- **Locale(s) and language policy:** 简体中文为主，模型名、状态枚举和文件扩展名保留技术原文；未提供英文切换。
- **Usage scene:** 桌面端管理密集资料，移动端快速查看状态和追问；长回答独立滚动，输入区保持可见。
- **Register:** 安静、可信的工作台；公开访客页使用同一色彩系统但隐藏所有私有来源。
- **Memorable signature:** 回答旁的“回答依据”面板，以及公开页的薄荷绿范围提示。
- **Restraint:** 不使用装饰性渐变背景、霓虹色、过度圆角或与证据无关的动效。
- **Anti-references:** 不做聊天气泡堆叠式社交产品，不做玻璃拟态仪表盘；它们会削弱资料层级和引用可信度。
- **Token ownership/runtime mapping:** `src/app.scss` 是运行时 token 唯一来源；本文件镜像其具体值，组件通过 CSS 变量消费，不另建主题生成器。

## Colors

`--ice` 是全局工作台底色，`--surface` 是资料层；`--navy` 只用于主要文本和结构，`--cobalt` 只用于主动作、链接和焦点环。薄荷绿表示已开放或成功，琥珀表示资料不足/处理中，红色只表示失败、撤销和停止生成。边框使用 `--line`，避免纯黑分割线。浅色主题是 MVP 唯一主题；焦点环使用半透明钴蓝并保持 3px 可见度。

## Typography

中文正文使用 MiSans/PingFang SC/Microsoft YaHei 回退栈，标题使用 HarmonyOS Sans SC；数字和模型标识可使用 Inter/Arial。标题 800、正文 400–600、操作按钮 700–800。回答正文行高约 1.85，资料列表和表格保持 1.55。中文标点不强制大写，状态标签使用产品既定中文词汇；长文件名使用省略号并保留完整值的可访问名称。

## Layout

桌面端固定 198px 深色侧栏，工作区最大宽度 1380px，顶部栏高 74px；内容区采用 34px/42px 内边距和 24px 区块间距。移动端在 760px 以下隐藏侧栏，改用底部 67px 导航，内容边距降至 14–16px。问答主区和引用面板必须保持独立滚动，不让 sticky 顶栏或输入区遮挡最后一条消息；上传、生成和错误状态都占据稳定的最小高度。

## Elevation & Depth

层次主要来自冰蓝/白色调差、`--line` 边框和两级柔和阴影；卡片阴影为 `--shadow-card`，大型容器可用 `--shadow-soft`。侧栏是唯一深色表面，公开页不使用漂浮模态。停止生成按钮采用红色实心而不增加额外阴影，以明确其状态性质。

## Shapes

资料卡 14px、面板 12px、字段和普通按钮 9px、品牌标记 10–13px；公开访客输入框为胶囊形，状态标签为 999px。头像和机器人标记为圆形。分割线 1px，图标容器与文字基线对齐，不能用圆角遮盖输入焦点。

## Components

### Foundational visual states

按钮默认实心钴蓝/白底描边，hover 只改变颜色或轻微上移 1px，focus-visible 使用全局焦点环，pressed 保持原几何尺寸，disabled 降低不透明度且不移动。上传、评测和问答使用稳定的 busy 文案；停止生成是 busy 状态的可操作出口。成功/警告/错误均同时使用颜色、图标和中文文字，不依赖单一颜色。

### Buttons and actions

主操作使用 `.primary-button`，次操作 `.outline-button`，删除/停止使用 `.danger-button` 或 `.stop-button`，图标按钮必须有 `aria-label`。按钮最小高度 40px，紧凑变体 32px；生成中的停止按钮不禁用，保持可点击。

### Navigation and data display

侧栏、空间页签和移动底栏共享 active 语义；资料、反馈和评测在桌面使用表格/卡片组合，移动端转为卡片并允许横向滚动。状态胶囊显示“处理中/已就绪/失败/已撤销”等稳定词汇。

### Forms and overlays

字段标签位于输入上方，错误文本紧邻字段或表单顶部；上传进度与后台轮询状态使用内联提示。删除前使用确认对话框（组件由页面 action 层提供），toast 固定右下角并保留 4 秒；公开边界失效使用独立页面而不是遮罩。

### Iconography

`src/components/Icon.tsx` 提供项目内 Unicode glyph 图标族，默认 18–22px、Arial 粗体，图标只增强含义；所有关键动作保留文字或 aria-label，不能用图标单独表达危险操作。

### Motion

动效只反馈状态：卡片 hover 200ms、生成点脉冲 1.5s、页面元素不做持续漂浮。停止或取消立即中断请求并清除 busy 文案；实现 `prefers-reduced-motion` 时应移除 transform 和 pulse。

### Content and data visualization

产品文案短句、具体、避免夸大；模型回答可拒答但不可伪造依据。文件大小使用 B/KB/MB，时间使用 `zh-CN` 24 小时制，分数保留后端给出的精度。质量自测同时展示回答状态和引用数量，无法只靠颜色判断。

## Do's and Don'ts

- **Do:** 把当前空间、公开范围和回答依据放在用户可见的层级上。
- **Do:** 所有异步操作提供明确的处理中、成功、失败和重试路径。
- **Don't:** 不把公开访客响应中的私有文件名、引用片段或下载入口渲染出来。
- **Don't:** 不用全屏弹层、夸张渐变或自动播放动效打断问答。
