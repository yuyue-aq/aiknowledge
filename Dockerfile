FROM node:22.14-bookworm-slim AS build

WORKDIR /app

COPY package.json yarn.lock ./
RUN corepack enable \
    && corepack prepare yarn@1.22.22 --activate \
    && yarn install --frozen-lockfile --ignore-scripts

COPY . .

ARG TARO_APP_API_BASE=http://localhost:8000/api/v1
ENV TARO_APP_API_BASE=${TARO_APP_API_BASE}

RUN yarn build:h5

FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
