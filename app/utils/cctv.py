import threading
import cv2
import time
import logging
import queue
import sys

# Setup logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(threadName)s - %(levelname)s - %(message)s')

file_handler = logging.FileHandler('detector.log')
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

# Stream handler untuk menulis ke terminal
stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.setFormatter(formatter)
logger.addHandler(stream_handler)

class CameraStreamManager:
    def __init__(self):
        self.camera_streams = {}
        self.lock = threading.Lock()

    def get_camera_stream(self, ip_address, consumer_id=None):
        from app.models import Camera
        with self.lock:
            # Check if camera is active in database
            camera = Camera.query.filter_by(ip_address=ip_address).first()
            if not camera or not camera.status:
                logger.warning(f"Camera with IP {ip_address} is not active or does not exist.")
                return None
                
            if ip_address not in self.camera_streams:
                logger.info(f"Starting new camera stream for IP: {ip_address}")
                camera_stream = CameraStream(ip_address)
                if consumer_id:
                    camera_stream.add_consumer(consumer_id)
                camera_stream.start()
                self.camera_streams[ip_address] = camera_stream
            else:
                # Check if existing stream is healthy
                existing_stream = self.camera_streams[ip_address]
                if not existing_stream.is_healthy() or not existing_stream.is_alive():
                    logger.warning(f"Existing stream for {ip_address} is unhealthy, restarting...")
                    
                    # Stop the old stream
                    try:
                        existing_stream.stop()
                        if existing_stream.is_alive():
                            existing_stream.join(timeout=5)
                    except Exception as e:
                        logger.error(f"Error stopping old stream: {e}")
                    
                    # Create new stream
                    camera_stream = CameraStream(ip_address)
                    if consumer_id:
                        camera_stream.add_consumer(consumer_id)
                    camera_stream.start()
                    self.camera_streams[ip_address] = camera_stream
                else:
                    # Add consumer to existing healthy stream
                    if consumer_id:
                        existing_stream.add_consumer(consumer_id)
                    
            return self.camera_streams[ip_address]

    def release_stream(self, ip_address, consumer_id=None):
        """Release stream for a specific consumer"""
        with self.lock:
            if ip_address in self.camera_streams:
                stream = self.camera_streams[ip_address]
                if consumer_id:
                    stream.remove_consumer(consumer_id)
                
                # If stream stopped itself due to no consumers, remove from manager
                if not stream.is_alive() or not stream.running:
                    logger.info(f"Removing stopped stream for {ip_address}")
                    try:
                        if stream.is_alive():
                            stream.join(timeout=2)
                    except Exception as e:
                        logger.warning(f"Error joining stream thread: {e}")
                    finally:
                        del self.camera_streams[ip_address]

    def force_restart_stream(self, ip_address, consumer_id=None):
        """Force restart stream untuk mengatasi masalah"""
        with self.lock:
            logger.info(f"Force restarting camera stream for IP: {ip_address}")
            
            # Stop existing stream
            if ip_address in self.camera_streams:
                try:
                    old_stream = self.camera_streams[ip_address]
                    old_stream.stop()
                    if old_stream.is_alive():
                        old_stream.join(timeout=5)
                except Exception as e:
                    logger.warning(f"Error stopping stream during force restart {ip_address}: {e}")
                finally:
                    del self.camera_streams[ip_address]
            
            # Wait a bit for resource cleanup
            time.sleep(1)
            
            # Start new stream
            return self.get_camera_stream(ip_address, consumer_id)

    def stop_inactive_streams(self):
        from app.models import Camera
        with self.lock:
            logger.info("Checking for inactive camera streams.")
            streams_to_remove = []
            
            for ip_address in list(self.camera_streams.keys()):
                camera = Camera.query.filter_by(ip_address=ip_address).first()
                if not camera or not camera.status:
                    logger.info(f"Stopping inactive camera stream for IP: {ip_address}")
                    stream = self.camera_streams[ip_address]
                    
                    try:
                        stream.stop()
                        if stream.is_alive():
                            stream.join(timeout=10)
                    except Exception as e:
                        logger.warning(f"Error stopping inactive stream {ip_address}: {e}")
                    finally:
                        streams_to_remove.append(ip_address)
            
            # Remove stopped streams
            for ip_address in streams_to_remove:
                if ip_address in self.camera_streams:
                    del self.camera_streams[ip_address]

    def stop_all(self):
        with self.lock:
            logger.info("Stopping all camera streams.")
            for ip_address, camera_stream in list(self.camera_streams.items()):
                try:
                    camera_stream.stop()
                    if camera_stream.is_alive():
                        camera_stream.join(timeout=10)
                except Exception as e:
                    logger.warning(f"Error stopping stream {ip_address}: {e}")
            
            self.camera_streams.clear()

    def cleanup_dead_streams(self):
        """Remove dead camera streams from the manager"""
        with self.lock:
            dead_streams = []
            for ip_address, stream in self.camera_streams.items():
                if not stream.is_alive() or not stream.is_healthy():
                    dead_streams.append(ip_address)
            
            for ip_address in dead_streams:
                logger.info(f"Cleaning up dead stream for IP: {ip_address}")
                try:
                    if self.camera_streams[ip_address].is_alive():
                        self.camera_streams[ip_address].stop()
                        self.camera_streams[ip_address].join(timeout=5)
                except Exception as e:
                    logger.warning(f"Error cleaning up dead stream {ip_address}: {e}")
                finally:
                    del self.camera_streams[ip_address]
                    
