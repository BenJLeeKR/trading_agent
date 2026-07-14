# =============================================================================
# Admin UI — 별도 컨테이너로 분리된 프론트엔드
# =============================================================================
# 이전에는 백엔드(api 서비스)가 dist/를 /admin 경로에 static mount 했지만,
# 프론트/백엔드를 별도 컨테이너로 분리하면서 이 이미지가 root("/")에서
# 직접 서비스한다. API 호출은 기본적으로 상대경로("")를 쓰고, 이 이미지에
# 포함된 nginx(nginx.frontend.conf)가 알려진 API 경로를 백엔드로 내부
# 프록시한다(src/api/client.ts의 API_BASE_URL 참고) — 이렇게 해야 프론트가
# zrok 같은 단일 HTTPS 터널로만 노출되는 환경에서도 CORS/mixed-content 없이
# 항상 동작한다. 백엔드 절대 URL이 정말 필요한 특수 배포라면
# VITE_API_BASE_URL 빌드 args로 override 가능.
# =============================================================================

# ── Build stage ──────────────────────────────────────────────────────────
FROM node:20-slim AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# 기본값은 빈 문자열(상대경로) — 이 이미지의 nginx가 내부 프록시하므로
# 필요 없지만, 특수 배포에서 override할 수 있게 build arg는 남겨둔다.
ARG VITE_API_BASE_URL=""
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}

RUN npm run build

# ── Serve stage ──────────────────────────────────────────────────────────
FROM nginx:1.27-alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.frontend.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
