FROM node:20-alpine AS builder
WORKDIR /app
# Low-RAM VPS: 4096 often triggers OOM-kill under load; 2560 is safer
ENV NODE_OPTIONS=--max-old-space-size=2560
ENV NEXT_TELEMETRY_DISABLED=1
ARG CACHEBUST=1
RUN echo "build cache bust: ${CACHEBUST}"
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
EXPOSE 3000
ENV PORT=3000
CMD ["node", "server.js"]
