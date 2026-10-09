import { Checkbox, Input, Label, Picker, Text, Textarea, View } from "@tarojs/components";
import Taro, { useLoad, useRouter } from "@tarojs/taro";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { Button } from '../../components/H5Button';
import { RetrievalMetadataFilterControls } from '../../components/RetrievalMetadataFilterControls';
import {
  ApiRequestError,
  publicShareUrl,
  createCategory,
  createOwnerConversation,
  createShareLink,
  createSpace,
  getAuthUserId,
  deleteDocument,
  formatDate,
  formatFileSize,
  getDocument,
  getOwnerConversation,
  listOwnerConversations,
  listCategories,
  listDocuments,
  listFeedback,
  listShareLinks,
  listSpaces,
  retryDocument,
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
  type Feedback,
  type FeedbackRating,
  type KnowledgeDocument,
  type ShareLink,
  type Space,
  type SpacePlan,
  type SpaceVisibility,
  type SpaceKind,
  type UploadFile,
  login,
  register,
  getMe,
  logout,
  type AuthUser,
  createTag,
  deleteTag,
  listTags,
  listMembers,
  addMember,
  changeMemberRole,
  removeMember,
  reviewFeedback,
  searchDocuments,
  listDocumentTags,
  setDocumentTags,
  updateDocumentAvailability,
  type KnowledgeTag,
  type SpaceMember,
  getSpaceUsage,
  type SpaceUsage,
  type RetrievalMetadataFilter,
  type QueryDiagnostics,
  emptyRetrievalMetadataFilter,
  createSource,
  listSources,
  setSourceStatus,
  syncSource,
  type KnowledgeSource,
  type SourceKind,
  type SourceStatus,
  listPublicQuestionRecords,
  getPublicAnalytics,
  moderatePublicQuestion,
  type PublicAnalytics,
  type PublicQuestionRecord,
} from "../../api/client";
import { AppShell, type WorkspacePage } from "../../components/AppShell";
import { Icon } from "../../components/Icon";
import { RetrievalView } from "../../components/RetrievalView";
import { EvaluationView } from "../../components/EvaluationView";
import { DocumentDetailView } from "../../components/DocumentDetailView";
import { FeedbackDialog } from "../../components/FeedbackDialog";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { V2Button, V2Heading } from "../../components/V2UI";
import {
  demoCategories,
  demoDocuments,
  demoFeedback,
  demoSpaces,
  demoSpaceId,
} from "../../mock/data";
import "./index.scss";
import "./eval-compare.scss";

type ToastTone = "success" | "info" | "warning" | "error";
type ToastState = { tone: ToastTone; message: string } | null;

type LocalMessage = {
  id: string;
  role: "USER" | "ASSISTANT";
  content: string;
  status?: AnswerStatus;
  model?: string | null;
  citations: Citation[];
  query_diagnostics?: QueryDiagnostics | null;
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
    query_diagnostics: message.query_diagnostics,
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
  onEnter: (user: AuthUser) => void;
  onPublic: () => void;
}) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [rememberMe, setRememberMe] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (mode === "register" && !name.trim()) {
      setError("请输入你的称呼。");
      return;
    }
    if (!email.trim() || !email.includes("@")) {
      setError("请输入有效的邮箱地址。");
      return;
    }
    if (password.length < 8) {
      setError("密码至少需要 8 个字符。");
      return;
    }
    setError("");
    setBusy(true);
    try {
      const session = mode === "login"
        ? await login({ email: email.trim(), password }, rememberMe)
        : await register({ email: email.trim(), password, display_name: name.trim() });
      onEnter(session.user);
    } catch (requestError) {
      setError(requestError instanceof ApiRequestError ? requestError.message : "暂时无法完成登录，请稍后重试。");
    } finally {
      setBusy(false);
    }
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
              : "创建账号并进入你的知识工作区"}
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
              onConfirm={() => void submit()}
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
                onConfirm={() => void submit()}
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
              <Label
                className='remember-copy'
                for='remember-me'
              >
                <Checkbox
                  id='remember-me'
                  value='remember-me'
                  checked={rememberMe}
                  onChange={() => setRememberMe((current) => !current)}
                />
                <Text>记住我</Text>
              </Label>
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
          <Text className='auth-note'>登录后可管理私密空间、团队成员与公开问答范围。</Text>
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
    kind: SpaceKind;
  }) => Promise<boolean>;
  onRetry: () => void;
}) {
  const [showCreate, setShowCreate] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [visibility, setVisibility] = useState<SpaceVisibility>("PRIVATE");
  const [kind, setKind] = useState<SpaceKind>("PERSONAL");
  const [formError, setFormError] = useState("");
  const submitCreate = async () => {
    if (!name.trim()) {
      setFormError("请填写空间名称。");
      return;
    }
    setFormError("");
    const created = await onCreate({
      name: name.trim(),
      description: description.trim(),
      visibility,
      kind,
    });
    if (!created) return;
    setName("");
    setDescription("");
    setShowCreate(false);
  };
  return (
    <View className='page-stack'>
      <View className='page-heading'>
        <View>

          <Text className='page-title'>知识空间</Text>
          <Text className='page-description'>
            整理资料，让每个回答都有据可循。
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
          <View className='field'>
            <Text className='field-label'>空间类型</Text>
            <View className='segmented-control' role='group' aria-label='空间类型'>
              <Button className={kind === "PERSONAL" ? "segment is-selected" : "segment"}
                onClick={() => setKind("PERSONAL")} aria-pressed={kind === "PERSONAL"}
              >个人空间</Button>
              <Button className={kind === "TEAM" ? "segment is-selected" : "segment"}
                onClick={() => setKind("TEAM")} aria-pressed={kind === "TEAM"}
              >团队空间</Button>
            </View>
            <Text className='section-description'>个人空间仅拥有者管理；团队空间支持一位拥有者和多位管理员。</Text>
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
      {currentSpace && <View className='v2-panel'><Text className='section-title'>继续工作</Text><Text className='section-description'>{currentSpace.name}</Text><Button className='outline-button' onClick={() => onSelect(currentSpace)}>进入空间</Button></View>}
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

function DocumentsView({
  documents,
  categories,
  tags,
  error,
  onUpload,
  onDelete,
  onRetry,
  onSearch,
  onLoadTags,
  onSetTags,
  onAvailability,
  onOpen,
  onRetrieve,
}: {
  space: Space;
  documents: KnowledgeDocument[];
  categories: Category[];
  tags: KnowledgeTag[];
  error: string;
  onUpload: (
    file: UploadFile,
    categoryId: string | null,
    onProgress: (progress: number) => void,
  ) => Promise<void>;
  onDelete: (document: KnowledgeDocument) => Promise<void>;
  onRetry: (document: KnowledgeDocument) => Promise<void>;
  onSearch: (query: string, tagId?: string) => Promise<void>;
  onLoadTags: (document: KnowledgeDocument) => Promise<string[]>;
  onSetTags: (document: KnowledgeDocument, tagIds: string[]) => Promise<void>;
  onAvailability: (document: KnowledgeDocument, enabled: boolean) => Promise<void>;
  onOpen: (document: KnowledgeDocument) => void;
  onRetrieve: () => void;
}) {
  const fileInput = useRef<HTMLInputElement>(null);
  const [selectedCategory, setSelectedCategory] = useState<string>("");
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [fileError, setFileError] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [searchTag, setSearchTag] = useState("");
  const accept = ".pdf,.docx,.md,.markdown,.txt,.csv,.tsv,.pptx";
  const categoryOptions = ["不指定分类", ...categories.map((category) => category.name)];
  const selectedCategoryIndex = selectedCategory
    ? Math.max(0, categories.findIndex((category) => category.id === selectedCategory) + 1)
    : 0;
  useEffect(() => {
    const timer = setTimeout(() => {
      void onSearch(searchQuery.trim(), searchTag || undefined);
    }, 260);
    return () => clearTimeout(timer);
  }, [onSearch, searchQuery, searchTag]);
  const handleFile = async (file: UploadFile | null) => {
    if (!file) return;
    const extension = `.${file.name.split(".").pop()?.toLowerCase()}`;
    if (!accept.split(",").includes(extension)) {
      setFileError("支持 PDF、DOCX、Markdown、TXT、CSV/TSV 和 PPTX 文件。");
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
  const handleFiles = async (files: UploadFile[]) => {
    for (const file of files) await handleFile(file);
  };
  const openPicker = async () => {
    if (process.env.TARO_ENV === "h5") {
      fileInput.current?.click();
      return;
    }
    try {
      const result = await Taro.chooseMessageFile({
        count: 20,
        type: "file",
        extension: ["pdf", "docx", "md", "markdown", "txt", "csv", "tsv", "pptx"],
      });
      await handleFiles(result.tempFiles);
    } catch {
      setFileError("无法打开文件选择器，请重试。");
    }
  };
  return (
    <View className='page-stack documents-page'>
      <V2Heading title='资料管理' description='上传、更新与维护当前空间的资料。' actions={<V2Button kind='outline' onClick={onRetrieve}>检索测试</V2Button>} />
      <View className='upload-toolbar'>
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
          multiple
          accept={accept}
          onChange={(event) => void handleFiles(Array.from(event.target.files ?? []))}
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
        {uploading && (
          <Text className='drop-title'>
            {`正在上传 ${progress ? `${progress}%` : ""}`}
          </Text>
        )}
        <Text className='drop-hint'>
          支持 PDF、DOCX、Markdown、TXT、CSV/TSV、PPTX，单文件不超过 20 MB
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
      <View className='document-search-bar'>
        <View className='search-input-wrap'>
          <Icon name='search' />
          <Input
            value={searchQuery}
            placeholder='搜索文件名或处理信息…'
            onInput={(event) => setSearchQuery(valueOf(event))}
            aria-label='搜索文档'
          />
        </View>
        <View className='tag-filter-list' role='listbox' aria-label='按标签筛选'>
          <Button
            className={!searchTag ? 'tag-filter is-active' : 'tag-filter'}
            onClick={() => setSearchTag("")}
          >全部标签</Button>
          {tags.map((tag) => (
            <Button
              key={tag.id}
              className={searchTag === tag.id ? 'tag-filter is-active' : 'tag-filter'}
              onClick={() => setSearchTag(tag.id)}
            >{tag.name}</Button>
          ))}
        </View>
      </View>
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
              tags={tags}
              onDelete={onDelete}
              onRetry={onRetry}
              onLoadTags={onLoadTags}
              onSetTags={onSetTags}
              onAvailability={onAvailability}
              onOpen={onOpen}
            />
          ))}
        </View>
      )}
    </View>
  );
}

