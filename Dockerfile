# ── claw-dashboard-portal ──────────────────────────────────────────────────
# 本地服务导航中心  |  端口 8888  |  Python 3.11 + Flask
# ---------------------------------------------------------------------------
FROM python:3.11-slim

WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制源码（data/ 目录由 volume 挂载，不打包进镜像）
COPY app.py       .
COPY index.html   .
COPY admin.html   .
COPY traffic.html .
COPY static/      static/

# 数据目录（config.json、icons、visit_count.json、ip_traffic.db 持久化在此）
VOLUME ["/app/data"]

EXPOSE 8888

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8888/health')" || exit 1

CMD ["python", "app.py"]
