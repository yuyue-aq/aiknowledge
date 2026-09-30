import { Button, Input, Text, View } from "@tarojs/components";
import { Icon, type IconName } from "./Icon";
import type { AuthUser } from "../api/client";

export type WorkspacePage =
  | "spaces"
  | "qa"
  | "documents"
  | "feedback"
  | "eval"
  | "settings";

const navItems: Array<{ key: WorkspacePage; label: string; icon: IconName }> = [
  { key: "spaces", label: "空间", icon: "home" },
  { key: "qa", label: "问答", icon: "chat" },
  { key: "documents", label: "资料", icon: "file" },
  { key: "feedback", label: "反馈", icon: "feedback" },
  { key: "eval", label: "评测", icon: "eval" },
  { key: "settings", label: "设置", icon: "settings" },
];

type AppShellProps = {
  active: WorkspacePage;
  onNavigate: (page: WorkspacePage) => void;
  spaceName?: string;
  children: React.ReactNode;
  onOpenPublic?: () => void;
  user?: AuthUser;
  onLogout?: () => void;
};

export function AppShell({
  active,
  onNavigate,
  spaceName,
  children,
  onOpenPublic,
  user,
  onLogout,
}: AppShellProps) {
  return (
    <View className='app-shell'>
      <View className='sidebar' aria-label='工作台导航'>
        <View className='brand-lockup'>
          <View className='brand-mark'>
            <Text>知</Text>
          </View>
          <View>
            <Text className='brand-name'>知溯</Text>
            <Text className='brand-caption'>可信知识工作台</Text>
          </View>
        </View>
        <View className='sidebar-nav'>
          {navItems.map((item) => (
            <Button
              key={item.key}
              className={`nav-button ${active === item.key ? "is-active" : ""}`}
              onClick={() => onNavigate(item.key)}
              aria-current={active === item.key ? "page" : undefined}
            >
              <Icon name={item.icon} />
              <Text>{item.label}</Text>
            </Button>
          ))}
        </View>
        <View className='sidebar-bottom'>
          {onOpenPublic && (
            <Button className='sidebar-public-button' onClick={onOpenPublic}>
              <Icon name='globe' />
              <Text>访客预览</Text>
            </Button>
          )}
          <Text className='sidebar-version'>模型工作台 · MVP</Text>
        </View>
      </View>
      <View className='workspace'>
        <View className='topbar'>
          <View className='topbar-search'>
            <Icon name='search' />
            <Input
              className='topbar-search-input'
              aria-label='搜索空间、文档或问题'
              placeholder='搜索空间、文档或问题…'
            />
          </View>
          <View className='topbar-actions'>
            <Button
              className='icon-button notification-button'
              disabled
              aria-label='查看通知（MVP 未接入）'
            >
              <Icon name='bell' />
            </Button>
            <View className='avatar' aria-hidden='true'>
              {(user?.display_name || "知").slice(0, 1)}
            </View>
            <Text className='user-name'>{user?.display_name || "知识管理员"}</Text>
            <Text className='user-caret'>⌄</Text>
            {onLogout && (
              <Button className='text-button shell-logout' onClick={onLogout} aria-label='退出登录'>
                退出
              </Button>
            )}
          </View>
        </View>
        <View className='workspace-content'>
          {spaceName && (
            <View className='space-context'>
              <Text className='space-context-label'>当前空间</Text>
              <Text className='space-context-name'>{spaceName}</Text>
            </View>
          )}
          {children}
        </View>
      </View>
      <View className='mobile-tabbar' aria-label='移动端主导航'>
        {navItems.slice(0, 5).map((item) => (
          <Button
            key={item.key}
            className={`mobile-tab ${active === item.key ? "is-active" : ""}`}
            onClick={() => onNavigate(item.key)}
            aria-current={active === item.key ? "page" : undefined}
          >
            <Icon name={item.icon} />
            <Text>{item.label}</Text>
          </Button>
        ))}
      </View>
    </View>
  );
}
