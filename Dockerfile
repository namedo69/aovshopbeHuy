FROM node:24-alpine AS builder

WORKDIR /app

# Copy package files from backend directory
COPY backend/package*.json ./
RUN npm install

# Copy source code and config
COPY backend/ ./
RUN npm run build

# Production image
FROM node:24-alpine AS runner
RUN apk add --no-cache python3 py3-cryptography lz4-libs

WORKDIR /app

ENV NODE_ENV=production
ENV PORT=3000

# Copy node_modules and built files
COPY --from=builder /app/package*.json ./
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/dist ./dist
COPY backend/scanner ./scanner

EXPOSE 3000

CMD ["node", "dist/server.js"]