function DocumentRow({
  document,
  tags,
  onDelete,
  onRetry,
  onLoadTags,
  onSetTags,
  onAvailability,
  onOpen,
}: {
  document: KnowledgeDocument;
  tags: KnowledgeTag[];
  onDelete: (document: KnowledgeDocument) => Promise<void>;
  onRetry: (document: KnowledgeDocument) => Promise<void>;
  onLoadTags: (document: KnowledgeDocument) => Promise<string[]>;
  onSetTags: (document: KnowledgeDocument, tagIds: string[]) => Promise<void>;
  onAvailability: (document: KnowledgeDocument, enabled: boolean) => Promise<void>;
  onOpen: (document: KnowledgeDocument) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const localUpload = document.id.startsWith("document-");
  const [showTags, setShowTags] = useState(false);
  const [selectedTags, setSelectedTags] = useState<string[]>([]);
  const [tagsLoading, setTagsLoading] = useState(false);
  const [tagsLoaded, setTagsLoaded] = useState(false);
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
  const toggleTags = () => {
    const next = !showTags;
    setShowTags(next);
    if (!next || tagsLoaded || tagsLoading) return;
    setTagsLoading(true);
    void onLoadTags(document)
      .then((tagIds) => {
        setSelectedTags(tagIds);
        setTagsLoaded(true);
      })
      .finally(() => setTagsLoading(false));
  };
  return (
    <View className='document-row'>
      <View
        className={`document-type ${document.mime_type.includes("word") ? "docx" : "pdf"}`}
      >
        <Icon name='file' />
      </View>
      <View className='document-main'>
        <Button className='document-name text-button' disabled={localUpload} onClick={() => onOpen(document)}>{document.original_filename}</Button>
        <Text className='document-meta'>
          {formatFileSize(document.size_bytes)} ·{" "}
          {formatDate(document.created_at)}
        </Text>
        {document.failure_message && (
          <Text className='document-error'>{document.failure_message}</Text>
        )}
        <View className='document-meta-controls'>
          <Button
            className='text-button compact-text-button'
            onClick={toggleTags}
            disabled={localUpload}
          >标签</Button>
          <Button
            className='text-button compact-text-button'
            onClick={() => void onAvailability(document, document.is_enabled === false)}
            disabled={localUpload || busy}
          >{document.is_enabled === false ? '启用' : '停用'}</Button>
          {(document.effective_at || document.expires_at) && (
            <Text className='document-window'>
              {document.effective_at ? `生效 ${formatDate(document.effective_at)}` : ''}
              {document.expires_at ? ` · 截止 ${formatDate(document.expires_at)}` : ''}
            </Text>
          )}
        </View>
        {showTags && tags.length > 0 && (
          <View className='document-tag-editor' role='group' aria-label='文档标签'>
            {tagsLoading && <Text className='muted-copy'>正在读取已有标签…</Text>}
            {tags.map((tag) => {
              const selected = selectedTags.includes(tag.id);
              return (
                <Button
                  key={tag.id}
                  className={selected ? 'tag-filter is-active' : 'tag-filter'}
                  onClick={() => setSelectedTags((items) => selected ? items.filter((id) => id !== tag.id) : [...items, tag.id])}
                >{tag.name}</Button>
              );
            })}
            <Button
              className='outline-button compact'
              onClick={() => void onSetTags(document, selectedTags)}
              disabled={busy}
            >保存标签</Button>
          </View>
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
          onClick={() => setDeleting(true)}
          disabled={busy}
          aria-label={`删除 ${document.original_filename}`}
        >
          删除
        </Button>
      </View>
      {deleting && <ConfirmDialog title={`删除 ${document.original_filename}？`} description={localUpload ? "移除这条未完成的本地上传记录。" : "删除后，这份资料将不再参与新的检索与问答。"} action='删除资料' onCancel={() => setDeleting(false)} onConfirm={() => { setDeleting(false); void action(onDelete); }} />}
    </View>
  );
}

function QaView({
  initialQuestion,
  onRetrieve,
  messages,
  streaming,
  streamingText,
  onSend,
  onCancel,
  onFeedback,
  feedbackBusy,
}: {
  initialQuestion: string;
  onRetrieve: (question: string) => void;
  messages: LocalMessage[];
  streaming: boolean;
  streamingText: string;
  onSend: (question: string) => Promise<void>;
  onCancel: () => void;
  onFeedback: (messageId: string, rating: FeedbackRating) => Promise<void>;
  feedbackBusy: string | null;
}) {
  const [input, setInput] = useState(initialQuestion);
  const [sourceMessage, setSourceMessage] = useState<LocalMessage | null>(null);
  const [selectedOrdinal, setSelectedOrdinal] = useState<number | null>(null);
  const [sourcesOpen, setSourcesOpen] = useState(() => typeof window === 'undefined' || window.innerWidth > 760);
  useEffect(() => setInput(initialQuestion), [initialQuestion]);
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
  const lastQuestion = [...messages].reverse().find(message => message.role === "USER")?.content || input;
  const lastAnswerId = lastAssistant?.id;
  useEffect(() => { setSourceMessage(null); setSelectedOrdinal(null); }, [lastAnswerId]);
  useEffect(() => {
    if (selectedOrdinal != null) document.querySelector('.citation-panel')?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }, [selectedOrdinal, sourceMessage]);
  return (
    <View className='v2-page'>
    <V2Heading title='可信问答' description='基于当前空间资料，查看答案与回答依据。' actions={<V2Button kind='outline' onClick={() => onRetrieve(input)}>检索测试</V2Button>} />
    {lastAssistant?.status === "FAILED" && <div className='v2-notice v2-notice-danger' role='alert'><p>这次回答没有完成，问题已保留。调用失败不代表资料没有答案。</p><div className='v2-row'><V2Button disabled={streaming || !lastQuestion} onClick={() => { setInput(lastQuestion); void onSend(lastQuestion); }}>重试回答</V2Button><V2Button kind='outline' onClick={() => onRetrieve(lastQuestion)}>先查看检索依据</V2Button></div></div>}
    <View className='qa-layout'>
      <View className='qa-main'>
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
              onCitation={(source, ordinal) => { setSourceMessage(source); setSelectedOrdinal(ordinal); setSourcesOpen(true); }}
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
          <textarea data-v2-control
            className='resize-none qa-question-input'
            value={input}
            maxLength={2000}
            onChange={(event) => setInput(event.currentTarget.value)}
            onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); send(); } }}
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
        citations={(sourceMessage || lastAssistant)?.citations ?? []}
        status={(sourceMessage || lastAssistant)?.status}
        selectedOrdinal={selectedOrdinal} open={sourcesOpen} onToggle={setSourcesOpen}
      />
    </View>
    </View>
  );
}

function MessageBubble({
  message,
  onFeedback,
  feedbackBusy,
  onCitation,
}: {
  message: LocalMessage;
  onFeedback: (messageId: string, rating: FeedbackRating) => Promise<void>;
  feedbackBusy: string | null;
  onCitation: (message: LocalMessage, ordinal: number) => void;
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
        {!!message.citations.length && <div className='v2-row'>{message.citations.map(citation => <V2Button key={citation.ordinal} kind='ghost' onClick={() => onCitation(message, citation.ordinal)}>[{citation.ordinal}] {citation.document_name}</V2Button>)}</div>}
        {message.query_diagnostics && (
          <details className='query-diagnostics'>
            <summary>查看问题改写与子问题证据</summary>
            <div className='query-diagnostics-body'>
              <div className='query-diagnostic-question'>
                <Text className='query-diagnostic-label'>用户原问题</Text>
                <Text>{message.query_diagnostics.original_question}</Text>
              </div>
              <div className='query-diagnostic-question'>
                <Text className='query-diagnostic-label'>
                  实际检索问题 · {message.query_diagnostics.was_rewritten ? '已补全指代' : '沿用原问题'}
                </Text>
                <Text>{message.query_diagnostics.retrieval_question}</Text>
              </div>
              {message.query_diagnostics.queries.map((trace, index) => (
                <div className='query-trace' key={`${trace.kind}-${index}`}>
                  <Text className='query-trace-title'>
                    {trace.kind === 'primary' ? '主问题检索' : `拆分问题 ${index}`}
                  </Text>
                  <Text className='query-trace-question'>{trace.query}</Text>
                  {trace.evidence.length ? (
                    <div className='query-evidence-list'>
                      {trace.evidence.map((evidence) => (
                        <div className='query-evidence-row' key={`${trace.kind}-${index}-${evidence.chunk_id}`}>
                          <div className='query-evidence-source'>
                            <Text className='query-evidence-rank'>#{evidence.rank}</Text>
                            <Text className='query-evidence-name' aria-label={`${evidence.document_name}，片段 ${evidence.ordinal}`}>
                              {evidence.document_name} · 片段 {evidence.ordinal}
                            </Text>
                          </div>
                          <Text className={evidence.selected_for_context ? 'query-context-status is-selected' : 'query-context-status'}>
                            {evidence.selected_for_context ? '已进入回答上下文' : '未进入回答上下文'}
                          </Text>
                          <Text className='query-evidence-score'>排序分数 {evidence.score.toFixed(3)} · {evidence.score_kind}</Text>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <Text className='query-evidence-empty'>未命中片段</Text>
                  )}
                </div>
              ))}
              <Text className='query-diagnostics-note'>排序分数不代表答案正确率；进入回答上下文也不等于最终引用。</Text>
            </div>
          </details>
        )}
        <Text className='message-time'>
          {formatTime(message.created_at)} ·{" "}
          {message.model || (message.status === "FAILED" ? "未生成回答" : "模型信息未记录")}
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
  selectedOrdinal,
  open,
  onToggle,
}: {
  citations: Citation[];
  status?: AnswerStatus;
  selectedOrdinal: number | null;
  open: boolean;
  onToggle: (open: boolean) => void;
}) {
  return (
    <details className='citation-panel' open={open} onToggle={event => onToggle(event.currentTarget.open)}>
      <summary className='citation-heading'>
        <View>
          <Text className='section-title'>回答依据</Text>
          <Text className='section-description'>
            所有者可查看原文片段与位置
          </Text>
        </View>
        <StatusPill status={citations.length ? "ready" : "neutral"}>
          {citations.length ? `${citations.length} 条来源` : "暂无来源"}
        </StatusPill></summary>
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
              className={selectedOrdinal === citation.ordinal ? 'citation-card is-selected' : 'citation-card'}
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
                {citation.source_available === false && <Text className='document-error'>历史依据已失效 · 不可用于新回答</Text>}
                <Text className='citation-score'>
                  排序分数 {citation.score.toFixed(6)} · 仅用于排序
                </Text>
              </View>
              <Icon name='arrow' />
            </View>
          ))}
        </View>
      )}
    </details>
  );
}

