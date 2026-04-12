FROM ghcr.io/puppeteer/puppeteer:latest

WORKDIR /bridge

# Copy package files
COPY package.json package-lock.json* ./
RUN npm ci --omit=dev

# Copy source
COPY src ./src

EXPOSE 3001

CMD ["node", "src/server.mjs"]