class CameraStream(threading.Thread):
    def __init__(self, ip_address):
        super().__init__(name=f"CameraStream-{ip_address}")
        self.ip_address = ip_address
        self.capture = None
        self.frame = None
        self.running = True
        self.lock = threading.Lock()
        self.connection_failed = False
        self.last_frame_time = time.time()
        self.active_consumers = set()  # Track who is using this stream
        self._initialize_capture()
        logger.info(f"Initialized CameraStream for IP: {self.ip_address}")

    def _initialize_capture(self):
        """Initialize the video capture with proper error handling"""
        try:
            # Force release any existing capture first
            if self.capture is not None:
                try:
                    self.capture.release()
                    time.sleep(0.5)  # Give time for release
                except:
                    pass
            
            if self.ip_address == 'http://1.1.1.1':
                # For webcam, try different backends
                for backend in [cv2.CAP_DSHOW, cv2.CAP_V4L2, cv2.CAP_ANY]:
                    try:
                        self.capture = cv2.VideoCapture(0, backend)
                        if self.capture and self.capture.isOpened():
                            logger.info(f"Successfully opened webcam with backend {backend}")
                            break
                        else:
                            if self.capture:
                                self.capture.release()
                    except Exception as e:
                        logger.warning(f"Failed to open webcam with backend {backend}: {e}")
                        continue
            else:
                self.capture = cv2.VideoCapture(self.ip_address)
            
            if self.capture is not None and self.capture.isOpened():
                # Set optimal properties
                self.capture.set(cv2.CAP_PROP_FPS, 30)
                self.capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                self.capture.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                
                # Test read one frame to ensure it's working
                ret, test_frame = self.capture.read()
                if ret and test_frame is not None:
                    logger.info(f"Successfully initialized camera stream for IP: {self.ip_address}")
                    self.connection_failed = False
                else:
                    logger.error(f"Failed to read test frame for IP: {self.ip_address}")
                    self.connection_failed = True
            else:
                logger.error(f"Failed to open camera stream for IP: {self.ip_address}")
                self.connection_failed = True
                
        except Exception as e:
            logger.error(f"Exception while initializing camera {self.ip_address}: {e}")
            self.connection_failed = True

    def add_consumer(self, consumer_id):
        """Add a consumer to track stream usage"""
        with self.lock:
            self.active_consumers.add(consumer_id)
            logger.info(f"Added consumer {consumer_id} to stream {self.ip_address}. Total consumers: {len(self.active_consumers)}")

    def remove_consumer(self, consumer_id):
        """Remove a consumer and check if stream should be stopped"""
        with self.lock:
            self.active_consumers.discard(consumer_id)
            logger.info(f"Removed consumer {consumer_id} from stream {self.ip_address}. Remaining consumers: {len(self.active_consumers)}")
            
            # If no more consumers, stop the stream
            if len(self.active_consumers) == 0:
                logger.info(f"No consumers left for stream {self.ip_address}, stopping stream")
                self.stop()

    def run(self):
        logger.info(f"Camera stream started for IP: {self.ip_address}")
        consecutive_failures = 0
        max_consecutive_failures = 10
        
        while self.running:
            # Check if we have active consumers
            with self.lock:
                if len(self.active_consumers) == 0 and consecutive_failures > 3:
                    logger.info(f"No active consumers for {self.ip_address}, stopping stream")
                    break
            
            if self.connection_failed or not self.capture or not self.capture.isOpened():
                if consecutive_failures < max_consecutive_failures:
                    logger.warning(f"Attempting to reconnect to {self.ip_address}")
                    self._reconnect()
                    consecutive_failures += 1
                    time.sleep(2)
                    continue
                else:
                    logger.error(f"Max reconnection attempts reached for {self.ip_address}")
                    break
            
            try:
                ret, frame = self.capture.read()
                if ret and frame is not None:
                    with self.lock:
                        # Make sure to store a copy to avoid threading issues
                        self.frame = frame.copy()
                        self.last_frame_time = time.time()
                    consecutive_failures = 0  # Reset failure count on success
                else:
                    consecutive_failures += 1
                    logger.warning(f"Failed to read frame from IP: {self.ip_address} (attempt {consecutive_failures})")
                    
                    if consecutive_failures >= 3:
                        self._reconnect()
                        time.sleep(1)
                    
            except Exception as e:
                logger.error(f"Exception while reading frame from {self.ip_address}: {e}")
                consecutive_failures += 1
                if consecutive_failures >= 3:
                    self._reconnect()
                time.sleep(1)
        
        # Final cleanup
        self._cleanup()
        logger.info(f"Camera stream thread ending for IP: {self.ip_address}")

    def _reconnect(self):
        """Safely reconnect to the camera stream"""
        if not self.running:
            return
            
        logger.info(f"Reconnecting to camera stream for IP: {self.ip_address}")
        
        # Safely release the current capture
        if self.capture is not None:
            try:
                self.capture.release()
                time.sleep(1)  # Give more time for proper release
            except Exception as e:
                logger.warning(f"Error releasing capture for {self.ip_address}: {e}")
            finally:
                self.capture = None
        
        time.sleep(2)  # Wait before reconnecting
        
        # Reinitialize capture
        self._initialize_capture()
        
        if self.connection_failed:
            logger.warning(f"Reconnection failed for IP: {self.ip_address}")
        else:
            logger.info(f"Successfully reconnected to IP: {self.ip_address}")

    def get_frame(self):
        with self.lock:
            if self.frame is not None:
                return self.frame.copy()
            return None

    def _cleanup(self):
        """Proper cleanup of resources"""
        if self.capture is not None:
            try:
                self.capture.release()
                logger.info(f"Released camera capture for IP: {self.ip_address}")
            except Exception as e:
                logger.warning(f"Error releasing capture during cleanup for {self.ip_address}: {e}")
            finally:
                self.capture = None

    def stop(self):
        """Gracefully stop the camera stream"""
        logger.info(f"Stopping camera stream for IP: {self.ip_address}")
        self.running = False
        
        # Give the thread a moment to finish current operations
        time.sleep(0.1)

    def is_healthy(self):
        """Check if the camera stream is healthy"""
        if not self.running or self.connection_failed:
            return False
        
        if not self.capture or not self.capture.isOpened():
            return False
            
        # Check if frame is recent (within last 5 seconds)
        current_time = time.time()
        frame_age = current_time - self.last_frame_time
        if frame_age > 5.0:
            logger.warning(f"Frame too old for {self.ip_address}: {frame_age:.2f}s")
            return False
            
        return True