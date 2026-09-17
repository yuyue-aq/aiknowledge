import { Button, Input, Text, Textarea, View } from "@tarojs/components";
import Taro, { useLoad, useRouter } from "@tarojs/taro";
import { useEffect, useRef, useState } from "react";
import {
  ApiRequestError,
  createPublicConversation,
  createPublicSession,
  getPublicSpace,
  streamPublicAnswer,
  type AnswerStatus,
  type PublicSpace,
} from "../../api/client";
import { Icon } from "../../components/Icon";
import "./public.scss";

type PublicMessage = {
  id: string;
  role: "USER" | "ASSISTANT";
  content: string;
  status?: AnswerStatus;
  createdAt: string;
};
const localId = (prefix: string) =>
  `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
const now = () => new Date().toISOString();
const valueOf = (event: any) =>
  event.detail?.value ?? event.currentTarget?.value ?? "";

const demoSpace: PublicSpace = {
  name: "项目与经历",
  description: "围绕已开放内容提问，回答只基于当前公开范围。",
  categories: [
    { name: "项目经验", description: "包含项目方案、技术实现与成果。" },
    { name: "产品介绍", description: "包含产品功能、使用说明与常见问题。" },
  ],
};

export default function Public() {
  const router = useRouter();
  const [token, setToken] = useState(router.params.token ?? "");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [space, setSpace] = useState<PublicSpace | null>(null);
  const [state, setState] = useState<"entry" | "loading" | "ready" | "invalid">(
    "entry",
  );
  const [error, setError] = useState("");
  const [usingDemo, setUsingDemo] = useState(false);
  const [questionError, setQuestionError] = useState("");
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<PublicMessage[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [streamingText, setStreamingText] = useState("");
  const streamAbort = useRef<AbortController | null>(null);

  useLoad(() => {
    if (router.params.token) void openSession(router.params.token);
    else void restoreSession();
  });
  useEffect(
    () => () => {
      streamAbort.current?.abort();
      streamAbort.current = null;
    },
    [],
  );
  useEffect(() => {
    const title =
      state === "invalid"
        ? "访问边界 · 知溯"
        : space
          ? `${space.name} · 公开问答`
          : "公开访问 · 知溯";
    if (typeof document !== "undefined") document.title = title;
    void Taro.setNavigationBarTitle({ title });
  }, [space, state]);

  const restoreSession = async () => {
    try {
      const result = await getPublicSpace();
      setSpace(result);
      setUsingDemo(false);
      setState("ready");
    } catch {
      setState("entry");
    }
  };
  const openSession = async (nextToken: string, nextPassword = password) => {
    if (!nextToken.trim()) {
      setError("请输入有效的分享 token。");
      return;
    }
    setState("loading");
    setError("");
    setQuestionError("");
    setUsingDemo(false);
    try {
      const result = await createPublicSession(nextToken.trim(), nextPassword.trim() || undefined);
      setSpace(result);
      setState("ready");
      setToken(nextToken.trim());
    } catch (requestError) {
      if (nextToken.trim() === "demo-share-token") {
        setSpace(demoSpace);
        setUsingDemo(true);
        setState("ready");
        setToken(nextToken.trim());
        return;
      }
      setState("invalid");
      setError(
        requestError instanceof ApiRequestError
          ? requestError.message
          : "分享链接无效或已失效。",
      );
    }
  };
  const ensureConversation = async () => {
    if (conversationId) return conversationId;
    try {
      const result = await createPublicConversation(
        `${space?.name ?? "公开空间"}访客问答`,
      );
      setConversationId(result.id);
      return result.id;
    } catch (requestError) {
      if (!usingDemo) throw requestError;
      const id = "demo-public-conversation";
      setConversationId(id);
      return id;
    }
  };
  const send = async (question: string) => {
    const cleaned = question.trim();
    if (streaming) {
      streamAbort.current?.abort();
      setStreaming(false);
      setStreamingText("");
      return;
    }
    if (!cleaned) return;
    setInput("");
    setMessages((items) => [
      ...items,
      { id: localId("user"), role: "USER", content: cleaned, createdAt: now() },
    ]);
    setStreaming(true);
    setStreamingText("");
    setQuestionError("");
    const controller = typeof AbortController === "undefined" ? null : new AbortController();
    streamAbort.current = controller;
    try {
      const id = await ensureConversation();
      if (id === "demo-public-conversation")
        throw new ApiRequestError("演示模式", 0);
      const result = await streamPublicAnswer(id, cleaned, setStreamingText, controller?.signal);
      setMessages((items) => [
        ...items,
        {
          id: result.message_id,
          role: "ASSISTANT",
          content: result.answer,
          status: result.status,
          createdAt: now(),
        },
      ]);
    } catch (requestError) {
      if (controller?.signal.aborted) return;
      if (usingDemo) {
        setMessages((items) => [
          ...items,
          {
            id: localId("assistant"),
            role: "ASSISTANT",
            content:
              "基于当前已开放的项目经验与产品介绍，我可以说明公开范围内的工作内容和产品能力；如果问题超出这些分类，我会明确提示无法回答。",
            status: "ANSWERED",
            createdAt: now(),
          },
        ]);
      } else {
        const message =
          requestError instanceof ApiRequestError
            ? requestError.message
            : "公开回答暂时无法生成，请稍后重试。";
        if (
          requestError instanceof ApiRequestError &&
          (requestError.status === 401 || requestError.status === 403)
        ) {
          setConversationId(null);
          setSpace(null);
          setState("invalid");
          setError("公开访问已失效，请重新输入有效的分享 token。");
        }
        setQuestionError(message);
        setMessages((items) => [
          ...items,
          {
            id: localId("assistant"),
            role: "ASSISTANT",
            content: message,
            status: "FAILED",
            createdAt: now(),
          },
        ]);
      }
    } finally {
      if (streamAbort.current === controller) streamAbort.current = null;
      setStreaming(false);
      setStreamingText("");
    }
  };

  if (state === "entry")
    return (
      <View className='public-page'>
        <PublicHeader onBack={() => void Taro.navigateBack()} />
        <View className='public-entry-card'>
          <View className='public-entry-icon'>
            <Icon name='link' />
          </View>
          <Text className='public-title'>进入公开问答</Text>
          <Text className='public-subtitle'>
            输入空间所有者分享的链接 token，开始围绕已开放内容提问。
          </Text>
          <View className='public-token-field'>
            <Text className='field-label'>分享 token</Text>
            <Input
              value={token}
              onInput={(event) => {
                setToken(valueOf(event));
                setError("");
              }}
              placeholder='粘贴分享 token'
              aria-label='分享 token'
              onConfirm={() => void openSession(token)}
            />
          </View>
          <View className='public-token-field'>
            <Text className='field-label'>访问密码（如有）</Text>
            <View className='secret-input public-secret-input'>
              <Input
                value={password}
                password={!showPassword}
                onInput={(event) => {
                  setPassword(valueOf(event));
                  setError("");
                }}
                placeholder='如链接设置了密码，请输入'
                aria-label='访问密码'
                onConfirm={() => void openSession(token)}
              />
              <Button
                className='input-action'
                size='mini'
                onClick={() => setShowPassword((current) => !current)}
                aria-label={showPassword ? '隐藏访问密码' : '显示访问密码'}
              >
                {showPassword ? '隐藏' : '显示'}
              </Button>
            </View>
          </View>
          {error && <Text className='public-error'>{error}</Text>}
          <Button
            className='public-primary'
            onClick={() => void openSession(token)}
            disabled={false}
          >
            进入公开空间
          </Button>
          <Text className='public-entry-note'>
            公开访客不会看到文档列表、原文片段或下载入口。
          </Text>
        </View>
        <PublicFooter />
      </View>
    );
  if (state === "invalid")
    return (
      <View className='public-page'>
        <PublicHeader onBack={() => void Taro.navigateBack()} />
        <View className='boundary-card boundary-invalid'>
          <View className='boundary-icon'>
            <Icon name='link' />
          </View>
          <Text className='boundary-title'>链接已失效</Text>
          <Text className='boundary-copy'>
            {error || "该分享链接已被撤销，请联系空间所有者获取新链接。"}
          </Text>
          <Button
            className='public-outline'
            onClick={() => {
              setState("entry");
              setError("");
            }}
          >
            重新输入 token
          </Button>
        </View>
        <PublicFooter />
      </View>
    );
  if (!space)
    return (
      <View className='public-page'>
        <PublicHeader onBack={() => void Taro.navigateBack()} />
        <View className='public-loading'>
          <View className='loading-dot' />
          <Text>正在打开公开空间…</Text>
        </View>
      </View>
    );
  return (
    <View className='public-page'>
      <PublicHeader
        onBack={() => void Taro.navigateBack()}
        spaceName={space.name}
      />
      <View className='public-content'>
        <View className='public-scope-banner'>
          <Icon name='globe' />
          <Text>
            仅基于 {space.categories.length} 个已开放分类，不展示原文档
          </Text>
        </View>
        <View className='public-intro'>
          <Text className='public-title'>了解{space.name}</Text>
          <Text className='public-subtitle'>
            {space.description || "围绕已开放内容提问"}
          </Text>
          <View className='public-category-chips'>
            {space.categories.map((category) => (
              <View className='public-category-chip' key={category.name}>
                <Icon name='file' />
                <Text>{category.name}</Text>
              </View>
            ))}
          </View>
        </View>
        <View className='public-messages' aria-live='polite'>
          {messages.length === 0 && (
            <View className='public-suggestions'>
              <Text className='suggestions-title'>你可以这样问</Text>
              <View className='suggestion-grid'>
                <Button
                  className='suggestion-card'
                  onClick={() => void send("你负责过哪些工作？")}
                >
                  你负责过哪些工作？
                  <Icon name='arrow' />
                </Button>
                <Button
                  className='suggestion-card'
                  onClick={() => void send("项目解决了什么问题？")}
                >
                  项目解决了什么问题？
                  <Icon name='arrow' />
                </Button>
                <Button
                  className='suggestion-card'
                  onClick={() => void send("产品适合哪些用户？")}
                >
                  产品适合哪些用户？
                  <Icon name='arrow' />
                </Button>
              </View>
            </View>
          )}
          {messages.map((message) => (
            <PublicBubble key={message.id} message={message} />
          ))}
          {streaming && (
            <View className='public-bubble-row'>
              <View className='public-bot-avatar'>知</View>
              <View className='public-answer'>
                <Text className='public-answer-label'>
                  <Icon name='globe' />
                  基于公开资料回答
                </Text>
                <Text>{streamingText || "正在检索公开分类…"}</Text>
              </View>
            </View>
          )}
        </View>
        {questionError && (
          <View className='public-question-error' role='alert'>
            <Icon name='warning' />
            <Text>{questionError}</Text>
          </View>
        )}
        <View className='public-composer'>
          <Icon name='search' />
          <Textarea
            className='resize-none'
            value={input}
            onInput={(event) => setInput(valueOf(event))}
            onConfirm={() => void send(input)}
            disabled={streaming}
            placeholder='输入你想了解的问题'
            aria-label='输入你想了解的问题'
          />
          <Button
            className={streaming ? 'public-send public-stop' : 'public-send'}
            onClick={() => void send(input)}
            disabled={!streaming && !input.trim()}
            aria-busy={streaming}
            aria-label={streaming ? '停止生成' : '发送问题'}
          >
            {streaming ? '停止' : <Icon name='send' />}
          </Button>
        </View>
      </View>
      <PublicFooter />
    </View>
  );
}

function PublicHeader({
  onBack,
  spaceName,
}: {
  onBack: () => void;
  spaceName?: string;
}) {
  return (
    <View className='public-header'>
      <Button className='public-brand' onClick={onBack}>
        <View className='brand-mark'>
          <Text>知</Text>
        </View>
        <Text>知溯</Text>
      </Button>
      {spaceName ? (
        <Text className='public-header-title'>{spaceName}</Text>
      ) : (
        <View className='public-header-links'>
          <Text className='header-link is-active'>公开问答</Text>
          <Text className='header-link'>关于</Text>
        </View>
      )}
      <Button className='public-menu' onClick={onBack} aria-label='返回'>
        <Icon name='menu' />
      </Button>
    </View>
  );
}
function PublicBubble({ message }: { message: PublicMessage }) {
  if (message.role === "USER")
    return (
      <View className='public-bubble-row public-user-row'>
        <View className='public-user-bubble'>
          <Text>{message.content}</Text>
          <Text className='public-time'>{formatTime(message.createdAt)}</Text>
        </View>
        <View className='public-user-avatar'>
          <Icon name='team' />
        </View>
      </View>
    );
  return (
    <View className='public-bubble-row'>
      <View className='public-bot-avatar'>知</View>
      <View
        className={`public-answer public-answer-${(message.status ?? "ANSWERED").toLowerCase()}`}
      >
        {message.status === "OUT_OF_SCOPE" && (
          <View className='boundary-inline'>
            <Icon name='warning' />
            <Text>超出公开范围</Text>
          </View>
        )}
        {message.status === "FAILED" && (
          <View className='boundary-inline boundary-error'>
            <Icon name='warning' />
            <Text>回答暂时不可用</Text>
          </View>
        )}
        <Text className='public-answer-label'>
          <Icon name='globe' />
          {message.status === "FAILED" ? "需要重试" : "基于公开资料回答"}
        </Text>
        <Text>{message.content}</Text>
        <Text className='public-time'>{formatTime(message.createdAt)}</Text>
      </View>
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
function PublicFooter() {
  return (
    <View className='public-footer'>
      <Icon name='lock' />
      <Text>知溯 · 让每一个答案都有据可循</Text>
    </View>
  );
}
