# syntax=docker/dockerfile:1
FROM alpine:3.20

# Install dependencies (example: curl + bash)
RUN apk add --no-cache curl bash git

# Set working dir
WORKDIR /app

# Copy source files (adjust as needed)
COPY . /app

# Fetch git submodules so their contents are available during the build
RUN git config --global --add safe.directory /app \
    && git -C /app submodule update --init --recursive

# Copy OrpheusDL core and modules into expected container locations
RUN mkdir -p /orpheusdl/modules/qobuz \
    && cp -a /app/external/orpheusdl/. /orpheusdl/ \
    && cp -a /app/external/orpheusdl-qobuz/. /orpheusdl/modules/qobuz/

# Default command
CMD ["sh"]
