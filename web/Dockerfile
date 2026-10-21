# Образ web (T-401): сборка SPA и nginx со статикой и прокси /api. В рантайме Node нет.
# Контекст сборки — папка web/ (так же собирает CI). Теги образов точные, не latest (50-02).

FROM node:24.22.1-bookworm-slim AS build
# Версия pnpm совпадает с `packageManager` в package.json
RUN npm install --global pnpm@12.14.0
WORKDIR /app
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml .npmrc ./
RUN pnpm install --frozen-lockfile
COPY . .
RUN pnpm build

FROM nginxinc/nginx-unprivileged:1.30.6-alpine3.24 AS runtime
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY nginx/ /etc/nginx/snippets/
COPY --from=build /app/dist /usr/share/nginx/html
# nginx-unprivileged работает от пользователя nginx (не root) и слушает 8080
EXPOSE 8080
HEALTHCHECK --interval=5s --timeout=3s --retries=12 \
  CMD ["wget", "-q", "-O", "/dev/null", "http://127.0.0.1:8080/healthz"]
