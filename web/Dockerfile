# Multi-stage: `build` compiles the app, `prod` serves the static result with
# nginx (the default target, used by docker-compose.yml), `dev` runs the Vite
# dev server with hot reload (used by docker-compose.dev.yml).

FROM node:22-slim AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
# `npm ci` installs exactly what package-lock.json pins (reproducible builds).
RUN npm ci

FROM deps AS dev
COPY . .
EXPOSE 5173
CMD ["npm", "run", "dev"]

FROM deps AS build
COPY . .
# Where the browser should send API calls. Empty (the default) means "same
# origin" - the reverse proxy routes /api/* to the backend, so no host name is
# baked into the bundle and the same image works on localhost, a LAN IP or a
# Tailscale name. It is read at BUILD time (Vite inlines it).
ARG VITE_API_BASE_URL=""
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

# The default (last) stage: what `docker compose build frontend` produces.
FROM nginx:1.27-alpine AS prod
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY security-headers.conf /etc/nginx/security-headers.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
  CMD wget -qO /dev/null http://127.0.0.1/ || exit 1
