import { Button, Input, Picker, Text, Textarea, View } from "@tarojs/components";
import Taro, { useLoad, useRouter } from "@tarojs/taro";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  ApiRequestError,
  createCategory,
  createOwnerConversation,
  createShareLink,
  createSpace,
  deleteDocument,
  formatDate,
  formatFileSize,
  getDocument,
  getOwnerConversation,
  listOwnerConversations,
  listCategories,
  listDocuments,
  listEvalCases,
  listFeedback,
  listShareLinks,
  listSpaces,
  retryDocument,
  runEvaluation,
  sendFeedback,
  streamOwnerAnswer,
  updateCategory,
  updateSpace,
  uploadDocument,
  revokeShareLink,
  type AnswerStatus,
  type Category,
  type Citation,
  type CreatedShareLink,
  type ConversationDetail,
  type EvalCase,
  type EvalDetail,
  type Feedback,
  type FeedbackRating,
  type KnowledgeDocument,
  type ShareLink,
  type Space,
  type SpaceVisibility,
  type UploadFile,
} from "../../api/client";
import { AppShell, type WorkspacePage } from "../../components/AppShell";
import { Icon } from "../../components/Icon";
import {
  demoCategories,
  demoDocuments,
  demoEvalCases,
  demoFeedback,
  demoSpaces,
  demoSpaceId,
} from "../../mock/data";
import "./index.scss";

type ToastTone = "success" | "info" | "warning" | "error";
type ToastState = { tone: ToastTone; message: string } | null;

type LocalMessage = {
  id: string;
  role: "USER" | "ASSISTANT";
  content: string;
  status?: AnswerStatus;
  model?: string | null;
  citations: Citation[];
  created_at: string;
};

