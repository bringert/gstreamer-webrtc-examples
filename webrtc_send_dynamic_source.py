#!/usr/bin/env python3
#
# Copyright (c) 2025 Bjorn Bringert
#
# gstreamer Python demo app for streaming webrtc video and replacing the
# video source dynamically.
#
# Based on:
# - https://github.com/GStreamer/gstreamer/blob/34741e1db21aa7749eb501b944298c791b122990/subprojects/gst-examples/webrtc/sendrecv/gst/webrtc_sendrecv.py
#   Copyright (C) 2018 Matthew Waters <matthew@centricular.com>
#                 2022 Nirbheek Chauhan <nirbheek@centricular.com>
# - https://github.com/GStreamer/gst-python/blob/6fcc1433d731a76fe90efc0a146256b07318f036/examples/dynamic_src.py

import random
import websockets
import asyncio
import sys
import json
import argparse
import logging

import gi

gi.require_version("Gst", "1.0")
gi.require_version("GstWebRTC", "1.0")
gi.require_version("GstSdp", "1.0")
from gi.repository import Gst, GstWebRTC, GstSdp

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# DO NOT USE intra-refresh=true, it will cause the video to freeze, at least in Chrome on MacOS

SOURCE_BALL_DESC = """
videotestsrc is-live=true pattern=ball ! videoconvert ! queue !
 x264enc tune=zerolatency speed-preset=ultrafast key-int-max=30"""

SOURCE_SMPTE_DESC = """
videotestsrc is-live=true pattern=smpte background-color=0xFF00FF00 ! videoconvert ! queue !
 x264enc tune=zerolatency speed-preset=ultrafast key-int-max=30
"""

SOURCE_CANNED_DESC = """
filesrc location=/code/videos/video.mp4 ! qtdemux name=demux
demux.video_0 ! h264parse ! avdec_h264 ! videoscale ! videorate !
video/x-raw,width=1920,height=1080,framerate=30/1 !
videoconvert ! queue !
x264enc tune=zerolatency speed-preset=ultrafast key-int-max=30
demux.audio_0 ! fakesink
"""

WEBRTC_OUTPUT_DESC = """
rtph264pay aggregate-mode=zero-latency config-interval=-1 !
application/x-rtp,media=video,encoding-name=H264,payload=96 !
queue !
webrtcbin name=webrtc_send latency=0 bundle-policy=max-bundle"""

sources = {}

def add_source(name, desc):
    sources[name] = desc

add_source("ball", SOURCE_BALL_DESC)
add_source("smpte", SOURCE_SMPTE_DESC)
add_source("canned", SOURCE_CANNED_DESC)

