import os
import json
import logging
import threading
import asyncio
import time
import cv2
import numpy as np
from collections import defaultdict
from aiortc import RTCPeerConnection, RTCSessionDescription, VideoStreamTrack
from aiortc.contrib.signaling import TcpSocketSignaling
from av import VideoFrame
import fractions
from datetime import datetime
import queue

logger = logging.getLogger(__name__)

# Global WebRTC manager
webrtc_manager = None

class WebRTCStreamer:
    def __init__(self):
        self.pcs = {}
        self.tracks = {}
        self.lock = threading.Lock()
        self.signaling = None
        self.signaling_task = None
        self.frame_queues = {}
        self.frame_producers = {}
        self.loop = None
        self.executor = None
        self._running = False
        
    def start_signaling(self, port=9999):
        """Start the signaling server in a separate thread with its own event loop"""
        if self.signaling is None and not self._running:
            self._running = True
            # Start the async event loop in a separate thread
            self.async_thread = threading.Thread(target=self._run_async_server, args=(port,), daemon=True)
            self.async_thread.start()

    def _run_async_server(self, port):
        """Run the async server in its own thread with event loop"""
        try:
            # Create new event loop for this thread
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            
            # Initialize signaling in this thread
            self.signaling = TcpSocketSignaling('0.0.0.0', port)
            
            # Start the server
            self.loop.run_until_complete(self._async_server_main())
        except Exception as e:
            logger.error(f"Error starting async server: {e}")
            self._running = False

    async def _async_server_main(self):
        """Main async server loop"""
        logger.info("WebRTC signaling server starting")
        try:
            await self.signaling.start()
            logger.info(f"WebRTC signaling server ready on port 9999")
            
            while self._running:
                try:
                    obj = await asyncio.wait_for(self.signaling.receive(), timeout=1.0)
                    if isinstance(obj, RTCSessionDescription):
                        await self.handle_offer(obj)
                    elif obj is None:
                        logger.info("Client disconnected")
                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    logger.error(f"Error receiving signaling message: {e}")
                    await asyncio.sleep(0.1)
                    
        except Exception as e:
            logger.error(f"Signaling error: {e}")
        finally:
            if self.signaling:
                try:
                    await self.signaling.close()
                except:
                    pass

    def get_low_latency_config(self):
        """Configuration for ultra-low latency WebRTC"""
        return {
            "iceServers": [],  # Use only local candidates for lowest latency
            "iceCandidatePoolSize": 0,
            "rtcpMuxPolicy": "require",
            "bundlePolicy": "max-bundle",
        }
                
    async def handle_offer(self, offer):
        detector_id = None
        try:
            # Parse detector ID from offer
            detector_id = int(offer.sdp.split("detector_id:")[1].split("\r\n")[0])
        except:
            logger.error("Failed to parse detector ID from offer")
            return
            
        with self.lock:
            if detector_id not in self.pcs:
                # Create peer connection with low-latency configuration
                self.pcs[detector_id] = RTCPeerConnection(configuration=self.get_low_latency_config())
                self.tracks[detector_id] = OptimizedVideoStreamTrack(detector_id)
                
                # Add track with specific codec preferences for low latency
                self.pcs[detector_id].addTrack(self.tracks[detector_id])
                
                @self.pcs[detector_id].on("connectionstatechange")
                async def on_connectionstatechange():
                    state = self.pcs[detector_id].connectionState
                    logger.info(f"Connection state for detector {detector_id}: {state}")
                    if state == "failed" or state == "closed":
                        await self.cleanup_connection(detector_id)
                        
                @self.pcs[detector_id].on("track")
                def on_track(track):
                    logger.info(f"Track received for detector {detector_id}: {track.kind}")
            
            pc = self.pcs[detector_id]
            
        await pc.setRemoteDescription(offer)
        answer = await pc.createAnswer()
        
        # Modify SDP for low latency
        answer.sdp = self.optimize_sdp_for_latency(answer.sdp)
        
        await pc.setLocalDescription(answer)
        await self.signaling.send(answer)
        logger.info(f"Sent optimized answer for detector {detector_id}")

    def optimize_sdp_for_latency(self, sdp):
        """Optimize SDP for minimal latency"""
        lines = sdp.split('\r\n')
        optimized_lines = []
        
        for line in lines:
            optimized_lines.append(line)
            
            # Add low-latency optimizations
            if line.startswith('m=video'):
                # Force specific codec order (H.264 baseline for lowest latency)
                optimized_lines.append('a=fmtp:96 profile-level-id=42e01f;level-asymmetry-allowed=1;packetization-mode=1')
                
            elif line.startswith('a=rtcp-fb:'):
                # Enable feedback mechanisms for adaptive streaming
                if 'nack' in line or 'pli' in line or 'fir' in line:
                    continue  # Keep these for error recovery
                    
        return '\r\n'.join(optimized_lines)

    async def cleanup_connection(self, detector_id):
        """Clean up a specific connection"""
        with self.lock:
            if detector_id in self.pcs:
                try:
                    await self.pcs[detector_id].close()
                except:
                    pass
                del self.pcs[detector_id]
                
            if detector_id in self.tracks:
                del self.tracks[detector_id]
                
            if detector_id in self.frame_queues:
                del self.frame_queues[detector_id]
                
        logger.info(f"Cleaned up connection for detector {detector_id}")

    def push_frame_direct(self, detector_id, frame):
        """Direct frame push without intermediate queuing for lowest latency"""
        if detector_id in self.tracks:
            try:
                # Push frame directly to track
                self.tracks[detector_id].set_current_frame(frame)
                # Optional: Add frame counter for debugging
                if hasattr(self, '_debug_frame_count'):
                    self._debug_frame_count = getattr(self, '_debug_frame_count', 0) + 1
                    if self._debug_frame_count % 30 == 0:  # Log every 30 frames (1 second at 30fps)
                        logger.debug(f"Pushed {self._debug_frame_count} frames to detector {detector_id}")
            except Exception as e:
                logger.error(f"Error pushing frame directly to detector {detector_id}: {e}")
        else:
            logger.warning(f"No track available for detector {detector_id}, ensure WebRTC connection is established")

    def ensure_connection_ready(self, detector_id):
        """Ensure WebRTC connection is ready for the detector"""
        with self.lock:
            if detector_id not in self.pcs:
                # Pre-create peer connection for immediate streaming
                self.pcs[detector_id] = RTCPeerConnection(configuration=self.get_low_latency_config())
                logger.info(f"Pre-created peer connection for detector {detector_id}")
            
            if detector_id not in self.tracks:
                self.tracks[detector_id] = OptimizedVideoStreamTrack(detector_id)
                logger.info(f"Created video track for detector {detector_id}")

    def push_frame(self, detector_id, frame):
        """Backward compatibility method - redirects to optimized version"""
        # Auto-initialize track if it doesn't exist
        if detector_id not in self.tracks:
            self.ensure_connection_ready(detector_id)
        
        self.push_frame_direct(detector_id, frame)

    def stop(self):
        """Stop the WebRTC streamer"""
        self._running = False
        
        # Close all peer connections
        if self.loop and not self.loop.is_closed():
            for detector_id in list(self.pcs.keys()):
                asyncio.run_coroutine_threadsafe(self.cleanup_connection(detector_id), self.loop)