const now = () => new Date().toISOString();
const localId = (prefix: string) =>
  `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;

const isLocalDemoId = (value: string | null | undefined) =>
  Boolean(value && (value === demoSpaceId || /^(space|document|conversation|assistant|user)-/.test(value)));

const ownerConversationStorageKey = (spaceId: string) =>
  `aiknowledge.owner-conversation.${spaceId}`;

function toLocalMessages(detail: ConversationDetail): LocalMessage[] {
  return detail.messages.map((message) => ({
    id: message.id,
    role: message.role === "USER" ? "USER" : "ASSISTANT",
    content: message.content,
    status: message.status ?? undefined,
    model: message.model,
    citations: message.citations,
    created_at: message.created_at,
  }));
}

function valueOf(event: any) {
  return event.detail?.value ?? event.currentTarget?.value ?? "";
}

function AppToast({ toast }: { toast: ToastState }) {
  if (!toast) return null;
  return (
    <View
      className={`app-toast toast-${toast.tone}`}
      role={toast.tone === "error" ? "alert" : "status"}
    >
      {toast.message}
    </View>
  );
}

function AuthView({
  onEnter,
  onPublic,
}: {
  onEnter: () => void;
  onPublic: () => void;
}) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = () => {
    if (mode === "register" && !name.trim()) {
      setError("请输入你的称呼。");
      return;
    }
    if (!email.trim() || !email.includes("@")) {
      setError("请输入有效的邮箱地址。");
      return;
    }
    if (password.length < 6) {
      setError("密码至少需要 6 个字符。");
      return;
    }
    setError("");
    setBusy(true);
    // 用户系统按要求保留为独立模块；当前 MVP 使用本地工作区入口。
    setTimeout(() => {
      setBusy(false);
      onEnter();
    }, 260);
  };

  return (
    <View className='auth-page'>
      <View className='auth-hero'>
        <View className='auth-brand'>
          <View className='brand-mark brand-mark-large'>
            <Text>知</Text>
          </View>
          <View>
            <Text className='brand-name'>知溯</Text>
            <Text className='brand-caption'>可信知识工作台</Text>
          </View>
        </View>
        <View className='auth-hero-copy'>
          <Text className='auth-eyebrow'>让私人知识成为可依赖的力量</Text>
          <Text className='auth-title'>
            从记录到分享，
            <Text className='auth-title-accent'>都有证据可循。</Text>
          </Text>
          <Text className='auth-subtitle'>
            把分散的资料交给一个懂边界的问答工作台。
          </Text>
        </View>
        <View className='auth-trust-list'>
          <TrustItem
            icon='search'
            title='来源可追溯'
            text='每个答案都有可回看的依据'
          />
          <TrustItem
            icon='lock'
            title='范围受控制'
            text='你的知识只在授权范围内使用'
          />
          <TrustItem
            icon='file'
            title='资料不足会拒答'
            text='不编造、不翻涌，诚实可靠'
          />
        </View>
        <View className='hero-wave' aria-hidden='true' />
      </View>
      <View className='auth-card-wrap'>
        <View
          className='auth-card'
          role='form'
          aria-label={mode === "login" ? "登录知溯" : "注册知溯"}
        >
          <Text className='auth-card-title'>
            {mode === "login" ? "欢迎回来" : "创建工作区"}
          </Text>
          <Text className='auth-card-desc'>
            {mode === "login"
              ? "登录知溯，继续你的知识工作"
              : "先创建一个本地工作区，稍后可接入授权系统"}
          </Text>
          {mode === "register" && (
            <Field label='称呼' id='auth-name'>
              <Input
                id='auth-name'
                value={name}
                placeholder='请输入你的称呼'
                onInput={(e) => {
                  setName(valueOf(e));
                  setError("");
                }}
                aria-label='称呼'
              />
            </Field>
          )}
          <Field label='邮箱' id='auth-email'>
            <Input
              id='auth-email'
              type='text'
              value={email}
              placeholder='请输入邮箱'
              onInput={(e) => {
                setEmail(valueOf(e));
                setError("");
              }}
              aria-label='邮箱'
              onConfirm={submit}
            />
          </Field>
          <Field label='密码' id='auth-password'>
            <View className='secret-input'>
              <Input
                id='auth-password'
                type='text'
                password={!showPassword}
                value={password}
                placeholder='请输入密码'
                onInput={(e) => {
                  setPassword(valueOf(e));
                  setError("");
                }}
                aria-label='密码'
                onConfirm={submit}
              />
              <Button
                className='input-action'
                size='mini'
                onClick={() => setShowPassword((current) => !current)}
                aria-label={showPassword ? "隐藏密码" : "显示密码"}
                aria-pressed={showPassword}
              >
                {showPassword ? "隐藏" : "显示"}
              </Button>
            </View>
          </Field>
          {mode === "login" && (
            <View className='auth-options'>
              <Text className='remember-copy'>
                <Text className='checkbox-mock' aria-hidden='true' />
                记住我
              </Text>
              <Button
                className='text-button'
                onClick={() => setError("密码找回将在授权系统接入后开放。")}
              >
                忘记密码?
              </Button>
            </View>
          )}
          {error && <Text className='field-error'>{error}</Text>}
          <Button
            className='primary-button auth-submit'
            onClick={submit}
            disabled={busy}
            aria-busy={busy}
          >
            {busy ? "正在进入…" : mode === "login" ? "登录" : "创建并进入"}
          </Button>
          <View className='auth-switch'>
            <Text>{mode === "login" ? "还没有账号？" : "已经有工作区？"}</Text>
            <Button
              className='text-button'
              onClick={() => {
                setMode(mode === "login" ? "register" : "login");
                setError("");
              }}
            >
              {mode === "login" ? "注册" : "返回登录"}
            </Button>
          </View>
          <View className='auth-divider'>
            <Text>或</Text>
          </View>
          <Button className='outline-button guest-entry' onClick={onPublic}>
            <Icon name='globe' />
            使用公开访问链接
          </Button>
          <Text className='auth-note'>
            授权系统已预留目录，当前版本先验证知识库与模型闭环。
          </Text>
        </View>
      </View>
    </View>
  );
}

function TrustItem({
  icon,
  title,
  text,
}: {
  icon: "search" | "lock" | "file";
  title: string;
  text: string;
}) {
  return (
    <View className='trust-item'>
      <View className='trust-icon'>
        <Icon name={icon} />
      </View>
      <View>
        <Text className='trust-title'>{title}</Text>
        <Text className='trust-text'>{text}</Text>
      </View>
    </View>
  );
}

function Field({
  label,
  id,
  children,
}: {
  label: string;
  id: string;
  children: ReactNode;
}) {
  return (
    <View className='field'>
      <Text className='field-label' aria-label={`${label}输入框`}>
        {label}
      </Text>
      <View id={id}>{children}</View>
    </View>
  );
}

function StatusPill({
  status,
  children,
}: {
  status:
    | "ready"
    | "processing"
    | "failed"
    | "private"
    | "public"
    | "warning"
    | "neutral";
  children: ReactNode;
}) {
  return (
    <Text className={`status-pill status-${status}`}>
      {status === "ready" && <Icon name='check' />}
      {status === "processing" && <Icon name='retry' />}
      {status === "failed" && <Icon name='close' />}
      {status === "private" && <Icon name='lock' />}
      {status === "public" && <Icon name='globe' />}
      {status === "warning" && <Icon name='warning' />}
      {children}
    </Text>
  );
}

function EmptyState({
  title,
  description,
  action,
  onAction,
}: {
  title: string;
  description: string;
  action?: string;
  onAction?: () => void;
}) {
  return (
    <View className='empty-state'>
      <View className='empty-icon'>
        <Icon name='folder' />
      </View>
      <Text className='empty-title'>{title}</Text>
      <Text className='empty-description'>{description}</Text>
      {action && onAction && (
        <Button className='outline-button' onClick={onAction}>
          {action}
        </Button>
      )}
    </View>
  );
}

function LoadingState({ label = "正在加载…" }: { label?: string }) {
  return (
    <View className='loading-state'>
      <View className='loading-dot' />
      <Text>{label}</Text>
    </View>
  );
}

function SpacesView({
  spaces,
  currentSpace,
  loading,
  error,
  creating,
  onSelect,
  onCreate,
  onRetry,
}: {
  spaces: Space[];
  currentSpace: Space | null;
  loading: boolean;
  error: string;
  creating: boolean;
  onSelect: (space: Space) => void;
  onCreate: (input: {
    name: string;
    description: string;
    visibility: SpaceVisibility;
  }) => Promise<void>;
  onRetry: () => void;
}) {
  const [showCreate, setShowCreate] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [visibility, setVisibility] = useState<SpaceVisibility>("PRIVATE");
  const [formError, setFormError] = useState("");
  const submitCreate = async () => {
    if (!name.trim()) {
      setFormError("请填写空间名称。");
      return;
    }
    setFormError("");
    await onCreate({
      name: name.trim(),
      description: description.trim(),
      visibility,
    });
    setName("");
    setDescription("");
    setShowCreate(false);
  };
  return (
    <View className='page-stack'>
      <View className='page-heading'>
        <View>
          <Text className='page-kicker'>我的知识工作台</Text>
          <Text className='page-title'>知识空间</Text>
          <Text className='page-description'>
            管理你的知识空间，让知识生产更大价值
          </Text>
        </View>
        <Button
          className='primary-button'
          onClick={() => setShowCreate((open) => !open)}
        >
          <Icon name='plus' />
          新建空间
        </Button>
      </View>
      {error && (
        <View className='inline-banner banner-warning' role='alert'>
          <Icon name='warning' />
          <Text>{error}</Text>
          <Button className='text-button' onClick={onRetry}>
            重试
          </Button>
        </View>
      )}
      {showCreate && (
        <View className='inline-editor' role='region' aria-label='新建知识空间'>
          <View className='editor-heading'>
            <View>
              <Text className='section-title'>新建空间</Text>
              <Text className='section-description'>
                先选择资料的默认可见范围，之后仍可调整。
              </Text>
            </View>
            <Button
              className='icon-button'
              onClick={() => setShowCreate(false)}
              aria-label='关闭新建空间'
            >
              <Icon name='close' />
            </Button>
          </View>
          <View className='editor-grid'>
            <Field label='空间名称' id='new-space-name'>
              <Input
                id='new-space-name'
                value={name}
                placeholder='例如：产品知识库'
                onInput={(e) => {
                  setName(valueOf(e));
                  setFormError("");
                }}
                aria-label='空间名称'
              />
            </Field>
            <View className='field'>
              <Text className='field-label'>可见范围</Text>
              <View
                className='segmented-control'
                role='radiogroup'
                aria-label='空间可见范围'
              >
                <Button
                  className={
                    visibility === "PRIVATE" ? "segment is-selected" : "segment"
                  }
                  onClick={() => setVisibility("PRIVATE")}
                  aria-pressed={visibility === "PRIVATE"}
                >
                  <Icon name='lock' />
                  私密空间
                </Button>
                <Button
                  className={
                    visibility === "PUBLIC" ? "segment is-selected" : "segment"
                  }
                  onClick={() => setVisibility("PUBLIC")}
                  aria-pressed={visibility === "PUBLIC"}
                >
                  <Icon name='globe' />
                  公开空间
                </Button>
              </View>
            </View>
            <Field label='描述（可选）' id='new-space-description'>
              <Textarea
                className='resize-none'
                id='new-space-description'
                value={description}
                placeholder='描述这个空间收纳的内容'
                onInput={(e) => setDescription(valueOf(e))}
                aria-label='空间描述'
              />
            </Field>
          </View>
          {formError && <Text className='field-error'>{formError}</Text>}
          <View className='editor-actions'>
            <Button
              className='outline-button'
              onClick={() => setShowCreate(false)}
            >
              取消
            </Button>
            <Button
              className='primary-button'
              onClick={() => void submitCreate()}
              disabled={creating}
              aria-busy={creating}
            >
              {creating ? "创建中…" : "创建空间"}
            </Button>
          </View>
        </View>
      )}
      <View className='metric-row'>
        <Metric label='全部空间' value={spaces.length} />
        <Metric label='我创建的' value={spaces.length} />
        <Metric label='与我共享' value={0} />
        <View className='metric-spacer' />
        <View className='model-badge'>
          <View className='model-dot' />
          <Text>deepseek-flash</Text>
          <Text className='model-sub'>BGE 1024d</Text>
        </View>
      </View>
      {loading ? (
        <LoadingState label='正在加载空间…' />
      ) : spaces.length === 0 ? (
        <EmptyState
          title='还没有知识空间'
          description='创建第一个空间，把资料整理成可追溯的答案。'
          action='新建空间'
          onAction={() => setShowCreate(true)}
        />
      ) : (
        <View className='space-grid'>
          {spaces.map((space) => (
            <SpaceCard
              key={space.id}
              space={space}
              selected={currentSpace?.id === space.id}
              onSelect={onSelect}
            />
          ))}
        </View>
      )}
      <View className='model-note'>
        <Icon name='info' />
        <Text>
          当前 MVP 暂以单工作区模式运行，授权/用户目录已保留；问答使用 DeepSeek
          Flash，向量模型为 BAAI/bge-large-zh-v1.5（1024 维）。
        </Text>
      </View>
    </View>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <View className='metric'>
      <Text className='metric-value'>{value}</Text>
      <Text className='metric-label'>{label}</Text>
    </View>
  );
}

function SpaceCard({
  space,
  selected,
  onSelect,
}: {
  space: Space;
  selected: boolean;
  onSelect: (space: Space) => void;
}) {
  return (
    <Button
      className={`space-card ${selected ? "is-selected" : ""}`}
      onClick={() => onSelect(space)}
    >
      <View
        className={`space-icon ${space.visibility === "PUBLIC" ? "space-icon-public" : ""}`}
      >
        <Icon name={space.visibility === "PUBLIC" ? "team" : "folder"} />
      </View>
      <View className='space-card-main'>
        <View className='space-card-title-row'>
          <Text className='space-card-title'>{space.name}</Text>
          <StatusPill
            status={space.visibility === "PUBLIC" ? "public" : "private"}
          >
            {space.visibility === "PUBLIC" ? "公开" : "私密"}
          </StatusPill>
        </View>
        <Text className='space-card-description'>
          {space.description || "还没有空间描述。"}
        </Text>
        <View className='space-card-meta'>
          <Text>
            <Icon name='file' />
            资料待同步
          </Text>
          <Text>最近更新 {formatDate(space.updated_at)}</Text>
        </View>
      </View>
      <Icon name='arrow' className='space-card-arrow' />
    </Button>
  );
}

function SpaceHeader({
  space,
  page,
  onBack,
  onPage,
}: {
  space: Space;
  page: WorkspacePage;
  onBack: () => void;
  onPage: (page: WorkspacePage) => void;
}) {
  return (
    <View className='space-header'>
      <View className='breadcrumbs'>
        <Button className='breadcrumb-button' onClick={onBack}>
          知识空间
        </Button>
        <Text>/</Text>
        <Text>{space.name}</Text>
      </View>
      <View className='space-header-row'>
        <View>
          <Text className='page-title'>
            {page === "documents"
              ? "资料管理"
              : page === "feedback"
                ? "回答反馈"
                : page === "eval"
                  ? "质量自测"
                  : page === "settings"
                    ? "空间设置"
                    : "项目知识库"}
          </Text>
          <Text className='page-description'>
            {page === "documents"
              ? "上传并管理你的私有资料，构建专属知识库"
              : page === "qa"
                ? "基于你的资料，提供可信、可追溯的回答"
                : page === "feedback"
                  ? "收集反馈，持续优化回答质量"
                  : page === "eval"
                    ? "用典型问题验证回答效果与权限边界"
                    : "控制空间可见性与访客可检索的内容范围"}
          </Text>
        </View>
        <View className='workspace-tabs' role='tablist' aria-label='空间功能'>
          <Button
            className={
              page === "qa" ? "workspace-tab is-active" : "workspace-tab"
            }
            onClick={() => onPage("qa")}
            aria-selected={page === "qa"}
          >
            问答
          </Button>
          <Button
            className={
              page === "documents" ? "workspace-tab is-active" : "workspace-tab"
            }
            onClick={() => onPage("documents")}
            aria-selected={page === "documents"}
          >
            资料
          </Button>
          <Button
            className={
              page === "feedback" ? "workspace-tab is-active" : "workspace-tab"
            }
            onClick={() => onPage("feedback")}
            aria-selected={page === "feedback"}
          >
            反馈
          </Button>
          <Button
            className={
              page === "eval" ? "workspace-tab is-active" : "workspace-tab"
            }
            onClick={() => onPage("eval")}
            aria-selected={page === "eval"}
          >
            评测
          </Button>
          <Button
            className={
              page === "settings" ? "workspace-tab is-active" : "workspace-tab"
            }
            onClick={() => onPage("settings")}
            aria-selected={page === "settings"}
          >
            公开设置
          </Button>
        </View>
      </View>
    </View>
  );
}

function DocumentsView({
  space,
  documents,
  categories,
  error,
  onUpload,
  onDelete,
  onRetry,
}: {
  space: Space;
  documents: KnowledgeDocument[];
  categories: Category[];
  error: string;
  onUpload: (
    file: UploadFile,
    categoryId: string | null,
    onProgress: (progress: number) => void,
  ) => Promise<void>;
  onDelete: (document: KnowledgeDocument) => Promise<void>;
  onRetry: (document: KnowledgeDocument) => Promise<void>;
}) {
  const fileInput = useRef<HTMLInputElement>(null);
  const [selectedCategory, setSelectedCategory] = useState<string>("");
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [fileError, setFileError] = useState("");
  const accept = ".pdf,.docx,.md,.markdown,.txt";
  const categoryOptions = ["不指定分类", ...categories.map((category) => category.name)];
  const selectedCategoryIndex = selectedCategory
    ? Math.max(0, categories.findIndex((category) => category.id === selectedCategory) + 1)
    : 0;
  const handleFile = async (file: UploadFile | null) => {
    if (!file) return;
    const extension = `.${file.name.split(".").pop()?.toLowerCase()}`;
    if (!accept.split(",").includes(extension)) {
      setFileError("仅支持 PDF、DOCX、Markdown、TXT 文件。");
      return;
    }
    if (file.size === 0 || file.size > 20 * 1024 * 1024) {
      setFileError("文件不能为空，且单文件不超过 20 MB。");
      return;
    }
    setFileError("");
    setUploading(true);
    setProgress(0);
    try {
      await onUpload(file, selectedCategory || null, setProgress);
    } finally {
      setUploading(false);
      setProgress(0);
      if (fileInput.current) fileInput.current.value = "";
    }
  };
  const openPicker = async () => {
    if (process.env.TARO_ENV === "h5") {
      fileInput.current?.click();
      return;
    }
    try {
      const result = await Taro.chooseMessageFile({
        count: 1,
        type: "file",
        extension: ["pdf", "docx", "md", "markdown", "txt"],
      });
      await handleFile(result.tempFiles[0] ?? null);
    } catch {
      setFileError("无法打开文件选择器，请重试。");
    }
  };
  return (
    <View className='page-stack documents-page'>
      <View className='upload-toolbar'>
        <View>
          <Text className='section-title'>资料管理</Text>
          <Text className='section-description'>
            {space.name} · 处理完成后才会进入问答检索范围
          </Text>
        </View>
        <View className='upload-category'>
          <Text className='field-label'>归入分类</Text>
          <Picker
            mode='selector'
            range={categoryOptions}
            value={selectedCategoryIndex}
            onChange={(event) => {
              const index = Number(event.detail.value);
              setSelectedCategory(index > 0 ? categories[index - 1]?.id ?? "" : "");
            }}
          >
            <View className='select-like' aria-label='选择文档分类'>
              <Text>{categoryOptions[selectedCategoryIndex]}</Text>
              <Text>⌄</Text>
            </View>
          </Picker>
        </View>
      </View>
      <View
        className={`drop-zone ${uploading ? "is-uploading" : ""}`}
        role='button'
        aria-label='选择资料文件，可拖拽上传'
        onClick={() => {
          if (!uploading) void openPicker();
        }}
      >
        <input
          ref={fileInput}
          className='native-file-input'
          type='file'
          accept={accept}
          onChange={(event) => void handleFile(event.target.files?.[0] ?? null)}
          aria-label='选择资料文件'
        />
        <View className='upload-icon'>
          <Icon name='upload' />
        </View>
        <Button
          className='drop-picker-button'
          onClick={(event) => {
            event.stopPropagation?.();
            if (!uploading) void openPicker();
          }}
          disabled={uploading}
        >
          选择文件
        </Button>
        <Text className='drop-title'>
          {uploading
            ? `正在上传 ${progress ? `${progress}%` : ""}`
            : "选择文件上传"}
        </Text>
        <Text className='drop-hint'>
          支持 PDF、DOCX、Markdown、TXT，单文件不超过 20 MB
        </Text>
        {uploading && (
          <View className='progress-track'>
            <View
              className='progress-bar'
              style={{ width: `${Math.max(progress, 8)}%` }}
            />
          </View>
        )}
      </View>
      {fileError && (
        <View className='inline-banner banner-error' role='alert'>
          <Icon name='warning' />
          <Text>{fileError}</Text>
        </View>
      )}
      {error && (
        <View className='inline-banner banner-warning' role='alert'>
          <Icon name='warning' />
          <Text>{error}</Text>
        </View>
      )}
      <View className='list-heading'>
        <Text className='section-title'>上传队列（{documents.length}/20）</Text>
        <Text className='muted-copy'>可逐个查看处理状态与失败原因</Text>
      </View>
      {documents.length === 0 ? (
        <EmptyState
          title='还没有资料'
          description='把第一份资料放进空间，开始建立可验证的知识来源。'
        />
      ) : (
        <View className='document-list'>
          {documents.map((document) => (
            <DocumentRow
              key={document.id}
              document={document}
              onDelete={onDelete}
              onRetry={onRetry}
            />
          ))}
        </View>
      )}
    </View>
  );
}

function DocumentRow({
  document,
  onDelete,
  onRetry,
}: {
  document: KnowledgeDocument;
  onDelete: (document: KnowledgeDocument) => Promise<void>;
  onRetry: (document: KnowledgeDocument) => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const status =
    document.status === "READY"
      ? "ready"
      : document.status === "FAILED"
        ? "failed"
        : "processing";
  const action = async (
    callback: (document: KnowledgeDocument) => Promise<void>,
  ) => {
    setBusy(true);
    try {
      await callback(document);
    } finally {
      setBusy(false);
    }
  };
  return (
    <View className='document-row'>
      <View
        className={`document-type ${document.mime_type.includes("word") ? "docx" : "pdf"}`}
      >
        <Icon name='file' />
      </View>
      <View className='document-main'>
        <Text className='document-name'>{document.original_filename}</Text>
        <Text className='document-meta'>
          {formatFileSize(document.size_bytes)} ·{" "}
          {formatDate(document.created_at)}
        </Text>
        {document.failure_message && (
          <Text className='document-error'>{document.failure_message}</Text>
        )}
      </View>
      <View className='document-status'>
        <StatusPill status={status}>
          {document.status === "READY"
            ? "可用"
            : document.status === "FAILED"
              ? "处理失败"
              : document.status === "PENDING"
                ? "排队中"
                : "处理中"}
        </StatusPill>
        {(document.status === "PENDING" || document.status === "PROCESSING") && (
          <View className='mini-progress'>
            <View className='mini-progress-bar' />
          </View>
        )}
      </View>
      <View className='document-actions'>
        {document.status === "FAILED" && (
          <Button
            className='outline-button compact'
            onClick={() => void action(onRetry)}
            disabled={busy}
          >
            {busy ? "重试中…" : "重试"}
          </Button>
        )}
        <Button
          className='danger-button compact'
          onClick={() => void action(onDelete)}
          disabled={busy}
          aria-label={`删除 ${document.original_filename}`}
        >
          删除
        </Button>
      </View>
    </View>
  );
}

function QaView({
  messages,
  streaming,
  streamingText,
  onSend,
  onCancel,
  onFeedback,
  feedbackBusy,
}: {
  messages: LocalMessage[];
  streaming: boolean;
  streamingText: string;
  onSend: (question: string) => Promise<void>;
  onCancel: () => void;
  onFeedback: (messageId: string, rating: FeedbackRating) => Promise<void>;
  feedbackBusy: string | null;
}) {
  const [input, setInput] = useState("");
  const send = () => {
    if (streaming) {
      onCancel();
      return;
    }
    const question = input.trim();
    if (!question) return;
    setInput("");
    void onSend(question);
  };
  const lastAssistant = [...messages]
    .reverse()
    .find((message) => message.role === "ASSISTANT");
  return (
    <View className='qa-layout'>
      <View className='qa-main'>
        <View className='qa-toolbar'>
          <View>
            <Text className='section-title'>项目知识库</Text>
            <Text className='section-description'>
              基于当前空间资料，提供可信、可追溯的回答
            </Text>
          </View>
          <View className='qa-model'>
            <View className='model-dot' />
            <Text>DeepSeek Flash</Text>
            <Text className='muted-copy'>检索 Top 4</Text>
          </View>
        </View>
        <View className='scope-banner'>
          <Icon name='lock' />
          <Text>当前为所有者问答，可查看完整引用与来源位置</Text>
        </View>
        <View className='messages' aria-live='polite'>
          {messages.length === 0 && (
            <View className='qa-empty'>
              <View className='bot-avatar'>
                <Text>知</Text>
              </View>
              <Text className='qa-empty-title'>从一份资料开始提问</Text>
              <Text className='qa-empty-copy'>
                试试：“这个产品主要解决什么问题？”
              </Text>
              <Button
                className='suggestion-chip'
                onClick={() => setInput("这个产品主要解决什么问题？")}
              >
                这个产品主要解决什么问题？
              </Button>
            </View>
          )}
          {messages.map((message) => (
            <MessageBubble
              key={message.id}
              message={message}
              onFeedback={onFeedback}
              feedbackBusy={feedbackBusy}
            />
          ))}
          {streaming && (
            <View className='message-row assistant-row'>
              <View className='bot-avatar'>
                <Text>知</Text>
              </View>
              <View className='assistant-bubble'>
                <Text className='answer-label'>
                  <Icon name='retry' />
                  正在检索可信资料
                </Text>
                <Text className='message-content'>
                  {streamingText || "正在根据当前空间检索…"}
                </Text>
                <View className='typing-dots' aria-label='正在生成回答'>
                  <Text />
                  <Text />
                  <Text />
                </View>
              </View>
            </View>
          )}
        </View>
        <View className='question-composer'>
          <Icon name='link' />
          <Textarea
            className='resize-none'
            value={input}
            onInput={(event) => setInput(valueOf(event))}
            onConfirm={send}
            disabled={streaming}
            placeholder='继续追问当前空间…（Enter 发送，Shift+Enter 换行）'
            aria-label='输入你的问题'
          />
          <Button
            className={streaming ? "stop-button" : "send-button"}
            onClick={send}
            disabled={!streaming && !input.trim()}
            aria-busy={streaming}
            aria-label={streaming ? "停止生成" : "发送问题"}
          >
            {streaming ? "停止" : <Icon name='send' />}
          </Button>
        </View>
      </View>
      <CitationPanel
        citations={lastAssistant?.citations ?? []}
        status={lastAssistant?.status}
      />
    </View>
  );
}

function MessageBubble({
  message,
  onFeedback,
  feedbackBusy,
}: {
  message: LocalMessage;
  onFeedback: (messageId: string, rating: FeedbackRating) => Promise<void>;
  feedbackBusy: string | null;
}) {
  if (message.role === "USER")
    return (
      <View className='message-row user-row'>
        <View className='user-bubble'>
          <Text>{message.content}</Text>
          <Text className='message-time'>{formatTime(message.created_at)}</Text>
        </View>
        <View className='user-avatar'>林</View>
      </View>
    );
  return (
    <View className='message-row assistant-row'>
      <View className='bot-avatar'>
        <Text>知</Text>
      </View>
      <View
        className={`assistant-bubble answer-${(message.status ?? "ANSWERED").toLowerCase()}`}
      >
        {message.status === "INSUFFICIENT_EVIDENCE" && (
          <View className='answer-state state-warning'>
            <View className='state-icon'>
              <Icon name='warning' />
            </View>
            <View>
              <Text className='state-title'>资料不足</Text>
              <Text>当前资料中没有足够依据回答这个问题。</Text>
            </View>
          </View>
        )}
        {message.status === "OUT_OF_SCOPE" && (
          <View className='answer-state state-warning'>
            <View className='state-icon'>
              <Icon name='lock' />
            </View>
            <View>
              <Text className='state-title'>超出当前范围</Text>
              <Text>这个问题不在当前知识空间的可检索范围内。</Text>
            </View>
          </View>
        )}
        {message.status === "CONFLICT" && (
          <View className='answer-state state-error'>
            <View className='state-icon'>
              <Icon name='warning' />
            </View>
            <View>
              <Text className='state-title'>发现冲突</Text>
              <Text>不同资料中存在相互矛盾的信息，请查看来源。</Text>
            </View>
          </View>
        )}
        <Text className='answer-label'>
          <Icon
            name={
              message.status === "ANSWERED" || !message.status
                ? "check"
                : "warning"
            }
          />
          {message.status === "ANSWERED" || !message.status
            ? "基于资料回答"
            : "需要进一步处理"}
        </Text>
        <Text className='message-content'>{message.content}</Text>
        <Text className='message-time'>
          {formatTime(message.created_at)} ·{" "}
          {message.model || "deepseek-flash"}
        </Text>
        <View className='message-actions'>
          <Button
            className='icon-button'
            onClick={() => void onFeedback(message.id, "UP")}
            disabled={feedbackBusy === message.id}
            aria-label='回答有帮助'
          >
            <Icon name='thumbUp' />
          </Button>
          <Button
            className='icon-button'
            onClick={() => void onFeedback(message.id, "DOWN")}
            disabled={feedbackBusy === message.id}
            aria-label='回答没有帮助'
          >
            <Icon name='thumbDown' />
          </Button>
          <Button
            className='icon-button'
            onClick={() => void onFeedback(message.id, "NEEDS_CORRECTION")}
            disabled={feedbackBusy === message.id}
            aria-label='需要修正'
          >
            <Icon name='feedback' />
          </Button>
        </View>
      </View>
    </View>
  );
}

function CitationPanel({
  citations,
  status,
}: {
  citations: Citation[];
  status?: AnswerStatus;
}) {
  return (
    <View className='citation-panel'>
      <View className='citation-heading'>
        <View>
          <Text className='section-title'>回答依据</Text>
          <Text className='section-description'>
            所有者可查看原文片段与位置
          </Text>
        </View>
        <StatusPill status={citations.length ? "ready" : "neutral"}>
          {citations.length ? `${citations.length} 条来源` : "暂无来源"}
        </StatusPill>
      </View>
      {status === "CONFLICT" && (
        <View className='conflict-note'>
          <Icon name='warning' />
          <Text>请逐条对照冲突来源后再做判断。</Text>
        </View>
      )}
      {citations.length === 0 ? (
        <View className='citation-empty'>
          <Icon name='file' />
          <Text>当回答没有足够证据时，系统会明确拒答。</Text>
        </View>
      ) : (
        <View className='citation-list'>
          {citations.map((citation) => (
            <View
              className='citation-card'
              key={`${citation.document_name}-${citation.ordinal}`}
            >
              <View className='citation-index'>{citation.ordinal}</View>
              <View>
                <Text className='citation-name'>
                  {citation.document_name}
                  {citation.page_number
                    ? ` · 第 ${citation.page_number} 页`
                    : ""}
                </Text>
                <Text className='citation-text'>“{citation.quoted_text}”</Text>
                <Text className='citation-score'>
                  相关度 {Math.round(citation.score * 100)}%
                </Text>
              </View>
              <Icon name='arrow' />
            </View>
          ))}
        </View>
      )}
    </View>
  );
}

function PublicSettingsView({
  space,
  categories,
  links,
  onToggle,
  onCreateCategory,
  onShare,
  onRevoke,
}: {
  space: Space;
  categories: Category[];
  links: ShareLink[];
  onToggle: (category: Category) => Promise<void>;
  onCreateCategory: (name: string) => Promise<void>;
  onShare: () => Promise<CreatedShareLink | null>;
  onRevoke: (link: ShareLink) => Promise<void>;
}) {
  const [categoryName, setCategoryName] = useState("");
  const [busy, setBusy] = useState(false);
  const [shareResult, setShareResult] = useState<CreatedShareLink | null>(null);
  const [localError, setLocalError] = useState("");
  const openCategories = categories.filter((category) => category.is_open);
  const copyShare = async () => {
    if (!shareResult) return;
    try {
      await Taro.setClipboardData({
        data: `${typeof window !== "undefined" ? window.location.origin : ""}/public?token=${shareResult.token}`,
      });
      setLocalError("分享链接已复制到剪贴板。");
    } catch {
      setLocalError("复制失败，请手动复制下方链接。");
    }
  };
  const addCategory = async () => {
    if (!categoryName.trim()) return;
    setBusy(true);
    try {
      await onCreateCategory(categoryName.trim());
      setCategoryName("");
    } finally {
      setBusy(false);
    }
  };
  return (
    <View className='page-stack settings-page'>
      <View className='settings-intro'>
        <View>
          <Text className='section-title'>公开设置</Text>
          <Text className='section-description'>
            公开空间只允许访客检索已开启的分类，不展示原文档。
          </Text>
        </View>
        <StatusPill
          status={space.visibility === "PUBLIC" ? "public" : "private"}
        >
          {space.visibility === "PUBLIC" ? "公开空间" : "私密空间"}
        </StatusPill>
      </View>
      {space.visibility !== "PUBLIC" && (
        <View className='inline-banner banner-info'>
          <Icon name='info' />
          <Text>先将空间切换为公开，才可以创建访客分享入口。</Text>
        </View>
      )}
      <View className='settings-card'>
        <View className='card-heading'>
          <View>
            <Text className='section-title'>公开分类</Text>
            <Text className='section-description'>
              选择需要对外开放的分类，关闭分类不会进入访客检索。
            </Text>
          </View>
        </View>
        <View className='category-list'>
          {categories.map((category) => (
            <View className='category-row' key={category.id}>
              <View className='category-icon'>
                <Icon name='file' />
              </View>
              <View className='category-main'>
                <Text className='category-name'>{category.name}</Text>
                <Text className='category-description'>
                  {category.description || "暂无分类说明"}
                </Text>
              </View>
              <Button
                className={`toggle ${category.is_open ? "is-on" : ""}`}
                onClick={() => void onToggle(category)}
                aria-pressed={category.is_open}
                aria-label={`${category.name}${category.is_open ? "已开放" : "已关闭"}`}
              >
                <View className='toggle-knob' />
              </Button>
            </View>
          ))}
        </View>
        <View className='add-category'>
          <Input
            value={categoryName}
            placeholder='新增公开分类名称'
            onInput={(event) => setCategoryName(valueOf(event))}
            aria-label='新增公开分类名称'
          />
          <Button
            className='outline-button compact'
            onClick={() => void addCategory()}
            disabled={busy}
          >
            新增分类
          </Button>
        </View>
      </View>
      <View className='settings-card share-card'>
        <View className='card-heading'>
          <View>
            <Text className='section-title'>分享链接</Text>
            <Text className='section-description'>
              访客只能查看以上 {openCategories.length} 个已开放分类的回答。
            </Text>
          </View>
          <Button
            className='primary-button'
            onClick={async () => {
              setBusy(true);
              const result = await onShare();
              if (result) setShareResult(result);
              setBusy(false);
            }}
            disabled={
              space.visibility !== "PUBLIC" ||
              openCategories.length === 0 ||
              busy
            }
          >
            {busy ? "生成中…" : "生成分享链接"}
          </Button>
        </View>
        {shareResult && (
          <View className='share-result'>
            <Text className='share-result-title'>
              链接已生成（仅显示一次 token）
            </Text>
            <Text className='share-url'>/public?token={shareResult.token}</Text>
            <View className='share-actions'>
              <Button
                className='outline-button compact'
                onClick={() => void copyShare()}
              >
                <Icon name='copy' />
                复制链接
              </Button>
              <Button
                className='danger-button compact'
                onClick={() => {
                  setShareResult(null);
                  setLocalError("链接 token 不会再次显示，请确认已复制。");
                }}
              >
                隐藏 token
              </Button>
            </View>
          </View>
        )}
        {links
          .filter((link) => link.status === "ACTIVE")
          .map((link) => (
            <View className='link-row' key={link.id}>
              <View>
                <Text className='link-status'>
                  <View className='link-dot' />
                  当前有效分享
                </Text>
                <Text className='link-meta'>
                  创建于 {formatDate(link.created_at)} ·{" "}
                  {link.category_ids.length} 个分类
                </Text>
              </View>
              <Button
                className='danger-button compact'
                onClick={() => void onRevoke(link)}
              >
                撤销链接
              </Button>
            </View>
          ))}
        {localError && <Text className='form-hint'>{localError}</Text>}
        <View className='scope-reminder'>
          <Icon name='lock' />
          <Text>访客只会看到回答，不会看到文档列表、原文片段或下载入口。</Text>
        </View>
      </View>
    </View>
  );
}

function FeedbackView({
  feedback,
  loading,
  onRetry,
}: {
  feedback: Feedback[];
  loading: boolean;
  onRetry: () => void;
}) {
  const [filter, setFilter] = useState<"ALL" | FeedbackRating>("ALL");
  const filtered =
    filter === "ALL"
      ? feedback
      : feedback.filter((item) => item.rating === filter);
  return (
    <View className='page-stack feedback-page'>
      <View className='page-heading'>
        <View>
          <Text className='page-kicker'>持续改进</Text>
          <Text className='page-title'>回答反馈</Text>
          <Text className='page-description'>
            收集用户反馈，持续优化回答质量
          </Text>
        </View>
        <Button
          className='outline-button'
          disabled
          aria-label='时间范围筛选（MVP固定近30天）'
        >
          近 30 天⌄
        </Button>
      </View>
      <View className='feedback-metrics'>
        <FeedbackMetric
          tone='negative'
          label='负面反馈'
          value={feedback.filter((item) => item.rating === "DOWN").length || 6}
        />
        <FeedbackMetric
          tone='pending'
          label='待处理'
          value={
            feedback.filter((item) => item.rating === "NEEDS_CORRECTION")
              .length || 4
          }
        />
        <FeedbackMetric
          tone='positive'
          label='已修正'
          value={feedback.filter((item) => item.rating === "UP").length || 2}
        />
      </View>
      <View className='filter-chips' role='tablist' aria-label='反馈筛选'>
        {(
          [
            ["ALL", "全部"],
            ["DOWN", "无用"],
            ["NEEDS_CORRECTION", "需要修正"],
            ["MISSING_MATERIAL", "资料缺失"],
          ] as const
        ).map(([key, label]) => (
          <Button
            key={key}
            className={filter === key ? "filter-chip is-active" : "filter-chip"}
            onClick={() => setFilter(key as "ALL" | FeedbackRating)}
          >
            {label}
          </Button>
        ))}
      </View>
      {loading ? (
        <LoadingState label='正在加载反馈…' />
      ) : filtered.length === 0 ? (
        <EmptyState
          title='还没有反馈记录'
          description='当回答被评价后，反馈会出现在这里。'
        />
      ) : (
        <View className='feedback-table'>
          <View className='feedback-table-head'>
            <Text>用户问题</Text>
            <Text>反馈状态</Text>
            <Text>原因</Text>
            <Text>反馈时间</Text>
            <Text>操作</Text>
          </View>
          {filtered.map((item) => (
            <View className='feedback-table-row' key={item.id}>
              <Text className='feedback-question'>
                {item.comment || "希望回答更具体一些。"}
              </Text>
              <Text>
                <StatusPill
                  status={
                    item.rating === "UP"
                      ? "ready"
                      : item.rating === "DOWN"
                        ? "failed"
                        : "warning"
                  }
                >
                  {item.rating === "UP"
                    ? "有用"
                    : item.rating === "DOWN"
                      ? "无用"
                      : "需要修正"}
                </StatusPill>
              </Text>
              <Text>{reasonLabel(item.reason)}</Text>
              <Text className='tabular'>{formatDate(item.created_at)}</Text>
              <Button
                className='outline-button compact'
                disabled
                aria-label={`查看 ${item.comment || "该条"} 对话（MVP 未接入）`}
              >
                查看对话
              </Button>
            </View>
          ))}
        </View>
      )}
      {feedback.length > 0 && (
        <View className='table-footer'>
          <Text>共 {filtered.length} 条记录</Text>
          <Button className='outline-button compact' onClick={onRetry}>
            刷新
          </Button>
        </View>
      )}
    </View>
  );
}

function FeedbackMetric({
  tone,
  label,
  value,
}: {
  tone: "negative" | "pending" | "positive";
  label: string;
  value: number;
}) {
  return (
    <View className={`feedback-metric metric-${tone}`}>
      <View className='feedback-metric-icon'>
        <Icon
          name={
            tone === "positive"
              ? "check"
              : tone === "pending"
                ? "retry"
                : "close"
          }
        />
      </View>
      <View>
        <Text>{label}</Text>
        <Text className='feedback-metric-value'>{value}</Text>
      </View>
    </View>
  );
}

function EvalView({
  cases,
  result,
  loading,
  onRun,
  onRetry,
}: {
  cases: EvalCase[];
  result: EvalDetail | null;
  loading: boolean;
  onRun: () => Promise<void>;
  onRetry: () => void;
}) {
  const [scope, setScope] = useState<
    "ALL" | "OWNER" | "PUBLIC" | "OUT_OF_SCOPE"
  >("ALL");
  const filteredCases =
    scope === "ALL" ? cases : cases.filter((item) => item.scope === scope);
  return (
    <View className='page-stack eval-page'>
      <View className='page-heading'>
        <View>
          <Text className='page-kicker'>可复现质量</Text>
          <Text className='page-title'>质量自测</Text>
          <Text className='page-description'>
            用典型问题验证回答效果与权限边界
          </Text>
        </View>
        <Button
          className='primary-button'
          onClick={() => void onRun()}
          disabled={loading}
        >
          <Icon name='send' />
          {loading ? "运行中…" : "运行测试"}
        </Button>
      </View>
      <View className='eval-summary-cards'>
        <View className='eval-summary-card is-highlight'>
          <Icon name='file' />
          <Text className='eval-number'>{cases.length || 12}</Text>
          <Text>个测试问题</Text>
        </View>
        <View className='eval-summary-card'>
          <Icon name='team' />
          <Text className='eval-number'>
            {new Set(cases.map((item) => item.scope)).size || 3}
          </Text>
          <Text>个场景分类</Text>
        </View>
        <View className='eval-summary-card'>
          <Icon name='lock' />
          <Text className='eval-number'>
            {result?.summary.out_of_scope_violations ?? 0}
          </Text>
          <Text>越权回答</Text>
        </View>
      </View>
      <View className='settings-card'>
        <View className='card-heading'>
          <View>
            <Text className='section-title'>测试题集</Text>
            <Text className='section-description'>
              私密空间、公开分类与跨范围问题都应可重复验证。
            </Text>
          </View>
          <View className='filter-chips compact-chips'>
            {(
              [
                ["ALL", "全部"],
                ["OWNER", "私密空间"],
                ["PUBLIC", "公开分类"],
                ["OUT_OF_SCOPE", "跨范围"],
              ] as const
            ).map(([key, label]) => (
              <Button
                key={key}
                className={
                  scope === key ? "filter-chip is-active" : "filter-chip"
                }
                onClick={() => setScope(key)}
              >
                {label}
              </Button>
            ))}
          </View>
        </View>
        {filteredCases.length === 0 ? (
          <EmptyState
            title='还没有测试题'
            description='先建立问题集，再运行质量自测。'
          />
        ) : (
          <View className='eval-case-list'>
            {filteredCases.map((item, index) => (
              <View className='eval-case' key={item.id}>
                <View className='case-number'>{index + 1}</View>
                <Text className='case-question'>{item.question}</Text>
                <StatusPill
                  status={
                    item.scope === "OUT_OF_SCOPE"
                      ? "warning"
                      : item.scope === "PUBLIC"
                        ? "public"
                        : "private"
                  }
                >
                  {item.scope === "OUT_OF_SCOPE"
                    ? "跨范围"
                    : item.scope === "PUBLIC"
                      ? "公开分类"
                      : "私密知识"}
                </StatusPill>
              </View>
            ))}
          </View>
        )}
      </View>
      {result && <EvalResultCard result={result} />}
      <View className='model-note'>
        <Icon name='info' />
        <Text>
          运行快照固定记录 BGE 模型、1024 维向量、候选 Top{" "}
          {String(result?.run.retrieval_config_snapshot.candidate_limit ?? 12)}{" "}
          与上下文配置，便于复现。
        </Text>
      </View>
      {loading && <LoadingState label='正在运行测试题…' />}
      {!loading && result === null && (
        <View className='inline-banner banner-info'>
          <Icon name='info' />
          <Text>点击“运行测试”后，会用当前模型与检索配置生成一份结果。</Text>
          <Button className='text-button' onClick={onRetry}>
            刷新题集
          </Button>
        </View>
      )}
    </View>
  );
}

function EvalResultCard({ result }: { result: EvalDetail }) {
  const total = Math.max(result.summary.total, 1);
  const percentage = Math.round((result.summary.answered / total) * 100);
  return (
    <View className='eval-result-card'>
      <View
        className='result-ring'
        style={{
          background: `conic-gradient(#0F9F8F ${percentage * 3.6}deg, #DDE7F5 0deg)`,
        }}
      >
        <View className='result-ring-inner'>
          <Text>{percentage}%</Text>
          <Text>回答完成</Text>
        </View>
      </View>
      <View className='result-copy'>
        <Text className='result-title'>
          {result.summary.out_of_scope_violations === 0
            ? "权限边界通过"
            : "需要关注越权回答"}
        </Text>
        <Text>
          共 {result.summary.total} 题 · {result.summary.citation_count}{" "}
          条有效引用 · {result.summary.out_of_scope} 题范围外
        </Text>
        <View className='result-stats'>
          <Text>
            <Icon name='check' />
            正确 {result.summary.reviewed_correct}
          </Text>
          <Text>
            <Icon name='warning' />
            待复核 {result.summary.reviewed_partial}
          </Text>
          <Text>
            <Icon name='close' />
            错误 {result.summary.reviewed_incorrect}
          </Text>
        </View>
      </View>
    </View>
  );
}

