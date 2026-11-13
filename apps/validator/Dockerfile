FROM public.ecr.aws/docker/library/node:24-bookworm-slim@sha256:01d566e8d94d8c619591d78652babfccd3c6992a3dffa9ed5ab39e11cf6c70e9
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/browsers
WORKDIR /app
COPY package*.json ./
COPY apps/web/package.json apps/web/package.json
COPY apps/validator/package.json apps/validator/package.json
RUN npm ci
RUN npx playwright install --with-deps chromium && chmod -R a+rX /opt/browsers
COPY shared shared
COPY apps/validator apps/validator
RUN npm run build -w @atoms/validator
USER node
EXPOSE 9000
CMD ["node","apps/validator/dist/server.js"]
