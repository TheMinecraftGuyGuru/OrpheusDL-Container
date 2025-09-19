# syntax=docker/dockerfile:1
FROM alpine:3.20

# Install dependencies (example: curl + bash)
RUN apk add --no-cache curl bash

# Set working dir
WORKDIR /app

# Copy source files (adjust as needed)
COPY . /app

# Default command
CMD ["sh"]