class WebRTCClient:
    def __init__(
        self,
        loop,
        our_id,
        peer_id,
        server,
        source,
    ):
        self.conn = None
        self.pipe = None
        self.video_src_bin = None
        self.output_bin = None
        self.webrtc = None
        self.event_loop = loop
        self.server = server
        # An optional user-specified ID we can use to register
        self.our_id = our_id
        # The actual ID we used to register
        self.id_ = None
        # An optional peer ID we should connect to
        self.peer_id = peer_id
        self.source = source

    async def send(self, msg):
        assert self.conn
        logger.info(f">>> {msg}")
        await self.conn.send(msg)

    async def connect(self):
        self.conn = await websockets.connect(self.server)
        if self.our_id is None:
            self.id_ = str(random.randrange(10, 10000))
        else:
            self.id_ = self.our_id
        await self.send(f"HELLO {self.id_}")

    async def setup_call(self):
        assert self.peer_id
        await self.send(f"SESSION {self.peer_id}")

    def send_soon(self, msg):
        asyncio.run_coroutine_threadsafe(self.send(msg), self.event_loop)

    def on_bus_poll_cb(self, bus):
        def remove_bus_poll():
            self.event_loop.remove_reader(bus.get_pollfd().fd)
            self.event_loop.stop()

        while bus.peek():
            msg = bus.pop()
            if msg.type == Gst.MessageType.ERROR:
                err = msg.parse_error()
                logger.error(f"{err.gerror} {err.debug}")
                remove_bus_poll()
                break
            elif msg.type == Gst.MessageType.EOS:
                remove_bus_poll()
                break
            elif msg.type == Gst.MessageType.LATENCY:
                if self.pipe:
                    logger.info("Recalculating latency")
                    self.pipe.recalculate_latency()

    def on_offer_created(self, promise, _, __):
        assert promise.wait() == Gst.PromiseResult.REPLIED
        reply = promise.get_reply()
        offer = reply["offer"]
        promise = Gst.Promise.new()
        logger.info("Offer created, setting local description")
        self.webrtc.emit("set-local-description", offer, promise)
        promise.interrupt()  # we don't care about the result, discard it
        text = offer.sdp.as_text()
        logger.info(f"Sending offer:\n{text}")
        self.send_soon(json.dumps({"sdp": {"type": "offer", "sdp": text}}))

    def on_negotiation_needed(self, _):
        logger.info("Negotiation needed, creating offer")
        promise = Gst.Promise.new_with_change_func(self.on_offer_created, None, None)
        self.webrtc.emit("create-offer", None, promise)

    def send_ice_candidate_message(self, _, mlineindex, candidate):
        self.send_soon(
            json.dumps({"ice": {"candidate": candidate, "sdpMLineIndex": mlineindex}})
        )

    def on_ice_gathering_state_notify(self, pspec, _):
        state = self.webrtc.get_property("ice-gathering-state")
        logger.info(f"ICE gathering state changed to {state}")

    def add_output_bin(self):
        self.output_bin = Gst.parse_bin_from_description(WEBRTC_OUTPUT_DESC, True)
        self.pipe.add(self.output_bin)

    def get_source_desc(self):
        if self.source in sources:
            return sources[self.source]
        else:
            raise ValueError(f"Invalid source: {self.source}")

    def create_source_bin(self):
        logger.info(f"Creating new video source bin for source {self.source}")
        desc = self.get_source_desc()
        logger.info(f"Source bin: {desc}")
        return Gst.parse_bin_from_description(desc, True)

    def set_source_bin(self, src_bin):
        if self.video_src_bin:
            self.video_src_bin.set_state(Gst.State.NULL)
            self.video_src_bin.unlink(self.output_bin)
            self.pipe.remove(self.video_src_bin)

        if src_bin:
            self.video_src_bin = src_bin
            self.pipe.add(self.video_src_bin)
            self.video_src_bin.link(self.output_bin)
            self.video_src_bin.sync_state_with_parent()

    def start_pipeline(self):
        logger.info("Creating pipeline")
        self.pipe = Gst.Pipeline.new()
        bus = self.pipe.get_bus()
        self.event_loop.add_reader(bus.get_pollfd().fd, self.on_bus_poll_cb, bus)

        self.add_output_bin()
        self.set_source_bin(self.create_source_bin())

        # Set up webrtc callbacks
        self.webrtc = self.output_bin.get_by_name("webrtc_send")
        self.webrtc.connect("on-negotiation-needed", self.on_negotiation_needed)
        self.webrtc.connect("on-ice-candidate", self.send_ice_candidate_message)
        self.webrtc.connect(
            "notify::ice-gathering-state", self.on_ice_gathering_state_notify
        )
        self.webrtc.emit("get-transceiver", 0).set_property(
            "direction", GstWebRTC.WebRTCRTPTransceiverDirection.SENDONLY
        )

        self.pipe.set_state(Gst.State.PLAYING)

    def on_source_idle(self, pad, info, new_src_bin):
        logger.info("Switching to new source")
        self.set_source_bin(new_src_bin)

        # TODO: renegotiation is needed if we change e.g. the source format
        #logger.info("Renegotiating")
        #self.on_negotiation_needed(self.webrtc)

        logger.info("Source bin replacement completed")
        return Gst.PadProbeReturn.REMOVE

    def set_source(self, source):
        logger.info(f"Changing source from {self.source} to {source}")
        self.source = source

        if not self.pipe or not self.webrtc:
            logger.info("Pipeline is not running, no source to replace")
            return

        try:
            new_src_bin = self.create_source_bin()
        except Exception:
            logger.exception("Failed to create new source bin")
            new_src_bin = None

        logger.info("Waiting for source pad to become idle before switching sources")
        self.video_src_bin.get_static_pad("src").add_probe(
            Gst.PadProbeType.IDLE, self.on_source_idle, new_src_bin
        )

    def handle_json(self, message):
        try:
            msg = json.loads(message)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON message: {str(e)}")
            logger.error(f"Message content: {repr(message)}")
            raise
        if "sdp" in msg:
            sdp = msg["sdp"]["sdp"]
            if msg["sdp"]["type"] == "answer":
                logger.info(f"Received answer:\n{sdp}")
                res, sdpmsg = GstSdp.SDPMessage.new_from_text(sdp)
                answer = GstWebRTC.WebRTCSessionDescription.new(
                    GstWebRTC.WebRTCSDPType.ANSWER, sdpmsg
                )
                promise = Gst.Promise.new()
                self.webrtc.emit("set-remote-description", answer, promise)
                promise.interrupt()  # we don't care about the result, discard it
        elif "ice" in msg:
            assert self.webrtc
            ice = msg["ice"]
            candidate = ice["candidate"]
            sdpmlineindex = ice["sdpMLineIndex"]
            self.webrtc.emit("add-ice-candidate", sdpmlineindex, candidate)
        else:
            logger.error("Unknown JSON message")

    def close_pipeline(self):
        if self.pipe:
            self.pipe.set_state(Gst.State.NULL)
            self.pipe = None
        self.output_bin = None
        self.video_src_bin = None
        self.webrtc = None

    async def loop(self):
        assert self.conn
        async for message in self.conn:
            logger.info(f"<<< {message}")
            if message == "HELLO":
                assert self.id_
                if not self.peer_id:
                    logger.info(f"Waiting for peer ID: ID is {self.id_}")
                else:
                    logger.info("Have peer ID: initiating call")
                    await self.setup_call()
            elif message == "SESSION_OK":
                self.start_pipeline()
            elif message == "OFFER_REQUEST":
                logger.info("Received offer request, creating offer")
                self.start_pipeline()
            elif message.startswith("ERROR"):
                logger.error(message)
                self.close_pipeline()
                return 1
            else:
                self.handle_json(message)
        self.close_pipeline()
        return 0

    async def stop(self):
        if self.conn:
            await self.conn.close()
        self.conn = None


