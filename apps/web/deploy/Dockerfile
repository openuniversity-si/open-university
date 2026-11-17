# The Lambda image of Open University's site (D-319): the Next.js standalone output of apps/web, served through the
# AWS Lambda Web Adapter. build-image.sh assembles the context (out/standalone, out/static, out/public); nothing secret
# is in the image: every secret reaches the function as an environment variable. Both bases are pinned by digest.
FROM public.ecr.aws/awsguru/aws-lambda-adapter:1.0.1@sha256:1e5ab4d9242167500ed8a7bed8a79b448228aaa51cf382fb51fe4bf8a5f9a811 AS adapter

FROM public.ecr.aws/docker/library/node:22-slim@sha256:e9f565d32859f0cbfb52125eafe8be39390f24dac302dc3cdf566e8ba3ab21ee
COPY --from=adapter /lambda-adapter /opt/extensions/lambda-adapter
WORKDIR /app
ENV NODE_ENV=production PORT=3000 HOSTNAME=0.0.0.0 NEXT_TELEMETRY_DISABLED=1
COPY --chown=node:node out/standalone/ ./
COPY --chown=node:node out/static ./.next/static
COPY --chown=node:node out/public ./public
# The function's file system is read-only but /tmp: Next's caches live there.
RUN rm -rf /app/.next/cache /app/.next/server/route-cache \
 && ln -s /tmp/next-cache /app/.next/cache \
 && ln -s /tmp/route-cache /app/.next/server/route-cache
ENV AWS_LWA_PORT=3000 AWS_LWA_READINESS_CHECK_PATH=/api/health AWS_LWA_INVOKE_MODE=response_stream
EXPOSE 3000
CMD ["sh", "-c", "mkdir -p /tmp/next-cache /tmp/route-cache && exec node server.js"]
