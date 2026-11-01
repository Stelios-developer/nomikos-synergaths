FROM node:26-alpine@sha256:c6ad9e9c1d80f6eb607c26b4b0a132ff7a2344fad1c78ea3baa2a7d4c8de6d94
WORKDIR /app
COPY package*.json ./
RUN npm ci --omit=dev && npm uninstall --global npm
COPY src ./src
USER node
ENV NODE_ENV=production APP_ENV=production AUTH_HOST=0.0.0.0
EXPOSE 3001
CMD ["node", "--import", "tsx", "src/server.ts"]
