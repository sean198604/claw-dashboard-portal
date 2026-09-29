# 8888 门户 (Dashboard Portal)

EGO International 内部工具导航门户，卡片式布局集中管理所有内部系统的入口。

## 技术栈

- **后端**: Python Flask
- **前端**: 原生 HTML/CSS/JS
- **部署**: Docker + Nginx
- **端口**: 8888

## 功能

- 🗂️ 分组建卡导航（AI应用、小工具、企业知识库、企业文化）
- 🔗 支持多种卡片类型：自定义链接、汇率看板、FastGPT 问答嵌入
- ⚙️ 管理后台：实时增删改卡片，配置持久化到 JSON
- 📊 访问统计追踪
- 📱 响应式布局

## 目录结构

```
├── app.py              # Flask 主应用
├── admin.html          # 管理后台页面
├── index.html          # 门户首页
├── container_index.html # 容器化索引
├── Dockerfile
├── docker-compose.yml
├── nginx.conf
├── requirements.txt
├── static/             # 静态资源（LOGO、favicon）
└── data/               # 运行时数据（Docker volume）
```

## 快速启动

```bash
docker-compose up -d
```

访问 `http://localhost:8888`；局域网部署请替换为实际服务器地址。

## 管理后台

访问 `/admin` 路径，默认密码通过环境变量 `ADMIN_PASSWORD` 设置。
