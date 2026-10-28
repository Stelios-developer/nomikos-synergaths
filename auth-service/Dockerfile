FROM node:22-alpine@sha256:fe4f6d74e20370acb04ad889077d14d0f64a9c8ea6a42bc60cddf1e844699914
WORKDIR /app
COPY package*.json ./
RUN npm ci --omit=dev && npm uninstall --global npm
COPY src ./src
USER node
ENV NODE_ENV=production APP_ENV=production AUTH_HOST=0.0.0.0
EXPOSE 3001
CMD ["node", "--import", "tsx", "src/server.ts"]