def check_plugin_features():
    """ensure we have all the plugins/features we need"""
    needed = [
        "nicesink",
        "webrtcbin",
        "dtlssrtpenc",
        "srtpenc",
        "rtpbin",
        "x264enc",
        "h264parse",
        "videotestsrc",
    ]

    missing = []
    reg = Gst.Registry.get()
    for fname in needed:
        feature = reg.find_feature(fname, Gst.ElementFactory.__gtype__)
        if not feature:
            missing.append(fname)
    if missing:
        logger.error(f"Missing gstreamer elements: {missing}")
        return False
    return True


async def switch_source_on_newline(webrtc_client):
    """Read from stdin and toggle source on newline"""
    loop = asyncio.get_event_loop()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)

    while True:
        try:
            line = await reader.readline()
            if not line:  # EOF
                break
            # Cycle through all available sources
            source_list = list(sources.keys())
            current_index = source_list.index(webrtc_client.source) if webrtc_client.source in source_list else -1
            next_index = (current_index + 1) % len(source_list)
            new_source = source_list[next_index]
            webrtc_client.set_source(new_source)
        except asyncio.CancelledError:
            break


def main():
    Gst.init(None)
    parser = argparse.ArgumentParser()
    parser.add_argument("--peer-id", help="String ID of the peer to connect to")
    parser.add_argument(
        "--our-id", help="String ID that the peer can use to connect to us"
    )
    parser.add_argument(
        "--server",
        default="wss://webrtc.gstreamer.net:8443",
        help='Signalling server to connect to, eg "wss://127.0.0.1:8443"',
    )
    parser.add_argument(
        "--source",
        default="ball",
        help=f"Source to use for the video stream, one of: {list(sources.keys())}",
    )
    args = parser.parse_args()
    if not check_plugin_features():
        sys.exit(1)
    if not args.peer_id and not args.our_id:
        print("You must pass either --peer-id or --our-id")
        sys.exit(1)

    logger.info(f"Starting with source {args.source}")

    loop = asyncio.new_event_loop()
    c = WebRTCClient(
        loop,
        our_id=args.our_id,
        peer_id=args.peer_id,
        server=args.server,
        source=args.source,
    )

    # Start stdin reading task
    stdin_task = loop.create_task(switch_source_on_newline(c))
    try:
        loop.run_until_complete(c.connect())
        res = loop.run_until_complete(c.loop())
    except KeyboardInterrupt:
        logger.info("\nShutting down...")
        res = 0
    finally:
        # Cancel stdin task when done
        stdin_task.cancel()
        try:
            loop.run_until_complete(stdin_task)
        except asyncio.CancelledError:
            pass
        # Ensure client is cleaned up
        c.close_pipeline()
        loop.run_until_complete(c.stop())
    sys.exit(res)

if __name__ == "__main__":
    main()