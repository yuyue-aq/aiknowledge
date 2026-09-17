import type { Category, EvalCase, Feedback, KnowledgeDocument, Space } from '../api/client'

export const demoSpaceId = '8c0c8e2c-1f4c-4f27-a4f2-3c21e1f8f401'
export const demoPublicSpaceId = '8c0c8e2c-1f4c-4f27-a4f2-3c21e1f8f402'

export const demoSpaces: Space[] = [
  {
    id: demoSpaceId,
    name: '个人项目资料',
    description: '记录个人项目相关的文档、方案与沉淀。',
    visibility: 'PRIVATE',
    guest_feedback_enabled: false,
    created_at: '2024-06-18T10:24:00+08:00',
    updated_at: '2024-06-20T16:40:00+08:00'
  },
  {
    id: demoPublicSpaceId,
    name: '团队产品手册',
    description: '团队协作的产品资料与规范文档。',
    visibility: 'PUBLIC',
    guest_feedback_enabled: false,
    created_at: '2024-06-16T10:24:00+08:00',
    updated_at: '2024-06-18T16:40:00+08:00'
  },
  {
    id: '8c0c8e2c-1f4c-4f27-a4f2-3c21e1f8f403',
    name: '学习笔记',
    description: '课程、阅读与技术笔记整理。',
    visibility: 'PRIVATE',
    guest_feedback_enabled: false,
    created_at: '2024-06-10T10:24:00+08:00',
    updated_at: '2024-06-10T16:40:00+08:00'
  }
]

export const demoCategories: Category[] = [
  {
    id: '9c0c8e2c-1f4c-4f27-a4f2-3c21e1f8f401',
    space_id: demoPublicSpaceId,
    name: '项目经验',
    description: '包含项目方案、技术实现与成果。',
    is_open: true,
    sort_order: 1,
    created_at: '2024-06-16T10:24:00+08:00',
    updated_at: '2024-06-18T16:40:00+08:00'
  },
  {
    id: '9c0c8e2c-1f4c-4f27-a4f2-3c21e1f8f402',
    space_id: demoPublicSpaceId,
    name: '产品介绍',
    description: '包含产品功能、使用说明与常见问题。',
    is_open: true,
    sort_order: 2,
    created_at: '2024-06-16T10:24:00+08:00',
    updated_at: '2024-06-18T16:40:00+08:00'
  },
  {
    id: '9c0c8e2c-1f4c-4f27-a4f2-3c21e1f8f403',
    space_id: demoPublicSpaceId,
    name: '个人工作经历',
    description: '包含工作经历、技能总结与成长记录。',
    is_open: false,
    sort_order: 3,
    created_at: '2024-06-16T10:24:00+08:00',
    updated_at: '2024-06-18T16:40:00+08:00'
  }
]

export const demoDocuments: KnowledgeDocument[] = [
  {
    id: 'ac0c8e2c-1f4c-4f27-a4f2-3c21e1f8f401',
    space_id: demoSpaceId,
    category_id: null,
    original_filename: '产品说明.pdf',
    mime_type: 'application/pdf',
    size_bytes: 12_400_000,
    status: 'READY',
    active_version_id: 'bc0c8e2c-1f4c-4f27-a4f2-3c21e1f8f401',
    failure_code: null,
    failure_message: null,
    created_at: '2024-06-18T10:24:00+08:00',
    updated_at: '2024-06-18T10:28:00+08:00'
  },
  {
    id: 'ac0c8e2c-1f4c-4f27-a4f2-3c21e1f8f402',
    space_id: demoSpaceId,
    category_id: null,
    original_filename: '项目复盘.docx',
    mime_type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    size_bytes: 8_700_000,
    status: 'PROCESSING',
    active_version_id: null,
    failure_code: null,
    failure_message: null,
    created_at: '2024-06-18T10:25:00+08:00',
    updated_at: '2024-06-18T10:26:00+08:00'
  },
  {
    id: 'ac0c8e2c-1f4c-4f27-a4f2-3c21e1f8f403',
    space_id: demoSpaceId,
    category_id: null,
    original_filename: '扫描资料.pdf',
    mime_type: 'application/pdf',
    size_bytes: 3_100_000,
    status: 'FAILED',
    active_version_id: null,
    failure_code: 'EMBEDDING_FAILED',
    failure_message: '向量服务暂时不可用，请稍后重试。',
    created_at: '2024-06-18T10:26:00+08:00',
    updated_at: '2024-06-18T10:27:00+08:00'
  }
]

export const demoEvalCases: EvalCase[] = [
  {
    id: 'ec0c8e2c-1f4c-4f27-a4f2-3c21e1f8f401',
    space_id: demoSpaceId,
    question: '这个产品主要解决什么问题？',
    expected_answer: '帮助团队从私有资料中快速找到可信答案。',
    expected_document_ids: [demoDocuments[0].id],
    scope: 'OWNER',
    category_ids: [],
    created_at: '2024-06-20T09:00:00+08:00'
  },
  {
    id: 'ec0c8e2c-1f4c-4f27-a4f2-3c21e1f8f402',
    space_id: demoSpaceId,
    question: '访客能否读取关闭分类？',
    expected_answer: '不能，公开检索只包含已开放分类。',
    expected_document_ids: [],
    scope: 'OUT_OF_SCOPE',
    category_ids: [],
    created_at: '2024-06-20T09:00:00+08:00'
  }
]

export const demoFeedback: Feedback[] = [
  {
    id: 'fc0c8e2c-1f4c-4f27-a4f2-3c21e1f8f401',
    message_id: 'mc0c8e2c-1f4c-4f27-a4f2-3c21e1f8f401',
    rating: 'DOWN',
    reason: 'OFF_TOPIC',
    comment: '希望增加更具体的实现步骤。',
    is_guest: false,
    created_at: '2024-06-20T14:32:00+08:00'
  },
  {
    id: 'fc0c8e2c-1f4c-4f27-a4f2-3c21e1f8f402',
    message_id: 'mc0c8e2c-1f4c-4f27-a4f2-3c21e1f8f402',
    rating: 'NEEDS_CORRECTION',
    reason: 'OUTDATED',
    comment: '请确认保存期限是否已经更新。',
    is_guest: false,
    created_at: '2024-06-19T10:18:00+08:00'
  },
  {
    id: 'fc0c8e2c-1f4c-4f27-a4f2-3c21e1f8f403',
    message_id: 'mc0c8e2c-1f4c-4f27-a4f2-3c21e1f8f403',
    rating: 'UP',
    reason: null,
    comment: null,
    is_guest: false,
    created_at: '2024-06-17T11:20:00+08:00'
  }
]