class OptimizedVideoStreamTrack(VideoStreamTrack):
    def __init__(self, detector_id):
        super().__init__()
        self.detector_id = detector_id
        self.current_frame = None
        self.frame_lock = threading.Lock()
        self.frame_counter = 0
        self.start_time = time.monotonic()
        self.last_frame_time = 0
        self.target_fps = 30  # Target FPS for consistent timing
        self.frame_interval = 1.0 / self.target_fps
        
    def set_current_frame(self, frame):
        """Set the current frame (thread-safe)"""
        with self.frame_lock:
            self.current_frame = frame.copy() if frame is not None else None
            
    async def recv(self):
        """Optimized receive method for minimal latency"""
        current_time = time.monotonic()
        
        # Frame rate control to prevent overwhelming the network
        if current_time - self.last_frame_time < self.frame_interval:
            await asyncio.sleep(0.001)  # Minimal sleep to prevent busy waiting
            
        with self.frame_lock:
            frame = self.current_frame
            
        if frame is None:
            # Return minimal black frame when no data available
            frame = np.zeros((240, 320, 3), dtype=np.uint8)  # Smaller default frame
            
        try:
            # Resize frame for optimal streaming (balance between quality and latency)
            height, width = frame.shape[:2]
            if width > 640 or height > 480:
                frame = cv2.resize(frame, (640, 480), interpolation=cv2.INTER_AREA)
            
            # Add minimal timestamp (optional, remove if not needed)
            timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            cv2.putText(
                frame, 
                timestamp, 
                (10, 25), 
                cv2.FONT_HERSHEY_SIMPLEX, 
                0.6, 
                (0, 255, 0), 
                1, 
                cv2.LINE_AA
            )
            
            # Convert to VideoFrame with optimized settings
            video_frame = VideoFrame.from_ndarray(frame, format='bgr24')
            
            # Precise timing for smooth playback
            self.frame_counter += 1
            elapsed = current_time - self.start_time
            
            # Use 90kHz clock for precise timing
            video_frame.pts = int(elapsed * 90000)
            video_frame.time_base = fractions.Fraction(1, 90000)
            
            self.last_frame_time = current_time
            return video_frame
            
        except Exception as e:
            logger.error(f"Error in optimized recv: {e}")
            # Return minimal frame on error
            empty_frame = np.zeros((240, 320, 3), dtype=np.uint8)
            video_frame = VideoFrame.from_ndarray(empty_frame, format='bgr24')
            
            self.frame_counter += 1
            elapsed = time.monotonic() - self.start_time
            video_frame.pts = int(elapsed * 90000)
            video_frame.time_base = fractions.Fraction(1, 90000)
            
            return video_frame

def init_webrtc_manager():
    global webrtc_manager
    if webrtc_manager is None:
        webrtc_manager = WebRTCStreamer()
        webrtc_manager.start_signaling()
        logger.info("WebRTC Manager initialized for real-time streaming")
    return webrtc_manager

def cleanup_webrtc_manager():
    """Cleanup function to be called when Flask app shuts down"""
    global webrtc_manager
    if webrtc_manager:
        webrtc_manager.stop()
        webrtc_manager = None

# Helper function for direct frame pushing (use this in your detector)
def push_frame_realtime(detector_id, frame):
    """Push frame directly for real-time streaming"""
    global webrtc_manager
    if webrtc_manager:
        webrtc_manager.push_frame_direct(detector_id, frame)