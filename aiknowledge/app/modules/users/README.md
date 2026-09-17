# 用户与授权模块（保留目录）

用户模块已接入 MVP 的邮箱注册、登录、刷新令牌、退出和 owner scope。实现位于 `app/services/auth.py`、`app/services/memberships.py` 与对应 API/Repository；新增身份能力必须继续通过服务层权限矩阵，不能在路由中绕过空间角色校验。
