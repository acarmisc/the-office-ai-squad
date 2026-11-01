# syntax=docker/dockerfile:1
ARG BASE_TAG=20.11-alpine
ARG REGISTRY=docker.io/library
FROM --platform=$BUILDPLATFORM ${REGISTRY}/node:${BASE_TAG} AS build
RUN npm ci

FROM build AS test
RUN npm test

FROM nginx:1.27.2-alpine@sha256:3f1e6a2b9c4d5e8f0a1b2c3d4e5f60718293a4b5c6d7e8f901a2b3c4d5e6f708 AS runtime
COPY --from=build /app/dist /usr/share/nginx/html

FROM alpine:latest AS tools
FROM scratch
