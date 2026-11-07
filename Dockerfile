FROM python:3.13-alpine@sha256:2d9aefe2fef018a7eb2c13064c89c71929800fd2e5dccdbf52ea5da5bb8d929a AS base

# Build the stable release on the same Alpine base; do not mix in edge packages.
FROM base AS qbittorrent-build
ARG QBITTORRENT_VERSION=5.2.4
ARG QBITTORRENT_SHA256=226a6ad1aa7810fcbfa58b0d28b14feb8e207726cbe774d4d267ce769c19dd6c
ARG QBITTORRENT_BUILD_JOBS=2
RUN apk add --no-cache build-base cmake ninja curl boost-dev \
    libtorrent-rasterbar-dev openssl-dev zlib-dev \
    qt6-qtbase-dev qt6-qtbase-private-dev qt6-qttools-dev
WORKDIR /src
RUN curl --fail --location --retry 3 \
      "https://github.com/qbittorrent/qBittorrent/archive/refs/tags/release-${QBITTORRENT_VERSION}.tar.gz" \
      --output qbittorrent.tar.gz \
    && echo "${QBITTORRENT_SHA256}  qbittorrent.tar.gz" | sha256sum -c - \
    && tar -xzf qbittorrent.tar.gz --strip-components=1 \
    && cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release \
      -DGUI=OFF -DWEBUI=ON -DSTACKTRACE=OFF -DTESTING=OFF \
    && cmake --build build --parallel "${QBITTORRENT_BUILD_JOBS}" \
    && install -D -m 755 build/qbittorrent-nox /out/qbittorrent-nox \
    && test "$(/out/qbittorrent-nox --version)" = "qBittorrent v${QBITTORRENT_VERSION}"

FROM base
RUN apk add --no-cache libtorrent-rasterbar qt6-qtbase ffmpeg mkvtoolnix tesseract-ocr \
    tesseract-ocr-data-eng tesseract-ocr-data-dan tesseract-ocr-data-swe \
    tesseract-ocr-data-nor tesseract-ocr-data-deu tesseract-ocr-data-fra \
    tesseract-ocr-data-spa tesseract-ocr-data-ita tesseract-ocr-data-nld \
    tesseract-ocr-data-por tesseract-ocr-data-fin tesseract-ocr-data-pol \
    tesseract-ocr-data-ukr tesseract-ocr-data-ara tesseract-ocr-data-jpn \
    tesseract-ocr-data-kor tesseract-ocr-data-chi_sim
COPY --from=qbittorrent-build /out/qbittorrent-nox /usr/bin/qbittorrent-nox
RUN qbittorrent-nox --version
WORKDIR /app
ARG CODEX_VERSION=0.162.1
RUN apk add --no-cache nodejs npm && npm install --global @openai/codex@${CODEX_VERSION} && codex --version
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py deletion_events.py bot_upload.py event_notifier.py hub_email.py hub.py runtime.py state.py qbit_rpc.py qbit_worker.py torrent_port.py trackers.py benefits.py covers.py torrent_meta.py rss.py rss_gate.py green_credit.py download_storage.py storage.py storage_browser.py ./
COPY templates ./templates
COPY streaming.py ./
COPY conversion_workflow.py conversion_options.py conversion.py library_conversion.py shared_library.py media_bitrates.py ./
COPY subtitle_text.py subtitle_pgs.py subtitle_media.py subtitle_auth.py subtitle_translation.py ./
COPY subtitle_device_auth.py subtitle_codex_rpc.py ./
COPY tools/chatgpt_login.py ./tools/chatgpt_login.py
COPY converter_runtime.py ./
COPY dolby_backup.py dolby_jobs.py conversion_media.py conversion_decoder.py converter_worker.py remote_conversion.py remote_helper.py ./
COPY seed_potential.py ./
COPY rss_history.py ./
COPY rss_budget.py ./
COPY tracker_credit.py ./
COPY tracker_providers.py ./
COPY tracker_history.py ./
COPY storage_release.py ./
COPY move_progress.py ./
COPY manual_package.py ./
COPY torrent_search.py search_routes.py ./
COPY static ./static
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
EXPOSE 8088
CMD ["python", "app.py"]
