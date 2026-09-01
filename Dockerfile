# 后端部署镜像
FROM python:3.11-slim

WORKDIR /app

# 安装依赖（含构建时需要的编译工具）
COPY backend/requirements.txt .
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && pip install --no-cache-dir -r requirements.txt \
    && rm -rf /var/lib/apt/lists/*

# 复制后端代码
COPY backend/app ./app

# 环境变量在 docker-compose / 运行时注入
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

# 生产模式：关闭热重载
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
