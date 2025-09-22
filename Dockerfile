# syntax=docker/dockerfile:1
FROM alpine:3.20

# Install system dependencies
RUN apk add --no-cache \
        bash \
        curl \
        ffmpeg \
        gcc \
        git \
        libffi-dev \
        musl-dev \
        openssl-dev \
        python3 \
        python3-dev \
        py3-pip

# Set working dir
WORKDIR /app

# Copy source files (adjust as needed)
COPY . /app

# Provide an entrypoint that injects runtime credentials into the settings file
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Fetch git submodules so their contents are available during the build
RUN git config --global --add safe.directory /app \
    && git -C /app submodule update --init --recursive

# Install OrpheusDL Python dependencies inside the image
RUN pip3 install --no-cache-dir --upgrade pip --break-system-packages \
    && pip3 install --no-cache-dir --break-system-packages -r /app/external/orpheusdl/requirements.txt

# Copy OrpheusDL core and modules into expected container locations
RUN mkdir -p /orpheusdl/modules/qobuz /orpheusdl/modules/musixmatch \
    && cp -a /app/external/orpheusdl/. /orpheusdl/ \
    && cp -a /app/external/orpheusdl-qobuz/. /orpheusdl/modules/qobuz/ \
    && cp -a /app/external/orpheusdl-musixmatch/. /orpheusdl/modules/musixmatch/

# Change to the OrpheusDL directory at runtime so bundled modules are detected
WORKDIR /orpheusdl

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