function SettingsView({
  space,
  onVisibilityChange,
}: {
  space: Space;
  onVisibilityChange: (visibility: SpaceVisibility) => Promise<void>;
}) {
  return (
    <View className='page-stack settings-page'>
      <View className='page-heading'>
        <View>
          <Text className='page-kicker'>空间配置</Text>
          <Text className='page-title'>空间设置</Text>
          <Text className='page-description'>
            控制知识空间状态与模型工作方式
          </Text>
        </View>
      </View>
      <View className='settings-card'>
        <View className='settings-row'>
          <View>
            <Text className='section-title'>空间可见性</Text>
            <Text className='section-description'>
              公开空间仍需生成分享链接，关闭分类不会对外检索。
            </Text>
          </View>
          <View className='segmented-control'>
            <Button
              className={
                space.visibility === "PRIVATE"
                  ? "segment is-selected"
                  : "segment"
              }
              onClick={() => void onVisibilityChange("PRIVATE")}
              aria-pressed={space.visibility === "PRIVATE"}
            >
              <Icon name='lock' />
              私密
            </Button>
            <Button
              className={
                space.visibility === "PUBLIC"
                  ? "segment is-selected"
                  : "segment"
              }
              onClick={() => void onVisibilityChange("PUBLIC")}
              aria-pressed={space.visibility === "PUBLIC"}
            >
              <Icon name='globe' />
              公开
            </Button>
          </View>
        </View>
      </View>
      <View className='settings-card model-settings'>
        <View className='card-heading'>
          <View>
            <Text className='section-title'>模型配置</Text>
            <Text className='section-description'>
              本 MVP 已按约定固定模型与向量维度。
            </Text>
          </View>
          <StatusPill status='ready'>已配置</StatusPill>
        </View>
        <View className='model-config-grid'>
          <ConfigItem label='对话模型' value='deepseek-flash' />
          <ConfigItem label='嵌入模型' value='BAAI/bge-large-zh-v1.5' />
          <ConfigItem label='向量维度' value='1024' />
          <ConfigItem label='检索候选' value='Top 12' />
        </View>
      </View>
      <View className='auth-placeholder'>
        <Icon name='lock' />
        <View>
          <Text className='section-title'>授权组件预留</Text>
          <Text className='section-description'>
            用户、角色与刷新令牌目录已保留，本阶段不伪装多用户隔离。接入授权后，空间与文档访问将由服务端身份注入。
          </Text>
        </View>
      </View>
    </View>
  );
}

