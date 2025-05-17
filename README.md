# GStreamer WebRTC Examples

`webrtc_send_dynamic_source.py` is an example of producing a WebRTC stream
from a video source that can be replaced dynamically while streaming.
To keep it minimal, the example is video-only (no audio), and send-only
(no incoming stream).

## Usage

1. Build the Docker image:
    ```bash
    docker build -t webrtc_example .
    ```

2. Pick a random number `NNNNN`

3. Run the example, substituing `NNNNN` with your random number:
    ```bash
    docker run --rm -it --init --name webrtc_example webrtc_example --our-id=NNNNN
    ```

4. Open <https://webrtc.gstreamer.net/>

5. Enter your random number under "Enter peer id"

6. Check "Remote offerer"

7. Set "getUserMedia constraints being used:" to `{}``

8. Click "Connect"

9. The video output should be shown in the web page

10. In the terminal where the docker container is runnning, press Enter
    to switch sources.
