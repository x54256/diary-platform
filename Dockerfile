# syntax=docker/dockerfile:1.4

FROM --platform=$BUILDPLATFORM node:20-bookworm-slim AS frontend-build

WORKDIR /build/frontend

COPY frontend/package*.json ./
RUN --mount=type=cache,target=/root/.npm npm ci

COPY frontend/ ./
RUN npm run build

FROM node:20-bookworm-slim AS backend-wheels

ENV PATH="/opt/venv/bin:${PATH}"

WORKDIR /build/backend

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv gcc \
    && python3 -m venv /opt/venv \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.lock.txt ./requirements.lock.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip wheel --wheel-dir /wheels -r requirements.lock.txt

FROM node:20-bookworm-slim AS runtime

ENV PYTHONUNBUFFERED=1
ENV PATH="/opt/venv/bin:${PATH}"
ENV HOST=0.0.0.0
ENV PORT=3000
ENV NITRO_HOST=0.0.0.0
ENV NITRO_PORT=3000
ENV NUXT_APP_BASE_URL=/mind/
ENV NUXT_PUBLIC_API_BASE=/diary/api

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv nginx \
    && python3 -m venv /opt/venv \
    && rm -f /etc/nginx/sites-enabled/default \
    && mkdir -p /run/nginx \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.lock.txt /app/backend/requirements.lock.txt
COPY --from=backend-wheels /wheels /wheels
RUN pip install --no-index --find-links=/wheels -r /app/backend/requirements.lock.txt \
    && rm -rf /wheels

COPY backend/ /app/backend/
COPY --from=frontend-build /build/frontend/.output/ /app/frontend/.output/
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY docker/start.sh /app/start.sh

EXPOSE 80

CMD ["sh", "/app/start.sh"]