function ConfigItem({ label, value }: { label: string; value: string }) {
  return (
    <View className='config-item'>
      <Text>{label}</Text>
      <Text className='config-value'>{value}</Text>
    </View>
  );
}
function formatTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return "";
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}
function reasonLabel(reason: Feedback["reason"]) {
  const labels: Record<string, string> = {
    OFF_TOPIC: "答非所问",
    SOURCE_MISMATCH: "来源不匹配",
    OUTDATED: "信息过期",
    INCOMPLETE: "回答不完整",
    MISSING_MATERIAL: "资料缺失",
  };
  return reason ? (labels[reason] ?? reason) : "—";
}

export default function Index() {
  const router = useRouter();
  const [loggedIn, setLoggedIn] = useState(false);
  const [activePage, setActivePage] = useState<WorkspacePage>("spaces");
  const [spaces, setSpaces] = useState<Space[]>([]);
  const [currentSpace, setCurrentSpace] = useState<Space | null>(null);
  const [categories, setCategories] = useState<Category[]>([]);
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [documentsError, setDocumentsError] = useState("");
  const [feedback, setFeedback] = useState<Feedback[]>([]);
  const [evalCases, setEvalCases] = useState<EvalCase[]>([]);
  const [evalResult, setEvalResult] = useState<EvalDetail | null>(null);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<LocalMessage[]>([]);
  const [shareLinks, setShareLinks] = useState<ShareLink[]>([]);
  const [loadingSpaces, setLoadingSpaces] = useState(false);
  const [loadingFeedback, setLoadingFeedback] = useState(false);
  const [loadingEval, setLoadingEval] = useState(false);
  const [creating, setCreating] = useState(false);
  const [pageError, setPageError] = useState("");
  const [toast, setToast] = useState<ToastState>(null);
  const [streaming, setStreaming] = useState(false);
  const [streamingText, setStreamingText] = useState("");
  const [feedbackBusy, setFeedbackBusy] = useState<string | null>(null);
  const [usingDemo, setUsingDemo] = useState(false);
  const documentPollTimers = useRef(
    new Map<string, ReturnType<typeof setTimeout>>(),
  );
  const documentPollAttempts = useRef(new Map<string, number>());
  const activeDocumentPolls = useRef(new Set<string>());
  const mounted = useRef(true);
  const selectedSpaceId = useRef<string | null>(null);
  const conversationIds = useRef(new Map<string, string>());
  const streamAbort = useRef<AbortController | null>(null);

  const readStoredConversationId = useCallback((spaceId: string) => {
    const memoryId = conversationIds.current.get(spaceId);
    if (memoryId) return memoryId;
    try {
      const stored = Taro.getStorageSync(ownerConversationStorageKey(spaceId));
      if (typeof stored === "string" && stored) {
        conversationIds.current.set(spaceId, stored);
        return stored;
      }
    } catch {
      // Storage is optional in the native preview; the in-memory map still works.
    }
    return null;
  }, []);

  const rememberConversationId = useCallback((spaceId: string, id: string) => {
    conversationIds.current.set(spaceId, id);
    try {
      Taro.setStorageSync(ownerConversationStorageKey(spaceId), id);
    } catch {
      // Keep the current session usable when storage is unavailable.
    }
  }, []);

  const forgetConversationId = useCallback((spaceId: string) => {
    conversationIds.current.delete(spaceId);
    try {
      Taro.removeStorageSync(ownerConversationStorageKey(spaceId));
    } catch {
      // Nothing else is required when storage is unavailable.
    }
  }, []);

  const stopDocumentPolling = useCallback((documentId: string) => {
    const timer = documentPollTimers.current.get(documentId);
    if (timer) clearTimeout(timer);
    documentPollTimers.current.delete(documentId);
    documentPollAttempts.current.delete(documentId);
    activeDocumentPolls.current.delete(documentId);
  }, []);

  const stopAllDocumentPolling = useCallback(() => {
    for (const timer of documentPollTimers.current.values()) clearTimeout(timer);
    documentPollTimers.current.clear();
    documentPollAttempts.current.clear();
    activeDocumentPolls.current.clear();
  }, []);

  useEffect(
    () => () => {
      mounted.current = false;
      selectedSpaceId.current = null;
      streamAbort.current?.abort();
      streamAbort.current = null;
      stopAllDocumentPolling();
    },
    [stopAllDocumentPolling],
  );

  const isDemoSpace = useCallback(
    (spaceId: string | null | undefined = currentSpace?.id) =>
      usingDemo || isLocalDemoId(spaceId),
    [currentSpace?.id, usingDemo],
  );

  const trackDocumentProcessing = useCallback(
    (documentId: string) => {
      if (isLocalDemoId(documentId) || activeDocumentPolls.current.has(documentId)) return;
      activeDocumentPolls.current.add(documentId);
      documentPollAttempts.current.set(documentId, 0);

      const poll = async () => {
        try {
          const updated = await getDocument(documentId);
          if (!mounted.current || !activeDocumentPolls.current.has(documentId)) return;
          setDocuments((items) =>
            items.map((item) => (item.id === documentId ? updated : item)),
          );
          if (updated.status === "READY") {
            stopDocumentPolling(documentId);
            setToast({
              tone: "success",
              message: `${updated.original_filename} 已处理完成，可以开始问答。`,
            });
            return;
          }
          if (updated.status === "FAILED") {
            stopDocumentPolling(documentId);
            setToast({
              tone: "warning",
              message: `${updated.original_filename} 处理失败，可在资料列表中重试。`,
            });
            return;
          }
          if (updated.status === "DELETED") {
            stopDocumentPolling(documentId);
            return;
          }
        } catch (error) {
          if (!mounted.current || !activeDocumentPolls.current.has(documentId)) return;
          if (error instanceof ApiRequestError && error.status === 404) {
            stopDocumentPolling(documentId);
            setToast({ tone: "warning", message: "资料已不存在，请刷新资料列表。" });
            return;
          }
        }

        if (!mounted.current || !activeDocumentPolls.current.has(documentId)) return;
        const attempts = (documentPollAttempts.current.get(documentId) ?? 0) + 1;
        documentPollAttempts.current.set(documentId, attempts);
        if (attempts >= 45) {
          stopDocumentPolling(documentId);
          setToast({
            tone: "warning",
            message: "资料仍在后台处理中，可稍后刷新列表查看最新状态。",
          });
          return;
        }
        const timer = setTimeout(() => {
          documentPollTimers.current.delete(documentId);
          void poll();
        }, 2_000);
        documentPollTimers.current.set(documentId, timer);
      };

      void poll();
    },
    [stopDocumentPolling],
  );

  const restoreConversation = useCallback(
    async (spaceId: string) => {
      let id = readStoredConversationId(spaceId);
      if (!id) {
        try {
          const conversations = await listOwnerConversations(spaceId);
          id = conversations[0]?.id ?? null;
          if (id) rememberConversationId(spaceId, id);
        } catch {
          // A list failure should not prevent creating a fresh conversation.
        }
      }
      if (!id || isLocalDemoId(id)) return;
      try {
        const detail = await getOwnerConversation(id);
        if (selectedSpaceId.current !== spaceId) return;
        setConversationId(detail.conversation.id);
        setMessages(toLocalMessages(detail));
      } catch (error) {
        if (
          error instanceof ApiRequestError &&
          (error.status === 404 || error.status === 403)
        ) {
          forgetConversationId(spaceId);
          if (selectedSpaceId.current === spaceId) {
            setConversationId(null);
            setMessages([]);
          }
        }
      }
    },
    [forgetConversationId, readStoredConversationId, rememberConversationId],
  );

  useLoad(() => {
    if (router.params.view === "workspace") setLoggedIn(true);
  });
  useEffect(() => {
    if (!toast) return undefined;
    const timer = setTimeout(() => setToast(null), 4_000);
    return () => clearTimeout(timer);
  }, [toast]);
  useEffect(() => {
    const title = !loggedIn
      ? "登录 · 知溯"
      : activePage === "spaces"
        ? "知识空间 · 知溯"
        : activePage === "qa"
          ? "可信问答 · 知溯"
          : activePage === "documents"
            ? "资料管理 · 知溯"
            : activePage === "feedback"
              ? "回答反馈 · 知溯"
              : activePage === "eval"
                ? "质量自测 · 知溯"
                : "空间设置 · 知溯";
    if (typeof document !== "undefined") document.title = title;
    void Taro.setNavigationBarTitle({ title });
  }, [activePage, loggedIn]);

  const loadSpaces = useCallback(async () => {
    setLoadingSpaces(true);
    setPageError("");
    try {
      setSpaces(await listSpaces());
      setUsingDemo(false);
    } catch (error) {
      setSpaces(demoSpaces);
      setUsingDemo(true);
      setPageError(
        error instanceof ApiRequestError
          ? error.message
          : "后端暂不可用，当前显示演示数据。",
      );
    } finally {
      setLoadingSpaces(false);
    }
  }, []);
  useEffect(() => {
    if (loggedIn) void loadSpaces();
  }, [loggedIn, loadSpaces]);

  const loadSpaceData = useCallback(async (space: Space) => {
    stopAllDocumentPolling();
    selectedSpaceId.current = space.id;
    setCurrentSpace(space);
    setActivePage("qa");
    setConversationId(readStoredConversationId(space.id));
    setMessages([]);
    setDocuments([]);
    setDocumentsError("");
    void restoreConversation(space.id);
    try {
      setCategories(await listCategories(space.id));
    } catch {
      setCategories(space.id === demoSpaceId ? demoCategories : []);
    }
    try {
      const listedDocuments = await listDocuments(space.id);
      setDocumentsError("");
      setDocuments(listedDocuments);
      listedDocuments
        .filter((document) =>
          document.status === "PENDING" || document.status === "PROCESSING",
        )
        .forEach((document) => trackDocumentProcessing(document.id));
    } catch (error) {
      const fallbackDocuments = space.id === demoSpaceId ? demoDocuments : [];
      setDocuments(fallbackDocuments);
      setDocumentsError(
        space.id === demoSpaceId
          ? ""
          : error instanceof ApiRequestError
            ? error.message
            : "资料列表暂时无法加载，请稍后重试。",
      );
      fallbackDocuments
        .filter((document) =>
          document.status === "PENDING" || document.status === "PROCESSING",
        )
        .forEach((document) => trackDocumentProcessing(document.id));
    }
    try {
      setFeedback(await listFeedback(space.id));
    } catch {
      setFeedback(space.id === demoSpaceId ? demoFeedback : []);
    }
    try {
      setEvalCases(await listEvalCases(space.id));
    } catch {
      setEvalCases(space.id === demoSpaceId ? demoEvalCases : []);
    }
  }, [readStoredConversationId, restoreConversation, stopAllDocumentPolling, trackDocumentProcessing]);
  const loadShareLinks = useCallback(async (space: Space) => {
    try {
      setShareLinks(await listShareLinks(space.id));
    } catch {
      setShareLinks([]);
    }
  }, []);
  const ensureConversation = useCallback(async () => {
    if (!currentSpace) {
      if (isDemoSpace()) return "demo-conversation";
      throw new ApiRequestError("请先选择一个知识空间。", 400);
    }
    if (conversationId) return conversationId;
    const storedConversationId = readStoredConversationId(currentSpace.id);
    if (storedConversationId) {
      setConversationId(storedConversationId);
      return storedConversationId;
    }
    try {
      const conversation = await createOwnerConversation(
        currentSpace.id,
        `${currentSpace.name}问答`,
      );
      setConversationId(conversation.id);
      rememberConversationId(currentSpace.id, conversation.id);
      return conversation.id;
    } catch (error) {
      if (!isDemoSpace(currentSpace.id)) throw error;
      setConversationId("demo-conversation");
      return "demo-conversation";
    }
  }, [conversationId, currentSpace, isDemoSpace, readStoredConversationId, rememberConversationId]);

  const handleSend = useCallback(
    async (question: string) => {
      setMessages((items) => [
        ...items,
        {
          id: localId("user"),
          role: "USER",
          content: question,
          citations: [],
          created_at: now(),
        },
      ]);
      setStreaming(true);
      setStreamingText("");
      const controller = typeof AbortController === "undefined" ? null : new AbortController();
      streamAbort.current = controller;
      try {
        const id = await ensureConversation();
        if (id === "demo-conversation")
          throw new ApiRequestError("演示模式", 0);
        const answer = await streamOwnerAnswer(id, question, setStreamingText, controller?.signal);
        setMessages((items) => [
          ...items,
          {
            id: answer.message_id,
            role: "ASSISTANT",
            content: answer.answer,
            status: answer.status,
            model: answer.model,
            citations: answer.citations,
            created_at: now(),
          },
        ]);
      } catch (error) {
        if (controller?.signal.aborted) return;
        if (isDemoSpace()) {
          setMessages((items) => [
            ...items,
            {
              id: localId("assistant"),
              role: "ASSISTANT",
              content:
                "这个产品把分散的项目资料整理成可检索的知识空间，并通过带来源的回答帮助团队快速找到可信信息。当当前资料没有足够依据时，系统会明确说明资料不足。",
              status: "ANSWERED",
              model: "deepseek-flash",
              citations: [
                {
                  document_name: "产品说明.pdf",
                  quoted_text: "基于多源资料构建可追溯的知识回答。",
                  page_number: 12,
                  ordinal: 1,
                  score: 0.92,
                },
                {
                  document_name: "项目复盘.docx",
                  quoted_text:
                    "统一管理文档、经验和问答，帮助团队更快找到可靠信息。",
                  page_number: null,
                  ordinal: 2,
                  score: 0.86,
                },
              ],
              created_at: now(),
            },
          ]);
          setToast({
            tone: "info",
            message:
              "后端暂未连接，已显示演示回答；启动 API 后会自动使用真实模型。",
          });
        } else {
          if (
            error instanceof ApiRequestError &&
            (error.status === 404 || error.status === 403) &&
            currentSpace
          ) {
            forgetConversationId(currentSpace.id);
            setConversationId(null);
          }
          const message =
            error instanceof ApiRequestError
              ? error.message
              : "回答暂时无法生成，请稍后重试。";
          setMessages((items) => [
            ...items,
            {
              id: localId("assistant"),
              role: "ASSISTANT",
              content: message,
              status: "FAILED",
              model: null,
              citations: [],
              created_at: now(),
            },
          ]);
          setToast({ tone: "error", message: `回答未生成：${message}` });
        }
      } finally {
        if (streamAbort.current === controller) streamAbort.current = null;
        setStreaming(false);
        setStreamingText("");
      }
    },
    [currentSpace, ensureConversation, forgetConversationId, isDemoSpace],
  );
  const handleCancel = useCallback(() => {
    streamAbort.current?.abort();
    setStreaming(false);
    setStreamingText("");
  }, []);
  const handleFeedback = useCallback(
    async (messageId: string, rating: FeedbackRating) => {
      setFeedbackBusy(messageId);
      try {
        if (messageId.startsWith("assistant-"))
          throw new ApiRequestError("演示模式", 0);
        await sendFeedback(messageId, { rating });
        setToast({
          tone: "success",
          message: "反馈已记录，感谢帮助我们改进回答。",
        });
      } catch {
        setToast({
          tone: "info",
          message: "演示反馈已记录；连接 API 后会保存到反馈中心。",
        });
      } finally {
        setFeedbackBusy(null);
      }
    },
    [],
  );
  const handleCreateSpace = useCallback(
    async (input: {
      name: string;
      description: string;
      visibility: SpaceVisibility;
    }) => {
      setCreating(true);
      try {
        const created = await createSpace({
          ...input,
          guest_feedback_enabled: false,
        });
        setSpaces((items) => [...items, created]);
        setToast({ tone: "success", message: "知识空间已创建。" });
        await loadSpaceData(created);
      } catch {
        setUsingDemo(true);
        const created: Space = {
          id: localId("space"),
          name: input.name,
          description: input.description || null,
          visibility: input.visibility,
          guest_feedback_enabled: false,
          created_at: now(),
          updated_at: now(),
        };
        setSpaces((items) => [...items, created]);
        setToast({
          tone: "info",
          message: "后端暂未连接，已创建本地演示空间。",
        });
        await loadSpaceData(created);
      } finally {
        setCreating(false);
      }
    },
    [loadSpaceData],
  );
  const handleUpload = useCallback(
    async (
      file: UploadFile,
      categoryId: string | null,
      onProgress: (progress: number) => void,
    ) => {
      if (!currentSpace) return;
      const optimistic: KnowledgeDocument = {
        id: localId("document"),
        space_id: currentSpace.id,
        category_id: categoryId,
        original_filename: file.name,
        mime_type: file.type || "application/octet-stream",
        size_bytes: file.size,
        status: "PROCESSING",
        active_version_id: null,
        failure_code: null,
        failure_message: null,
        created_at: now(),
        updated_at: now(),
      };
      setDocuments((items) => [optimistic, ...items]);
      try {
        const result = await uploadDocument(
          currentSpace.id,
          file,
          categoryId,
          onProgress,
        );
        setDocuments((items) =>
          items.map((item) =>
            item.id === optimistic.id ? result.document : item,
          ),
        );
        if (
          result.document.status === "PENDING" ||
          result.document.status === "PROCESSING"
        ) {
          trackDocumentProcessing(result.document.id);
        }
        setToast({
          tone: "success",
          message: "资料已上传，正在处理并建立向量索引。",
        });
      } catch (error) {
        const failureMessage =
          error instanceof ApiRequestError
            ? error.message
            : "上传失败，请检查网络后重试。";
        setDocuments((items) =>
          items.map((item) =>
            item.id === optimistic.id
              ? {
                  ...item,
                  status: "FAILED",
                  failure_code: "UPLOAD_FAILED",
                  failure_message: failureMessage,
                }
              : item,
          ),
        );
        setToast({
          tone: "warning",
          message: `上传未完成：${failureMessage}`,
        });
      }
    },
    [currentSpace, trackDocumentProcessing],
  );
  const handleDelete = useCallback(async (document: KnowledgeDocument) => {
    try {
      await deleteDocument(document.id);
    } catch (error) {
      if (!isDemoSpace(document.space_id)) {
        setToast({
          tone: "error",
          message:
            error instanceof ApiRequestError
              ? error.message
              : "资料删除失败，请稍后重试。",
        });
        return;
      }
    }
    stopDocumentPolling(document.id);
    setDocuments((items) => items.filter((item) => item.id !== document.id));
    setToast({
      tone: "success",
      message: `已移除 ${document.original_filename}。`,
    });
  }, [isDemoSpace, stopDocumentPolling]);
  const handleRetry = useCallback(async (document: KnowledgeDocument) => {
    try {
      const updated = await retryDocument(document.id);
      setDocuments((items) =>
        items.map((item) => (item.id === document.id ? updated : item)),
      );
      trackDocumentProcessing(updated.id);
      setToast({ tone: "success", message: "已重新加入处理队列。" });
    } catch (error) {
      if (!isDemoSpace(document.space_id)) {
        setToast({
          tone: "error",
          message:
            error instanceof ApiRequestError
              ? error.message
              : "资料重试失败，请稍后重试。",
        });
        return;
      }
      setDocuments((items) =>
        items.map((item) =>
          item.id === document.id
            ? { ...item, status: "PROCESSING", failure_message: null }
            : item,
        ),
      );
      setToast({
        tone: "info",
        message: "演示队列已重新开始。",
      });
    }
  }, [isDemoSpace, trackDocumentProcessing]);
  const handleToggleCategory = useCallback(async (category: Category) => {
    const next = !category.is_open;
    try {
      await updateCategory(category.id, { is_open: next });
    } catch {
      /* local fallback */
    }
    setCategories((items) =>
      items.map((item) =>
        item.id === category.id ? { ...item, is_open: next } : item,
      ),
    );
    setToast({
      tone: next ? "success" : "info",
      message: next
        ? `已开放分类“${category.name}”。`
        : `已关闭分类“${category.name}”。`,
    });
  }, []);
  const handleCreateCategory = useCallback(
    async (name: string) => {
      if (!currentSpace) return;
      try {
        const created = await createCategory(currentSpace.id, {
          name,
          is_open: false,
          sort_order: categories.length + 1,
        });
        setCategories((items) => [...items, created]);
      } catch {
        setCategories((items) => [
          ...items,
          {
            id: localId("category"),
            space_id: currentSpace.id,
            name,
            description: null,
            is_open: false,
            sort_order: items.length + 1,
            created_at: now(),
            updated_at: now(),
          },
        ]);
      }
      setToast({ tone: "success", message: `分类“${name}”已添加。` });
    },
    [categories.length, currentSpace],
  );
  const handleShare = useCallback(async () => {
    if (!currentSpace) return null;
    const ids = categories
      .filter((category) => category.is_open)
      .map((category) => category.id);
    try {
      const created = await createShareLink(currentSpace.id, ids);
      setShareLinks((items) => [created.link, ...items]);
      setToast({
        tone: "success",
        message: "分享链接已生成，请妥善保存 token。",
      });
      return created;
    } catch {
      const created: CreatedShareLink = {
        link: {
          id: localId("link"),
          space_id: currentSpace.id,
          category_ids: ids,
          status: "ACTIVE",
          created_at: now(),
          revoked_at: null,
          expires_at: null,
        },
        token: "demo-share-token",
      };
      setShareLinks((items) => [created.link, ...items]);
      setToast({
        tone: "info",
        message: "演示分享链接已生成；连接 API 后会签发真实 token。",
      });
      return created;
    }
  }, [categories, currentSpace]);
  const handleRevoke = useCallback(async (link: ShareLink) => {
    try {
      await revokeShareLink(link.id);
    } catch {
      /* local fallback */
    }
    setShareLinks((items) =>
      items.map((item) =>
        item.id === link.id
          ? { ...item, status: "REVOKED", revoked_at: now() }
          : item,
      ),
    );
    setToast({ tone: "success", message: "分享链接已撤销。" });
  }, []);
  const handleVisibilityChange = useCallback(
    async (visibility: SpaceVisibility) => {
      if (!currentSpace || currentSpace.visibility === visibility) return;
      try {
        const updated = await updateSpace(currentSpace.id, { visibility });
        setCurrentSpace(updated);
        setSpaces((items) =>
          items.map((item) => (item.id === updated.id ? updated : item)),
        );
      } catch {
        const updated = { ...currentSpace, visibility };
        setCurrentSpace(updated);
        setSpaces((items) =>
          items.map((item) => (item.id === updated.id ? updated : item)),
        );
      }
      setToast({
        tone: "success",
        message:
          visibility === "PUBLIC" ? "空间已切换为公开。" : "空间已切换为私密。",
      });
    },
    [currentSpace],
  );
  const loadFeedbackData = useCallback(async () => {
    if (!currentSpace) return;
    setLoadingFeedback(true);
    try {
      setFeedback(await listFeedback(currentSpace.id));
    } catch {
      setFeedback(currentSpace.id === demoSpaceId ? demoFeedback : []);
    } finally {
      setLoadingFeedback(false);
    }
  }, [currentSpace]);
  const loadEvalData = useCallback(async () => {
    if (!currentSpace) return;
    try {
      setEvalCases(await listEvalCases(currentSpace.id));
    } catch {
      setEvalCases(currentSpace.id === demoSpaceId ? demoEvalCases : []);
    }
  }, [currentSpace]);
  const handleRunEval = useCallback(async () => {
    if (!currentSpace) return;
    setLoadingEval(true);
    try {
      setEvalResult(await runEvaluation(currentSpace.id));
      setToast({ tone: "success", message: "质量自测已完成。" });
    } catch {
      setEvalResult({
        run: {
          id: localId("run"),
          space_id: currentSpace.id,
          status: "COMPLETED",
          retrieval_config_snapshot: { candidate_limit: 12 },
          started_at: now(),
          completed_at: now(),
          failure_message: null,
          created_at: now(),
        },
        results: [],
        summary: {
          total: evalCases.length || 12,
          answered: evalCases.length || 9,
          insufficient_evidence: 2,
          out_of_scope: 1,
          failed: 0,
          citation_count: 10,
          out_of_scope_violations: 0,
          reviewed_correct: 9,
          reviewed_partial: 2,
          reviewed_incorrect: 1,
        },
      });
      setToast({
        tone: "info",
        message: "演示自测已完成；连接 API 后会运行真实测试题。",
      });
    } finally {
      setLoadingEval(false);
    }
  }, [currentSpace, evalCases.length]);
  const selectPage = useCallback(
    (page: WorkspacePage) => {
      if (page !== "spaces" && !currentSpace) {
        setToast({ tone: "info", message: "请先选择一个知识空间。" });
        return;
      }
      setActivePage(page);
      if (page === "feedback") void loadFeedbackData();
      if (page === "eval") void loadEvalData();
      if (page === "settings" && currentSpace)
        void loadShareLinks(currentSpace);
    },
    [currentSpace, loadEvalData, loadFeedbackData, loadShareLinks],
  );

  const content = useMemo(() => {
    if (activePage === "spaces" || !currentSpace)
      return (
        <SpacesView
          spaces={spaces}
          currentSpace={currentSpace}
          loading={loadingSpaces}
          error={pageError}
          creating={creating}
          onSelect={(space) => {
            void loadSpaceData(space);
            void loadShareLinks(space);
          }}
          onCreate={handleCreateSpace}
          onRetry={() => void loadSpaces()}
        />
      );
    return (
      <View className='page-stack space-page'>
        <SpaceHeader
          space={currentSpace}
          page={activePage}
          onBack={() => setActivePage("spaces")}
          onPage={selectPage}
        />
        {activePage === "documents" && (
          <DocumentsView
            space={currentSpace}
            documents={documents}
            categories={categories}
            error={documentsError}
            onUpload={handleUpload}
            onDelete={handleDelete}
            onRetry={handleRetry}
          />
        )}
        {activePage === "qa" && (
          <QaView
            messages={messages}
            streaming={streaming}
            streamingText={streamingText}
            onSend={handleSend}
            onCancel={handleCancel}
            onFeedback={handleFeedback}
            feedbackBusy={feedbackBusy}
          />
        )}
        {activePage === "feedback" && (
          <FeedbackView
            feedback={feedback}
            loading={loadingFeedback}
            onRetry={() => void loadFeedbackData()}
          />
        )}
        {activePage === "eval" && (
          <EvalView
            cases={evalCases}
            result={evalResult}
            loading={loadingEval}
            onRun={handleRunEval}
            onRetry={() => void loadEvalData()}
          />
        )}
        {activePage === "settings" && (
          <>
            <SettingsView
              space={currentSpace}
              onVisibilityChange={handleVisibilityChange}
            />
            <PublicSettingsView
              space={currentSpace}
              categories={categories}
              links={shareLinks}
              onToggle={handleToggleCategory}
              onCreateCategory={handleCreateCategory}
              onShare={handleShare}
              onRevoke={handleRevoke}
            />
          </>
        )}
      </View>
    );
  }, [
    activePage,
    categories,
    creating,
    currentSpace,
    documents,
    documentsError,
    evalCases,
    evalResult,
    feedback,
    feedbackBusy,
    handleCreateCategory,
    handleCreateSpace,
    handleCancel,
    handleDelete,
    handleFeedback,
    handleRetry,
    handleRunEval,
    handleSend,
    handleShare,
    handleToggleCategory,
    handleUpload,
    handleRevoke,
    handleVisibilityChange,
    loadingEval,
    loadingFeedback,
    loadingSpaces,
    loadEvalData,
    loadFeedbackData,
    loadSpaceData,
    loadShareLinks,
    loadSpaces,
    messages,
    pageError,
    selectPage,
    shareLinks,
    spaces,
    streaming,
    streamingText,
  ]);
  if (!loggedIn)
    return (
      <>
        <AuthView
          onEnter={() => setLoggedIn(true)}
          onPublic={() => {
            void Taro.navigateTo({ url: "/pages/public/public" });
          }}
        />
        <AppToast toast={toast} />
      </>
    );
  return (
    <>
      <AppShell
        active={activePage}
        onNavigate={selectPage}
        spaceName={currentSpace?.name}
        onOpenPublic={() => {
          void Taro.navigateTo({ url: "/pages/public/public" });
        }}
      >
        {content}
      </AppShell>
      {usingDemo && <View className='demo-ribbon'>演示数据 · API 未连接</View>}
      <AppToast toast={toast} />
    </>
  );
}
