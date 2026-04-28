# Stage 1: Install dependencies
FROM node:20-alpine AS builder
WORKDIR /build

COPY package.json package-lock.json* ./
RUN npm ci --omit=dev

# Stage 2: Production image
FROM node:20-alpine AS runtime
WORKDIR /app

# Non-root user for container security
RUN addgroup -S contoso && adduser -S contoso -G contoso

COPY --from=builder /build/node_modules ./node_modules
COPY src ./src
COPY package.json ./

RUN chown -R contoso:contoso /app
USER contoso

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD node -e "require('http').get('http://localhost:3000/health', r => process.exit(r.statusCode === 200 ? 0 : 1))"

ENV NODE_ENV=production
CMD ["node", "src/index.js"]
