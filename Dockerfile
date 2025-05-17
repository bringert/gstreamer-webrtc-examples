# We use a trixie base image to get Gstreamer 1.26+
ARG DEBIAN_VERSION=trixie
FROM debian:${DEBIAN_VERSION}-slim

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update -y && apt-get install -y \
        gstreamer1.0-plugins-good \
        gstreamer1.0-plugins-bad \
        gir1.2-gst-plugins-bad-1.0 \
        gstreamer1.0-plugins-ugly \
        gstreamer1.0-nice \
        gstreamer1.0-tools \
        gstreamer1.0-libcamera \
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
        python3-simplejson

ENV GST_DEBUG=*:2

WORKDIR /code

COPY webrtc_send_dynamic_source.py /code

ENTRYPOINT ["python3", "webrtc_send_dynamic_source.py"]
