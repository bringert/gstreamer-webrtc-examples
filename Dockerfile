# We use a trixie base image to get Gstreamer 1.26+
ARG DEBIAN_VERSION=trixie
FROM debian:${DEBIAN_VERSION}-slim

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update -y && apt-get install -y --no-install-recommends \
        curl \
        gstreamer1.0-plugins-good \
        gstreamer1.0-plugins-bad \
        gir1.2-gst-plugins-bad-1.0 \
        gstreamer1.0-plugins-ugly \
        gstreamer1.0-nice \
        gstreamer1.0-tools \
        gstreamer1.0-libcamera \
        gstreamer1.0-libav \
        libcamera-tools \
        libexif12 \
        libunwind8 \
        libdw1 \
        python3-gi \
        python3-gst-1.0 \
        python3-websockets \
        python3-httpx \
        python3-gi \
        python3-cryptography \
        python3-simplejson \
        && rm -rf /var/lib/apt/lists/*

ARG DOWNLOAD_VIDEO_URI=https://cdn.pixabay.com/video/2024/06/10/216058_small.mp4?download
ENV CANNED_VIDEO_FILE=/code/videos/video.mp4
RUN mkdir -p /code/videos && curl -L ${DOWNLOAD_VIDEO_URI} -o ${CANNED_VIDEO_FILE}

ENV GST_DEBUG=*:3
ENV PYTHONUNBUFFERED=1

WORKDIR /code

COPY *.py /code


ENTRYPOINT ["python3"]