function PublicSettingsView({
  space,
  categories,
  tags,
  links,
  publicQuestions,
  publicAnalytics,
  onToggle,
  onCreateCategory,
  onCreateTag,
  onDeleteTag,
  onShare,
  onRevoke,
  onModerateQuestion,
}: {
  space: Space;
  categories: Category[];
  tags: KnowledgeTag[];
  links: ShareLink[];
  publicQuestions: PublicQuestionRecord[];
  publicAnalytics: PublicAnalytics | null;
  onToggle: (category: Category) => Promise<void>;
  onCreateCategory: (name: string) => Promise<boolean>;
  onCreateTag: (name: string) => Promise<void>;
  onDeleteTag: (tag: KnowledgeTag) => Promise<void>;
  onShare: (options?: { password?: string; visitor_question_limit?: number | null; allowed_origins?: string[] }) => Promise<CreatedShareLink | null>;
  onRevoke: (link: ShareLink) => Promise<void>;
  onModerateQuestion: (item: PublicQuestionRecord) => Promise<void>;
}) {
  const [categoryName, setCategoryName] = useState("");
  const [tagName, setTagName] = useState("");
  const [sharePassword, setSharePassword] = useState("");
  const [questionLimit, setQuestionLimit] = useState("");
  const [shareOrigin, setShareOrigin] = useState("");
  const [showSharePassword, setShowSharePassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [shareResult, setShareResult] = useState<CreatedShareLink | null>(null);
  const [localError, setLocalError] = useState("");
  const openCategories = categories.filter((category) => category.is_open);
  const copyShare = async () => {
    if (!shareResult) return;
    try {
      await Taro.setClipboardData({
        data: publicShareUrl(shareResult.token),
      });
      setLocalError("分享链接已复制到剪贴板。");
    } catch {
      setLocalError("复制失败，请手动复制下方链接。");
    }
  };
  const embedSnippet = shareResult
    ? `<div id="knowledge-widget"></div>\n<script src="${typeof window !== "undefined" ? window.location.origin : ""}/aiknowledge-embed.js"></script>\n<script>AiKnowledgeEmbed.mount({ token: "${shareResult.token}", target: "#knowledge-widget", publicUrl: "${typeof window !== "undefined" ? window.location.origin : ""}" });</script>`
    : "";
  const copyEmbed = async () => {
    if (!embedSnippet) return;
    try {
      await Taro.setClipboardData({ data: embedSnippet });
      setLocalError("嵌入代码已复制到剪贴板。");
    } catch {
      setLocalError("复制失败，请手动复制下方嵌入代码。");
    }
  };
  const addCategory = async () => {
    if (!categoryName.trim()) return;
    setBusy(true);
    try {
      if (await onCreateCategory(categoryName.trim())) setCategoryName("");
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
                  {category.display_description || category.description || "暂无分类说明"}
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
            className='text-input'
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
      <View className='settings-card tag-settings-card'>
        <View className='card-heading'>
          <View>
            <Text className='section-title'>知识标签</Text>
            <Text className='section-description'>用标签整理文档，便于快速筛选。</Text>
          </View>
        </View>
        <View className='add-category'>
          <Input
            className='text-input'
            value={tagName}
            placeholder='新增标签，例如：产品、合规'
            onInput={(event) => setTagName(valueOf(event))}
            aria-label='新增知识标签'
          />
          <Button
            className='outline-button compact'
            onClick={async () => {
              if (!tagName.trim()) return;
              setBusy(true);
              try { await onCreateTag(tagName.trim()); setTagName(""); } finally { setBusy(false); }
            }}
            disabled={busy}
          >新增标签</Button>
        </View>
        {tags.length > 0 && (
          <View className='tag-manager-list'>
            {tags.map((tag) => (
              <View className='managed-tag' key={tag.id}>
                <Text>{tag.name}</Text>
                <Button className='text-button compact-text-button' onClick={() => void onDeleteTag(tag)}>删除</Button>
              </View>
            ))}
          </View>
        )}
      </View>
      <View className='settings-card share-card'>
        <View className='card-heading'>
          <View>
            <Text className='section-title'>分享链接</Text>
            <Text className='section-description'>
              访客只能查看以上 {openCategories.length} 个已开放分类的回答。
            </Text>
          </View>
          <View className='share-controls'>
            <View className='secret-input share-secret-input'>
              <Input
                value={sharePassword}
                type='text'
                password={!showSharePassword}
                placeholder='访问密码（可选）'
                onInput={(event) => setSharePassword(valueOf(event))}
                aria-label='分享访问密码'
              />
              <Button
                className='input-action'
                size='mini'
                onClick={() => setShowSharePassword((value) => !value)}
                aria-label={showSharePassword ? '隐藏分享密码' : '显示分享密码'}
              >{showSharePassword ? '隐藏' : '显示'}</Button>
            </View>
            <Input
              className='text-input share-limit-input'
              type='number'
              value={questionLimit}
              placeholder='访客提问上限（可选）'
              onInput={(event) => setQuestionLimit(valueOf(event))}
              aria-label='访客提问上限'
            />
            <Input
              className='text-input share-origin-input'
              value={shareOrigin}
              placeholder='允许来源（可选，如 https://example.com）'
              onInput={(event) => setShareOrigin(valueOf(event))}
              aria-label='分享链接允许来源'
            />
          </View>
          <Button
            className='primary-button'
            onClick={async () => {
              setBusy(true);
              const parsedLimit = Number(questionLimit);
              const result = await onShare({
                password: sharePassword.trim() || undefined,
                visitor_question_limit: Number.isFinite(parsedLimit) && parsedLimit > 0 ? parsedLimit : null,
                allowed_origins: shareOrigin.trim() ? [shareOrigin.trim()] : [],
              });
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
            <Text className='share-url'>{publicShareUrl(shareResult.token)}</Text>
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
        {shareResult && (
          <View className='embed-snippet'>
            <View className='embed-snippet-heading'>
              <View><Text className='section-title'>嵌入到已有页面</Text><Text className='section-description'>加载脚本后会在目标容器中打开同一套公开问答界面。</Text></View>
              <Button className='outline-button compact' onClick={() => void copyEmbed()}>复制代码</Button>
            </View>
            <Text className='embed-snippet-code'>{embedSnippet}</Text>
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
      <View className='settings-card public-question-log-card'>
        <View className='card-heading'>
          <View>
            <Text className='section-title'>访客提问记录</Text>
            <Text className='section-description'>仅保存匿名标识与问题摘要哈希，便于观察公开入口使用情况。</Text>
          </View>
          <StatusPill status={publicQuestions.length ? 'ready' : 'neutral'}>
            {publicQuestions.length} 条
          </StatusPill>
        </View>
        {publicQuestions.length === 0 ? (
          <Text className='muted-copy'>暂时没有访客提问记录。</Text>
        ) : (
          <View className='public-question-log-list'>
            {publicQuestions.slice(0, 20).map((item) => (
              <View className='public-question-log-row' key={item.id}>
                <View>
                  <Text className='public-question-log-time'>{formatDate(item.created_at)}</Text>
                  <Text className='public-question-log-hash'>问题指纹 {item.question_hash.slice(0, 12)}…</Text>
                </View>
                <Text className='public-question-log-visitor'>访客 {item.visitor_id.slice(0, 8)}</Text>
                <StatusPill status={item.is_hidden ? 'warning' : 'neutral'}>
                  {item.is_hidden ? '已隐藏' : '可见'}
                </StatusPill>
                <Button
                  className='text-button compact-text-button'
                  onClick={() => void onModerateQuestion(item)}
                >{item.is_hidden ? '取消隐藏' : '隐藏'}</Button>
              </View>
            ))}
          </View>
        )}
      </View>
      <View className='settings-card public-analytics-card'>
        <View className='card-heading'>
          <View>
            <Text className='section-title'>公开入口统计</Text>
            <Text className='section-description'>最近 30 天的匿名访问趋势，不记录问题原文。</Text>
          </View>
          <StatusPill status={publicAnalytics ? 'ready' : 'neutral'}>
            {publicAnalytics ? '已同步' : '暂无数据'}
          </StatusPill>
        </View>
        {publicAnalytics ? (
          <>
            <View className='public-analytics-grid'>
              <View><Text className='analytics-number'>{publicAnalytics.sessions}</Text><Text>访问会话</Text></View>
              <View><Text className='analytics-number'>{publicAnalytics.conversations}</Text><Text>对话</Text></View>
              <View><Text className='analytics-number'>{publicAnalytics.questions}</Text><Text>问题</Text></View>
              <View><Text className='analytics-number'>{publicAnalytics.unique_visitors}</Text><Text>匿名访客</Text></View>
            </View>
            <View className='public-call-stats'>
              <Text>模型调用 {publicAnalytics.answer_count ?? 0} 次</Text>
              <Text>失败 {publicAnalytics.failed_answers ?? 0} 次</Text>
              <Text>P50 {publicAnalytics.latency_p50_ms ?? '—'} ms</Text>
              <Text>P95 {publicAnalytics.latency_p95_ms ?? '—'} ms</Text>
              <Text>Token {(publicAnalytics.input_tokens ?? 0) + (publicAnalytics.output_tokens ?? 0)}</Text>
            </View>
            {publicAnalytics.daily.length > 0 && (
              <View className='public-analytics-daily'>
                {publicAnalytics.daily.slice(-7).map((item) => (
                  <View className='public-analytics-day' key={item.date}>
                    <Text>{item.date.slice(5)}</Text><Text>{item.questions} 问题</Text>
                  </View>
                ))}
              </View>
            )}
          </>
        ) : <Text className='muted-copy'>公开入口产生访问后，这里会显示统计。</Text>}
      </View>
    </View>
  );
}

function FeedbackView({
  feedback,
  loading,
  onRetry,
  onReview,
  onRepair,
  onRetest,
}: {
  feedback: Feedback[];
  loading: boolean;
  onRetry: () => void;
  onRepair: () => void;
  onRetest: (item: Feedback) => void;
  onReview: (item: Feedback, input: {
    review_status: "PENDING" | "FIXED" | "DEFERRED";
    corrected_answer?: string | null;
    review_note?: string | null;
    data_usage_scope?: string;
    pii_status?: string;
  }) => Promise<void>;
}) {
  const [filter, setFilter] = useState<"ALL" | FeedbackRating>("ALL");
  const filtered =
    filter === "ALL"
      ? feedback
      : feedback.filter((item) => item.rating === filter);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [correctedAnswer, setCorrectedAnswer] = useState("");
  const [reviewNote, setReviewNote] = useState("");
  return (
    <View className='page-stack feedback-page'>
      <V2Heading title='反馈队列' description='把用户反馈变成资料修复与复测任务。' />
      <View className='feedback-metrics'>
        <FeedbackMetric
          tone='negative'
          label='负面反馈'
          value={feedback.filter((item) => item.rating === "DOWN").length}
        />
        <FeedbackMetric
          tone='pending'
          label='待处理'
          value={
            feedback.filter((item) => item.rating === "NEEDS_CORRECTION" && item.review_status !== "FIXED")
              .length
          }
        />
        <FeedbackMetric
          tone='positive'
          label='已修正'
          value={feedback.filter((item) => item.review_status === "FIXED").length}
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
            <Text>审核状态</Text>
            <Text>反馈时间</Text>
            <Text>操作</Text>
          </View>
          {filtered.map((item) => (
            <View className='feedback-table-row' key={item.id}>
              <Text className='feedback-question'>
                {item.question || "历史问题未记录"}
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
              <Text>
                <StatusPill status={item.review_status === "FIXED" ? "ready" : item.review_status === "DEFERRED" ? "neutral" : "warning"}>
                  {item.review_status === "FIXED" ? "已修正" : item.review_status === "DEFERRED" ? "已延期" : "待处理"}
                </StatusPill>
              </Text>
              <Text className='tabular'>{formatDate(item.created_at)}</Text>
              <View className='feedback-actions'>
                <Button
                  className='outline-button compact'
                  onClick={() => {
                    setEditingId(editingId === item.id ? null : item.id);
                    setCorrectedAnswer(item.corrected_answer || "");
                    setReviewNote(item.review_note || "");
                  }}
                >{editingId === item.id ? "收起" : "审核"}</Button>
              </View>
              {editingId === item.id && (
                <View className='feedback-review-editor'>
                  <Text className='section-title'>原回答</Text><Text>{item.original_answer || "历史回答未记录"}</Text>
                  <Text className='section-title'>反馈说明</Text><Text>{item.comment || "未填写说明"}</Text>
                  <View className='feedback-review-actions'><Button className='outline-button compact' onClick={onRepair}>补充资料</Button>
                    {item.eval_case_id ? <Button className='outline-button compact' onClick={() => onRetest(item)}>查看回归题</Button> :
                      <Button className='outline-button compact' disabled={!item.question || item.review_status !== 'FIXED' || !item.corrected_answer}
                        onClick={() => onRetest(item)}>{item.review_status === 'FIXED' && item.corrected_answer ? '加入回归题集' : '标记修正后可加入'}</Button>}
                  </View>
                  <textarea
                    data-feedback-answer
                    className='text-input resize-none'
                    value={correctedAnswer}
                    placeholder='人工修正答案（标记为已修正时必填）'
                    maxLength={5000}
                    onChange={(event) => setCorrectedAnswer(event.currentTarget.value)}
                    aria-label='人工修正答案'
                  />
                  <Input
                    className='text-input'
                    value={reviewNote}
                    placeholder='审核说明（可选）'
                    onInput={(event) => setReviewNote(valueOf(event))}
                    aria-label='审核说明'
                  />
                  <View className='feedback-review-actions'>
                    <Button className='primary-button compact' onClick={() => void onReview(item, { review_status: "FIXED", corrected_answer: correctedAnswer, review_note: reviewNote, data_usage_scope: "INTERNAL_ONLY", pii_status: "UNKNOWN" })}>标记已修正</Button>
                    <Button className='outline-button compact' onClick={() => void onReview(item, { review_status: "DEFERRED", review_note: reviewNote, data_usage_scope: "INTERNAL_ONLY", pii_status: "UNKNOWN" })}>暂缓处理</Button>
                  </View>
                </View>
              )}
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

function SettingsView({
  space,
  onVisibilityChange,
  onPlanChange,
  sources,
  onCreateSource,
  onSyncSource,
  onToggleSource,
  members,
  onAddMember,
  onChangeMemberRole,
  onRemoveMember,
  usage,
}: {
  space: Space;
  onVisibilityChange: (visibility: SpaceVisibility) => Promise<void>;
  onPlanChange: (plan: SpacePlan) => Promise<void>;
  sources: KnowledgeSource[];
  onCreateSource: (input: { kind: SourceKind; locator: string; name?: string }) => Promise<void>;
  onSyncSource: (source: KnowledgeSource) => Promise<void>;
  onToggleSource: (source: KnowledgeSource) => Promise<void>;
  members: SpaceMember[];
  onAddMember: (email: string, role: "ADMIN" | "EDITOR" | "MEMBER") => Promise<void>;
  onChangeMemberRole: (member: SpaceMember, role: "ADMIN" | "EDITOR" | "MEMBER") => Promise<void>;
  onRemoveMember: (member: SpaceMember) => Promise<void>;
  usage: SpaceUsage | null;
}) {
  const [memberEmail, setMemberEmail] = useState("");
  const [memberRole, setMemberRole] = useState<"ADMIN" | "EDITOR" | "MEMBER">("MEMBER");
  const [memberBusy, setMemberBusy] = useState(false);
  const [planBusy, setPlanBusy] = useState(false);
  const [sourceKind, setSourceKind] = useState<SourceKind>("WEBPAGE");
  const [sourceLocator, setSourceLocator] = useState("");
  const [sourceName, setSourceName] = useState("");
  const [sourceBusy, setSourceBusy] = useState(false);

  const add = async () => {
    const email = memberEmail.trim();
    if (!email || !email.includes("@")) return;
    setMemberBusy(true);
    try {
      await onAddMember(email, memberRole);
      setMemberEmail("");
    } finally {
      setMemberBusy(false);
    }
  };

  const roleLabel = (role: SpaceMember["role"]) =>
    role === "OWNER" ? "拥有者（管理员）" : role === "ADMIN" ? "管理员" : role === "EDITOR" ? "编辑者" : "成员";

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
      <View className='settings-card source-settings'>
        <View className='card-heading'>
          <View>
            <Text className='section-title'>外部知识来源</Text>
            <Text className='section-description'>登记网页、Markdown 或 FAQ 地址，手动同步后会按普通文档进入解析与检索。</Text>
          </View>
          <StatusPill status={sources.length ? "ready" : "neutral"}>{sources.length} 个来源</StatusPill>
        </View>
        <View className='source-create-row'>
          <Picker
            mode='selector'
            range={['网页', 'Markdown 仓库', 'FAQ 表格']}
            value={sourceKind === 'WEBPAGE' ? 0 : sourceKind === 'MARKDOWN_REPOSITORY' ? 1 : 2}
            onChange={(event) => {
              const index = Number(event.detail.value);
              setSourceKind(index === 1 ? 'MARKDOWN_REPOSITORY' : index === 2 ? 'FAQ_TABLE' : 'WEBPAGE');
            }}
          >
            <View className='select-like source-kind-select' aria-label='来源类型'>
              <Text>{sourceKind === 'WEBPAGE' ? '网页' : sourceKind === 'MARKDOWN_REPOSITORY' ? 'Markdown 仓库' : 'FAQ 表格'}</Text><Text>⌄</Text>
            </View>
          </Picker>
          <Input
            className='text-input source-locator-input'
            value={sourceLocator}
            placeholder='https://example.com/knowledge.md'
            onInput={(event) => setSourceLocator(valueOf(event))}
            aria-label='来源地址'
          />
          <Input
            className='text-input source-name-input'
            value={sourceName}
            placeholder='名称（可选）'
            onInput={(event) => setSourceName(valueOf(event))}
            aria-label='来源名称'
          />
          <Button
            className='primary-button compact'
            disabled={sourceBusy || !sourceLocator.trim()}
            onClick={async () => {
              setSourceBusy(true);
              try {
                await onCreateSource({ kind: sourceKind, locator: sourceLocator.trim(), ...(sourceName.trim() ? { name: sourceName.trim() } : {}) });
                setSourceLocator('');
                setSourceName('');
              } finally { setSourceBusy(false); }
            }}
          >{sourceBusy ? '登记中…' : '登记来源'}</Button>
        </View>
        {sources.length === 0 ? (
          <Text className='muted-copy'>暂未登记外部来源。你也可以直接上传本地资料。</Text>
        ) : (
          <View className='source-list' role='list' aria-label='外部知识来源列表'>
            {sources.map((source) => (
              <View className='source-row' role='listitem' key={source.id}>
                <View className='source-main'>
                  <Text className='source-name'>{source.name || source.locator}</Text>
                  <Text className='source-meta'>{source.kind === 'WEBPAGE' ? '网页' : source.kind === 'MARKDOWN_REPOSITORY' ? 'Markdown 仓库' : 'FAQ 表格'} · {source.locator}</Text>
                  {source.last_error && <Text className='form-hint source-error'>{source.last_error}</Text>}
                </View>
                <StatusPill status={source.status === 'FAILED' ? 'warning' : source.status === 'READY' ? 'ready' : 'neutral'}>
                  {source.status === 'READY' ? '已同步' : source.status === 'SYNCING' ? '同步中' : source.status === 'FAILED' ? '同步失败' : source.status === 'DISABLED' ? '已停用' : '待同步'}
                </StatusPill>
                <View className='source-actions'>
                  <Button className='text-button compact-text-button' disabled={source.status === 'SYNCING'} onClick={() => void onSyncSource(source)}>同步</Button>
                  <Button className='outline-button compact' onClick={() => void onToggleSource(source)}>{source.status === 'DISABLED' ? '启用' : '停用'}</Button>
                </View>
              </View>
            ))}
          </View>
        )}
      </View>
      <View className='settings-card plan-settings'>
        <View className='settings-row'>
          <View>
            <Text className='section-title'>套餐权益</Text>
            <Text className='section-description'>演示阶段可切换额度，用于验证不同套餐的资源边界；暂不连接支付渠道。</Text>
          </View>
          <View className='segmented-control plan-selector' aria-label='选择套餐'>
            {([['FREE', '免费版'], ['PRO', '专业版'], ['TEAM', '小团队版']] as const).map(([plan, label]) => (
              <Button
                key={plan}
                className={(space.plan ?? usage?.plan ?? 'FREE') === plan ? 'segment is-selected' : 'segment'}
                disabled={planBusy}
                onClick={async () => {
                  setPlanBusy(true);
                  try { await onPlanChange(plan); } finally { setPlanBusy(false); }
                }}
                aria-pressed={(space.plan ?? usage?.plan ?? 'FREE') === plan}
              >{label}</Button>
            ))}
          </View>
        </View>
      </View>
      {usage && (
        <View className='settings-card usage-settings'>
          <View className='card-heading'>
            <View>
              <Text className='section-title'>套餐与用量</Text>
              <Text className='section-description'>当前套餐仅控制资源上限，不连接支付渠道。</Text>
            </View>
            <StatusPill status={usage.plan === "FREE" ? "neutral" : "ready"}>
              {usage.plan === "FREE" ? "个人免费版" : usage.plan === "PRO" ? "个人专业版" : "小团队版"}
            </StatusPill>
          </View>
          <View className='usage-grid'>
            <UsageItem label='文档' used={usage.documents_used} limit={usage.limits.documents} />
            <UsageItem label='成员' used={usage.members_used} limit={usage.limits.members} />
            <UsageItem label='今日提问' used={usage.questions_used_today} limit={usage.limits.questions_per_day} />
          </View>
        </View>
      )}
      <View className='settings-card members-settings'>
        <View className='card-heading'>
          <View>
            <Text className='section-title'>成员与权限</Text>
            <Text className='section-description'>
              {space.kind === "TEAM" ? "团队拥有者可添加多位管理员、编辑者和只读成员。管理员可查看引用、使用检索调试和管理评测。" : "个人空间仅拥有者负责管理，不添加其他成员。"}
            </Text>
          </View>
          <StatusPill status='ready'>服务端鉴权</StatusPill>
        </View>
        {space.kind === "TEAM" && space.owner_user_id === getAuthUserId() && <View className='member-invite'>
          <Input
            className='text-input member-email-input'
            value={memberEmail}
            onInput={(event) => setMemberEmail(valueOf(event))}
            onConfirm={() => void add()}
            type='text'
            placeholder='输入成员邮箱'
            aria-label='成员邮箱'
          />
          <View className='member-role-picker' role='group' aria-label='成员角色'>
            <Button
              className={memberRole === "MEMBER" ? "segment is-selected" : "segment"}
              onClick={() => setMemberRole("MEMBER")}
              aria-pressed={memberRole === "MEMBER"}
            >只读成员</Button>
            <Button
              className={memberRole === "EDITOR" ? "segment is-selected" : "segment"}
              onClick={() => setMemberRole("EDITOR")}
              aria-pressed={memberRole === "EDITOR"}
            >编辑者</Button>
            <Button className={memberRole === "ADMIN" ? "segment is-selected" : "segment"}
              onClick={() => setMemberRole("ADMIN")} aria-pressed={memberRole === "ADMIN"}
            >管理员</Button>
          </View>
          <Button
            className='primary-button compact member-invite-button'
            onClick={() => void add()}
            disabled={memberBusy || !memberEmail.trim()}
            aria-busy={memberBusy}
          >{memberBusy ? "添加中…" : "添加成员"}</Button>
        </View>}
        <View className='member-list' role='list' aria-label='空间成员'>
          {members.length === 0 && (
            <View className='empty-state compact-empty'>
              <Text>暂无成员记录。添加后，成员会在这里显示。</Text>
            </View>
          )}
          {members.map((member) => (
            <View className='member-row' role='listitem' key={member.user_id}>
              <View className='member-avatar' aria-hidden='true'>
                <Text>{(member.display_name || member.email || "?").slice(0, 1).toUpperCase()}</Text>
              </View>
              <View className='member-identity'>
                <Text className='member-name'>{member.display_name || "未命名成员"}</Text>
                <Text className='member-email'>{member.email}</Text>
              </View>
              <StatusPill status={member.role === "OWNER" ? "ready" : "neutral"}>
                {roleLabel(member.role)}
              </StatusPill>
              {member.role !== "OWNER" && space.kind === "TEAM" && space.owner_user_id === getAuthUserId() && (
                <View className='member-actions'>
                  {(["ADMIN", "EDITOR", "MEMBER"] as const).filter((role) => role !== member.role).map((role) => (
                    <Button key={role} className='text-button compact-text-button'
                      onClick={() => void onChangeMemberRole(member, role)}
                    >设为{roleLabel(role)}</Button>
                  ))}
                  <Button
                    className='danger-button compact'
                    onClick={() => void onRemoveMember(member)}
                  >移除</Button>
                </View>
              )}
            </View>
          ))}
        </View>
      </View>
      <View className='auth-placeholder'>
        <Icon name='lock' />
        <View>
          <Text className='section-title'>安全边界</Text>
          <Text className='section-description'>
            拥有者、团队管理员、编辑者与成员的空间访问均由服务端校验；分享链接仍单独受公开访问密码、分类范围和问题配额约束。
          </Text>
        </View>
      </View>
    </View>
  );
}

function UsageItem({ label, used, limit }: { label: string; used: number; limit: number }) {
  const percentage = Math.min(100, Math.round((used / Math.max(limit, 1)) * 100));
  return (
    <View className='usage-item'>
      <View className='usage-item-heading'><Text>{label}</Text><Text>{used} / {limit}</Text></View>
      <View className='usage-track' aria-label={`${label}使用量 ${used} / ${limit}`}><View className='usage-bar' style={{ width: `${percentage}%` }} /></View>
      <Text className='usage-remaining'>剩余 {Math.max(limit - used, 0)}</Text>
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
  const [authUser, setAuthUser] = useState<AuthUser | null>(null);
  const [activePage, setActivePage] = useState<WorkspacePage>("spaces");
  const [handoffQuestion, setHandoffQuestion] = useState("");
  const [handoffStrategy,setHandoffStrategy]=useState<'dense' | 'hybrid' | 'hybrid_rerank'>('dense');
  const [handoffMetadataFilter, setHandoffMetadataFilter] = useState<RetrievalMetadataFilter>(emptyRetrievalMetadataFilter)
  const [evalDraft, setEvalDraft] = useState<{ question: string; answer: string; feedbackId: string; caseId?: string; scope: 'OWNER' | 'PUBLIC'; categoryIds: string[] } | null>(null);
  const [feedbackDraft, setFeedbackDraft] = useState<{ messageId: string; rating: FeedbackRating } | null>(null);
  const [selectedDocumentId, setSelectedDocumentId] = useState<string | null>(null);
  const [spaces, setSpaces] = useState<Space[]>([]);
  const [currentSpace, setCurrentSpace] = useState<Space | null>(null);
  const [categories, setCategories] = useState<Category[]>([]);
  const [tags, setTags] = useState<KnowledgeTag[]>([]);
  const [members, setMembers] = useState<SpaceMember[]>([]);
  const [usage, setUsage] = useState<SpaceUsage | null>(null);
  const [publicQuestions, setPublicQuestions] = useState<PublicQuestionRecord[]>([]);
  const [publicAnalytics, setPublicAnalytics] = useState<PublicAnalytics | null>(null);
  const [sources, setSources] = useState<KnowledgeSource[]>([]);
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [documentsError, setDocumentsError] = useState("");
  const [feedback, setFeedback] = useState<Feedback[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<LocalMessage[]>([]);
  const [shareLinks, setShareLinks] = useState<ShareLink[]>([]);
  const [loadingSpaces, setLoadingSpaces] = useState(false);
  const [loadingFeedback, setLoadingFeedback] = useState(false);
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
  const failedUploads = useRef(new Map<string, { file: UploadFile; categoryId: string | null }>());

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
      isLocalDemoId(spaceId),
    [currentSpace?.id],
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
    void getMe()
      .then((user) => {
        setAuthUser(user);
        setLoggedIn(true);
      })
      .catch(() => {
        // The login form owns the recoverable unauthenticated state.
      });
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
                : activePage === "retrieval" ? "检索测试 · 知溯" : "空间设置 · 知溯";
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
      const allowDemo = router.params.view === "workspace" && !authUser;
      if (allowDemo) setSpaces(demoSpaces);
      setUsingDemo(allowDemo);
      setPageError(
        error instanceof ApiRequestError
          ? error.message
          : "空间列表加载失败，请重试。",
      );
    } finally {
      setLoadingSpaces(false);
    }
  }, [authUser, router.params.view]);
  useEffect(() => {
    if (loggedIn) void loadSpaces();
  }, [loggedIn, loadSpaces]);

  const loadSpaceData = useCallback(async (space: Space, destination: WorkspacePage = "qa") => {
    stopAllDocumentPolling();
    selectedSpaceId.current = space.id;
    setCurrentSpace(space);
    setHandoffQuestion("");
    setHandoffStrategy('dense');
    setEvalDraft(null);
    setSelectedDocumentId(null);
    setActivePage(destination);
    setConversationId(readStoredConversationId(space.id));
    setMessages([]);
    setDocuments([]);
    setDocumentsError("");
    setSources([]);
    void restoreConversation(space.id);
    try {
      setCategories(await listCategories(space.id));
    } catch {
      setCategories(space.id === demoSpaceId ? demoCategories : []);
    }
    try {
      setTags(await listTags(space.id));
    } catch {
      setTags([]);
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
  }, [readStoredConversationId, restoreConversation, stopAllDocumentPolling, trackDocumentProcessing]);
  const loadShareLinks = useCallback(async (space: Space) => {
    try {
      setShareLinks(await listShareLinks(space.id));
    } catch {
      setShareLinks([]);
    }
  }, []);
  const loadMembers = useCallback(async (space: Space) => {
    try {
      setMembers(await listMembers(space.id));
    } catch {
      setMembers([]);
    }
  }, []);
  const loadUsage = useCallback(async (space: Space) => {
    try {
      setUsage(await getSpaceUsage(space.id));
    } catch {
      setUsage(null);
    }
  }, []);
  const loadPublicQuestions = useCallback(async (space: Space) => {
    try {
      setPublicQuestions(await listPublicQuestionRecords(space.id));
    } catch {
      setPublicQuestions([]);
    }
  }, []);
  const loadPublicAnalytics = useCallback(async (space: Space) => {
    try {
      setPublicAnalytics(await getPublicAnalytics(space.id));
    } catch {
      setPublicAnalytics(null);
    }
  }, []);
  const loadSources = useCallback(async (space: Space) => {
    try {
      setSources(await listSources(space.id));
    } catch {
      setSources([]);
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
        const answer = await streamOwnerAnswer(id, question, setStreamingText, controller?.signal, handoffStrategy, handoffMetadataFilter);
        setMessages((items) => [
          ...items,
          {
            id: answer.message_id,
            role: "ASSISTANT",
            content: answer.answer,
            status: answer.status,
            model: answer.model,
            citations: answer.citations,
            query_diagnostics: answer.query_diagnostics,
            created_at: now(),
          },
        ]);
      } catch (error) {
        if (controller?.signal.aborted) return;
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
      } finally {
        if (streamAbort.current === controller) streamAbort.current = null;
        setStreaming(false);
        setStreamingText("");
      }
    },
    [currentSpace, ensureConversation, forgetConversationId, handoffStrategy, handoffMetadataFilter],
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
      } catch (error) {
        if (!isDemoSpace()) {
          setToast({ tone: "error", message: error instanceof ApiRequestError ? error.message : "反馈保存失败，请重试。" });
          return;
        }
        setToast({
          tone: "info",
          message: "演示反馈已记录；连接 API 后会保存到反馈中心。",
        });
      } finally {
        setFeedbackBusy(null);
      }
    },
    [isDemoSpace],
  );
  const handleCreateSpace = useCallback(
    async (input: {
      name: string;
      description: string;
      visibility: SpaceVisibility;
      kind: SpaceKind;
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
      } catch (error) {
        if (!usingDemo) {
          setToast({ tone: "error", message: error instanceof ApiRequestError ? error.message : "空间创建失败，请重试。" });
          return false;
        }
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
      return true;
    },
    [loadSpaceData, usingDemo],
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
          tone: result.processing_enqueued ? "success" : "warning",
          message: result.processing_enqueued
            ? "资料已上传，正在处理并建立向量索引。"
            : "资料已保存，但处理队列暂不可用，请点击重试。",
        });
      } catch (error) {
        const failureMessage =
          error instanceof ApiRequestError
            ? error.message
            : "上传失败，请检查网络后重试。";
        failedUploads.current.set(optimistic.id, { file, categoryId });
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
  const handleDocumentSearch = useCallback(
    async (query: string, tagId?: string) => {
      if (!currentSpace) return;
      try {
        const result = query || tagId
          ? await searchDocuments(currentSpace.id, query, tagId)
          : await listDocuments(currentSpace.id);
        setDocuments(result);
        setDocumentsError("");
      } catch (error) {
        if (!isDemoSpace(currentSpace.id)) {
          setDocumentsError(
            error instanceof ApiRequestError ? error.message : "搜索暂时无法完成。",
          );
          return;
        }
        const normalized = query.toLowerCase();
        setDocuments(
          demoDocuments.filter((document) =>
            !normalized || document.original_filename.toLowerCase().includes(normalized),
          ),
        );
      }
    },
    [currentSpace, isDemoSpace],
  );
  const handleSetDocumentTags = useCallback(
    async (document: KnowledgeDocument, tagIds: string[]) => {
      try {
        await setDocumentTags(document.space_id, document.id, tagIds);
        setToast({ tone: "success", message: "文档标签已更新。" });
      } catch (error) {
        if (!isDemoSpace(document.space_id)) {
          setToast({
            tone: "error",
            message: error instanceof ApiRequestError ? error.message : "标签更新失败。",
          });
          return;
        }
        setToast({ tone: "info", message: "演示标签已更新；连接 API 后会保存。" });
      }
    },
    [isDemoSpace],
  );
  const handleLoadDocumentTags = useCallback(
    async (document: KnowledgeDocument) => {
      try {
        const items = await listDocumentTags(document.id);
        return items.map((tag) => tag.id);
      } catch (error) {
        if (!isDemoSpace(document.space_id)) {
          setToast({
            tone: "warning",
            message: error instanceof ApiRequestError ? error.message : "已有标签暂时无法读取。",
          });
        }
        return [];
      }
    },
    [isDemoSpace],
  );
  const handleAvailability = useCallback(
    async (document: KnowledgeDocument, enabled: boolean) => {
      try {
        const updated = await updateDocumentAvailability(document.id, { is_enabled: enabled });
        setDocuments((items) => items.map((item) => item.id === document.id ? updated : item));
        setToast({ tone: "success", message: enabled ? "文档已重新启用。" : "文档已停用，不会进入新检索。" });
      } catch (error) {
        if (!isDemoSpace(document.space_id)) {
          setToast({ tone: "error", message: error instanceof ApiRequestError ? error.message : "文档状态更新失败。" });
          return;
        }
        setDocuments((items) => items.map((item) => item.id === document.id ? { ...item, is_enabled: enabled } : item));
        setToast({ tone: "info", message: "演示文档状态已更新。" });
      }
    },
    [isDemoSpace],
  );
  const handleDelete = useCallback(async (document: KnowledgeDocument) => {
    if (failedUploads.current.has(document.id)) {
      failedUploads.current.delete(document.id);
      setDocuments(items => items.filter(item => item.id !== document.id));
      return;
    }
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
    const local = failedUploads.current.get(document.id);
    if (local) {
      failedUploads.current.delete(document.id);
      setDocuments(items => items.filter(item => item.id !== document.id));
      await handleUpload(local.file, local.categoryId, () => undefined);
      return;
    }
    try {
      const updated = await retryDocument(document.id);
      setDocuments((items) =>
        items.map((item) => (item.id === document.id ? updated : item)),
      );
      if (updated.status === "FAILED") {
        setToast({ tone: "error", message: updated.failure_message || "处理队列暂不可用，请稍后重试。" });
        return;
      }
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
  }, [isDemoSpace, trackDocumentProcessing, handleUpload]);
  const handleToggleCategory = useCallback(async (category: Category) => {
    const next = !category.is_open;
    try {
      await updateCategory(category.id, { is_open: next });
    } catch (error) {
      if (!isDemoSpace(category.space_id)) {
        setToast({ tone: "error", message: error instanceof ApiRequestError ? error.message : "分类状态更新失败，请重试。" });
        return;
      }
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
  }, [isDemoSpace]);
  const handleCreateCategory = useCallback(
    async (name: string) => {
      if (!currentSpace) return false;
      try {
        const created = await createCategory(currentSpace.id, {
          name,
          is_open: false,
          sort_order: categories.length + 1,
        });
        setCategories((items) => [...items, created]);
      } catch (error) {
        if (!isDemoSpace(currentSpace.id)) {
          setToast({ tone: "error", message: error instanceof ApiRequestError ? error.message : "分类创建失败，请重试。" });
          return false;
        }
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
      return true;
    },
    [categories.length, currentSpace, isDemoSpace],
  );
  const handleCreateTag = useCallback(async (name: string) => {
    if (!currentSpace) return;
    try {
      const tag = await createTag(currentSpace.id, { name });
      setTags((items) => [...items, tag]);
      setToast({ tone: "success", message: `标签“${name}”已创建。` });
    } catch (error) {
      if (!isDemoSpace(currentSpace.id)) {
        setToast({ tone: "error", message: error instanceof ApiRequestError ? error.message : "标签创建失败。" });
        return;
      }
      const tag: KnowledgeTag = {
        id: localId("tag"),
        space_id: currentSpace.id,
        name,
        color: null,
        created_at: now(),
        updated_at: now(),
      };
      setTags((items) => [...items, tag]);
      setToast({ tone: "info", message: "演示标签已创建。" });
    }
  }, [currentSpace, isDemoSpace]);
  const handleDeleteTag = useCallback(async (tag: KnowledgeTag) => {
    try {
      await deleteTag(tag.id);
    } catch (error) {
      if (!isDemoSpace(tag.space_id)) {
        setToast({ tone: "error", message: error instanceof ApiRequestError ? error.message : "标签删除失败。" });
        return;
      }
    }
    setTags((items) => items.filter((item) => item.id !== tag.id));
    setToast({ tone: "success", message: `标签“${tag.name}”已删除。` });
  }, [isDemoSpace]);
  const handleShare = useCallback(async (options?: { password?: string; visitor_question_limit?: number | null; allowed_origins?: string[] }) => {
    if (!currentSpace) return null;
    const ids = categories
      .filter((category) => category.is_open)
      .map((category) => category.id);
    try {
      const created = await createShareLink(currentSpace.id, ids, options);
      setShareLinks((items) => [created.link, ...items]);
      setToast({
        tone: "success",
        message: "分享链接已生成，请妥善保存 token。",
      });
      return created;
    } catch (error) {
      if (!isDemoSpace(currentSpace.id)) {
        setToast({ tone: "error", message: error instanceof ApiRequestError ? error.message : "分享链接生成失败，请重试。" });
        return null;
      }
      const created: CreatedShareLink = {
        link: {
          id: localId("link"),
          space_id: currentSpace.id,
          category_ids: ids,
          status: "ACTIVE",
          created_at: now(),
          revoked_at: null,
          expires_at: null,
          visitor_question_limit: options?.visitor_question_limit ?? null,
          allowed_origins: options?.allowed_origins ?? [],
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
  }, [categories, currentSpace, isDemoSpace]);
  const handleRevoke = useCallback(async (link: ShareLink) => {
    try {
      await revokeShareLink(link.id);
    } catch (error) {
      if (!isDemoSpace(link.space_id)) {
        setToast({ tone: "error", message: error instanceof ApiRequestError ? error.message : "分享链接撤销失败，请重试。" });
        return;
      }
    }
    setShareLinks((items) =>
      items.map((item) =>
        item.id === link.id
          ? { ...item, status: "REVOKED", revoked_at: now() }
          : item,
      ),
    );
    setToast({ tone: "success", message: "分享链接已撤销。" });
  }, [isDemoSpace]);
  const handleVisibilityChange = useCallback(
    async (visibility: SpaceVisibility) => {
      if (!currentSpace || currentSpace.visibility === visibility) return;
      try {
        const updated = await updateSpace(currentSpace.id, { visibility });
        setCurrentSpace(updated);
        setSpaces((items) =>
          items.map((item) => (item.id === updated.id ? updated : item)),
        );
      } catch (error) {
        if (!isDemoSpace(currentSpace.id)) {
          setToast({ tone: "error", message: error instanceof ApiRequestError ? error.message : "空间可见性更新失败，请重试。" });
          return;
        }
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
    [currentSpace, isDemoSpace],
  );
  const handlePlanChange = useCallback(
    async (plan: SpacePlan) => {
      if (!currentSpace || currentSpace.plan === plan) return;
      try {
        const updated = await updateSpace(currentSpace.id, { plan });
        setCurrentSpace(updated);
        setSpaces((items) => items.map((item) => item.id === updated.id ? updated : item));
        await loadUsage(updated);
        setToast({ tone: "success", message: "套餐权益已更新。" });
      } catch (error) {
        if (!isDemoSpace(currentSpace.id)) {
          setToast({ tone: "error", message: error instanceof ApiRequestError ? error.message : "套餐更新失败。" });
          return;
        }
        const updated = { ...currentSpace, plan };
        setCurrentSpace(updated);
        setSpaces((items) => items.map((item) => item.id === updated.id ? updated : item));
        setUsage((value) => value ? { ...value, plan, limits: value.limits } : value);
        setToast({ tone: "info", message: "演示套餐已切换；连接 API 后会按真实额度校验。" });
      }
    },
    [currentSpace, isDemoSpace, loadUsage],
  );
  const handleModerateQuestion = useCallback(async (item: PublicQuestionRecord) => {
    try {
      const updated = await moderatePublicQuestion(item.id, {
        is_hidden: !item.is_hidden,
        moderation_note: item.is_hidden ? null : "由空间管理员隐藏",
      });
      setPublicQuestions((items) => items.map((current) => current.id === updated.id ? updated : current));
      setToast({ tone: "success", message: updated.is_hidden ? "访客问题已隐藏。" : "访客问题已恢复显示。" });
    } catch (error) {
      setToast({ tone: "error", message: error instanceof ApiRequestError ? error.message : "访客问题审核失败。" });
    }
  }, []);
  const handleCreateSource = useCallback(async (input: { kind: SourceKind; locator: string; name?: string }) => {
    if (!currentSpace) return;
    try {
      const created = await createSource(currentSpace.id, input);
      setSources((items) => [created, ...items]);
      setToast({ tone: "success", message: "知识来源已登记。" });
    } catch (error) {
      if (!isDemoSpace(currentSpace.id)) {
        setToast({ tone: "error", message: error instanceof ApiRequestError ? error.message : "来源登记失败。" });
        return;
      }
      const created: KnowledgeSource = {
        id: localId("source"),
        space_id: currentSpace.id,
        kind: input.kind,
        locator: input.locator,
        name: input.name ?? null,
        status: "ACTIVE",
        last_checksum: null,
        last_synced_at: null,
        last_error: null,
        created_at: now(),
        updated_at: now(),
      };
      setSources((items) => [created, ...items]);
      setToast({ tone: "info", message: "演示来源已登记；连接 API 后会执行真实同步。" });
    }
  }, [currentSpace, isDemoSpace]);
  const handleSyncSource = useCallback(async (source: KnowledgeSource) => {
    try {
      setSources((items) => items.map((item) => item.id === source.id ? { ...item, status: "SYNCING" } : item));
      const result = await syncSource(source.id);
      setSources((items) => items.map((item) => item.id === source.id ? result.source : item));
      setToast({ tone: result.failed ? "warning" : "success", message: result.skipped ? "来源内容没有变化，已跳过导入。" : `来源同步完成，导入 ${result.uploaded} 个文档。` });
    } catch (error) {
      if (!isDemoSpace(source.space_id)) {
        setSources((items) => items.map((item) => item.id === source.id ? { ...item, status: "FAILED" } : item));
        setToast({ tone: "error", message: error instanceof ApiRequestError ? error.message : "来源同步失败。" });
        return;
      }
      setSources((items) => items.map((item) => item.id === source.id ? { ...item, status: "READY", last_synced_at: now() } : item));
      setToast({ tone: "info", message: "演示来源已标记为同步完成；连接 API 后会导入文档。" });
    }
  }, [isDemoSpace]);
  const handleToggleSource = useCallback(async (source: KnowledgeSource) => {
    const next: SourceStatus = source.status === "DISABLED" ? "ACTIVE" : "DISABLED";
    try {
      const updated = await setSourceStatus(source.id, next);
      setSources((items) => items.map((item) => item.id === source.id ? updated : item));
      setToast({ tone: "success", message: next === "ACTIVE" ? "知识来源已启用。" : "知识来源已停用。" });
    } catch (error) {
      if (!isDemoSpace(source.space_id)) {
        setToast({ tone: "error", message: error instanceof ApiRequestError ? error.message : "来源状态更新失败。" });
        return;
      }
      setSources((items) => items.map((item) => item.id === source.id ? { ...item, status: next } : item));
      setToast({ tone: "info", message: "演示来源状态已更新。" });
    }
  }, [isDemoSpace]);
  const handleAddMember = useCallback(async (email: string, role: "ADMIN" | "EDITOR" | "MEMBER") => {
    if (!currentSpace) return;
    try {
      const member = await addMember(currentSpace.id, { email, role });
      setMembers((items) => [...items, member]);
      setToast({ tone: "success", message: "成员已添加。" });
    } catch (error) {
      setToast({ tone: "error", message: error instanceof ApiRequestError ? error.message : "成员添加失败。" });
    }
  }, [currentSpace]);
  const handleChangeMemberRole = useCallback(async (member: SpaceMember, role: "ADMIN" | "EDITOR" | "MEMBER") => {
    if (!currentSpace) return;
    try {
      const updated = await changeMemberRole(currentSpace.id, member.user_id, role);
      setMembers((items) => items.map((item) => item.user_id === updated.user_id ? updated : item));
      setToast({ tone: "success", message: "成员权限已更新。" });
    } catch (error) {
      setToast({ tone: "error", message: error instanceof ApiRequestError ? error.message : "成员权限更新失败。" });
    }
  }, [currentSpace]);
  const handleRemoveMember = useCallback(async (member: SpaceMember) => {
    if (!currentSpace) return;
    try {
      await removeMember(currentSpace.id, member.user_id);
      setMembers((items) => items.filter((item) => item.user_id !== member.user_id));
      setToast({ tone: "success", message: "成员已移除。" });
    } catch (error) {
      setToast({ tone: "error", message: error instanceof ApiRequestError ? error.message : "成员移除失败。" });
    }
  }, [currentSpace]);
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
  const selectPage = useCallback(
    (page: WorkspacePage) => {
      if (page !== "spaces" && !currentSpace) {
        setToast({ tone: "info", message: "请先选择一个知识空间。" });
        return;
      }
      setActivePage(page);
      if (page === "feedback") void loadFeedbackData();
      if (page === "settings" && currentSpace)
        {
          void loadShareLinks(currentSpace);
          void loadMembers(currentSpace);
          void loadPublicQuestions(currentSpace);
          void loadPublicAnalytics(currentSpace);
          void loadSources(currentSpace);
        }
    },
    [currentSpace, loadFeedbackData, loadMembers, loadPublicAnalytics, loadPublicQuestions, loadShareLinks, loadSources],
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
            void loadUsage(space);
            void loadSources(space);
          }}
          onCreate={handleCreateSpace}
          onRetry={() => void loadSpaces()}
        />
      );
    return (
      <View className='page-stack space-page'>

        {activePage === "retrieval" && (
          <RetrievalView key={currentSpace.id} spaceId={currentSpace.id} initialQuestion={handoffQuestion} categories={categories} tags={tags}
            onAsk={(question, strategy, metadataFilter) => { setHandoffQuestion(question); setHandoffStrategy(strategy || 'dense'); setHandoffMetadataFilter(metadataFilter || emptyRetrievalMetadataFilter()); setActivePage("qa"); }}
          />
        )}
        {activePage === "documents" && selectedDocumentId && <DocumentDetailView key={selectedDocumentId} spaceId={currentSpace.id} documentId={selectedDocumentId} onBack={() => { setSelectedDocumentId(null); void loadSpaceData(currentSpace, "documents"); }} onAsk={() => setActivePage("qa")} onRetrieve={() => setActivePage("retrieval")} />}
        {activePage === "documents" && !selectedDocumentId && (
          <DocumentsView
            space={currentSpace}
            documents={documents}
            categories={categories}
            tags={tags}
            error={documentsError}
            onUpload={handleUpload}
            onDelete={handleDelete}
            onRetry={handleRetry}
            onSearch={handleDocumentSearch}
            onLoadTags={handleLoadDocumentTags}
            onSetTags={handleSetDocumentTags}
            onAvailability={handleAvailability}
            onOpen={(item) => setSelectedDocumentId(item.id)}
            onRetrieve={() => setActivePage("retrieval")}
          />
        )}
        {activePage === "qa" && handoffStrategy!=='dense' && <View className='inline-banner'><Text>本次问答使用{handoffStrategy==='hybrid_rerank' ? '混合检索 + 模型重排' : '混合检索 · RRF'}</Text><Button className='text-button' disabled={streaming} onClick={()=>setHandoffStrategy('dense')}>恢复向量检索</Button></View>}
        {activePage === "qa" && <>
          <RetrievalMetadataFilterControls value={handoffMetadataFilter} categories={categories} tags={tags} disabled={streaming} onChange={setHandoffMetadataFilter} />
          <QaView
            initialQuestion={handoffQuestion}
            onRetrieve={(question) => { setHandoffQuestion(question); setActivePage("retrieval"); }}
            messages={messages}
            streaming={streaming}
            streamingText={streamingText}
            onSend={handleSend}
            onCancel={handleCancel}
            onFeedback={async (messageId, rating) => {
              if (rating === "UP") await handleFeedback(messageId, rating);
              else setFeedbackDraft({ messageId, rating });
            }}
            feedbackBusy={feedbackBusy}
          />
        </>}
        {activePage === "feedback" && (
          <FeedbackView
            feedback={feedback}
            loading={loadingFeedback}
            onRetry={() => void loadFeedbackData()}
            onRepair={() => { setSelectedDocumentId(null); setActivePage("documents"); }}
            onRetest={(item) => { setEvalDraft({ question: item.question || "", answer: item.corrected_answer || "", feedbackId: item.id,
              caseId: item.eval_case_id || undefined, scope: item.is_guest ? 'PUBLIC' : 'OWNER', categoryIds: item.is_guest ? item.source_category_ids || [] : [] }); setActivePage("eval"); }}
            onReview={async (item, input) => {
              try {
                const updated = await reviewFeedback(item.id, input);
                setFeedback((items) => items.map((current) => current.id === updated.id ? { ...updated, question: updated.question || current.question, original_answer: updated.original_answer || current.original_answer } : current));
                setToast({ tone: "success", message: "反馈审核结果已保存。" });
              } catch (error) {
                setToast({ tone: "error", message: error instanceof ApiRequestError ? error.message : "反馈审核保存失败。" });
              }
            }}
          />
        )}
        {activePage === "eval" && (
          <EvaluationView key={currentSpace.id}
            spaceId={currentSpace.id} categories={categories} tags={tags}
            initialQuestion={evalDraft?.caseId ? undefined : evalDraft?.question} initialAnswer={evalDraft?.caseId ? undefined : evalDraft?.answer}
            initialCaseId={evalDraft?.caseId} initialFeedbackId={evalDraft?.caseId ? undefined : evalDraft?.feedbackId} initialScope={evalDraft?.scope} initialCategoryIds={evalDraft?.categoryIds}
            onSeedConsumed={() => setEvalDraft(null)}
            notify={(message) => setToast({ tone: "success", message })}
          />
        )}
        {activePage === "settings" && (
          <>
            <SettingsView
              space={currentSpace}
              onVisibilityChange={handleVisibilityChange}
              onPlanChange={handlePlanChange}
              sources={sources}
              onCreateSource={handleCreateSource}
              onSyncSource={handleSyncSource}
              onToggleSource={handleToggleSource}
              members={members}
              onAddMember={handleAddMember}
              onChangeMemberRole={handleChangeMemberRole}
              onRemoveMember={handleRemoveMember}
              usage={usage}
            />
            <PublicSettingsView
              space={currentSpace}
              categories={categories}
              tags={tags}
              links={shareLinks}
              publicQuestions={publicQuestions}
              publicAnalytics={publicAnalytics}
              onToggle={handleToggleCategory}
              onCreateCategory={handleCreateCategory}
              onCreateTag={handleCreateTag}
              onDeleteTag={handleDeleteTag}
              onShare={handleShare}
              onRevoke={handleRevoke}
              onModerateQuestion={handleModerateQuestion}
            />
          </>
        )}
      </View>
    );
  }, [
    activePage,
    handoffQuestion,
    handoffStrategy,
    handoffMetadataFilter,
    selectedDocumentId,
    categories,
    tags,
    creating,
    currentSpace,
    documents,
    documentsError,
    feedback,
    feedbackBusy,
    members,
    publicQuestions,
    publicAnalytics,
    sources,
    usage,
    handleCreateCategory,
    handleCreateTag,
    handleDeleteTag,
    handleCreateSpace,
    handleCancel,
    handleDelete,
    handleDocumentSearch,
    handleLoadDocumentTags,
    handleSetDocumentTags,
    handleAvailability,
    handleFeedback,
    handleRetry,
    handleSend,
    handleShare,
    handleToggleCategory,
    handleUpload,
    handleRevoke,
    handleVisibilityChange,
    handlePlanChange,
    handleModerateQuestion,
    handleCreateSource,
    handleSyncSource,
    handleToggleSource,
    handleAddMember,
    handleChangeMemberRole,
    handleRemoveMember,
    loadingFeedback,
    loadingSpaces,
    loadFeedbackData,
    loadSpaceData,
    loadShareLinks,
    loadUsage,
    loadSources,
    loadSpaces,
    messages,
    pageError,
    evalDraft,
    shareLinks,
    spaces,
    streaming,
    streamingText,
  ]);
  if (!loggedIn)
    return (
      <>
        <AuthView
          onEnter={(user) => {
            setAuthUser(user);
            setLoggedIn(true);
          }}
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
        user={authUser ?? undefined}
        onLogout={() => {
          void logout().finally(() => {
            setAuthUser(null);
            setLoggedIn(false);
            setCurrentSpace(null);
            setSpaces([]);
          });
        }}
      >
        {content}
      </AppShell>
      {usingDemo && <View className='demo-ribbon'>演示数据 · API 未连接</View>}
      <AppToast toast={toast} />
      {feedbackDraft && <FeedbackDialog onCancel={() => setFeedbackDraft(null)} onSubmit={async (reason, comment) => {
        await sendFeedback(feedbackDraft.messageId, { rating: feedbackDraft.rating, reason, comment: comment || undefined });
        setFeedbackDraft(null); setToast({ tone: "success", message: "反馈已保存。" });
      }}
      />}
    </>
  );
}
