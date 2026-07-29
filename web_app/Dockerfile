FROM node:22.18.0-alpine3.22

WORKDIR /web_app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev
COPY . .
RUN npm run build

EXPOSE 3000
CMD ["npm", "run", "start"]
