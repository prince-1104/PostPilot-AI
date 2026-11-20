# syntax=docker/dockerfile:1

FROM node:24.22.3-alpine AS base

ENV PNPM_HOME="/pnpm" \
    PATH="/pnpm:$PATH" \
    NEXT_TELEMETRY_DISABLED=1

# Corepack installs the exact pnpm version pinned in package.json ("packageManager").
RUN corepack enable

WORKDIR /app


# --- Dependencies: installed strictly from pnpm-lock.yaml --------------------------
FROM base AS deps

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN --mount=type=cache,id=pnpm-store,target=/pnpm/store \
    pnpm install --frozen-lockfile


# --- Build -------------------------------------------------------------------------
FROM base AS builder

# NEXT_PUBLIC_* values are inlined into the client bundle here, at build time.
ARG NEXT_PUBLIC_API_BASE_URL
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}

COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN pnpm build


# --- Runtime: the standalone server only, without node_modules or pnpm -------------
FROM node:24.22.3-alpine AS runtime

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    HOSTNAME=0.0.0.0 \
    PORT=3000

WORKDIR /app

COPY --from=builder --chown=node:node /app/public ./public
COPY --from=builder --chown=node:node /app/.next/standalone ./
COPY --from=builder --chown=node:node /app/.next/static ./.next/static

USER node
EXPOSE 3000

CMD ["node", "server.js"]
