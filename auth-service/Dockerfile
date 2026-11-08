FROM node:25-alpine@sha256:bdf2cca6fe3dabd014ea60163eca3f0f7015fbd5c7ee1b0e9ccb4ced6eb02ef4
WORKDIR /app
COPY package*.json ./
RUN npm ci --omit=dev && npm uninstall --global npm
COPY src ./src
USER node
ENV NODE_ENV=production APP_ENV=production AUTH_HOST=0.0.0.0
EXPOSE 3001
CMD ["node", "--import", "tsx", "src/server.ts"]
