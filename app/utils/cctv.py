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

    def get_camera_stream(self, ip_address):
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
                camera_stream.start()
                self.camera_streams[ip_address] = camera_stream
            else:
                # Check if existing stream is healthy
                existing_stream = self.camera_streams[ip_address]
                if not existing_stream.is_healthy():
                    logger.warning(f"Existing stream for {ip_address} is unhealthy, restarting...")
                    existing_stream.stop()
                    if existing_stream.is_alive():
                        existing_stream.join(timeout=5)  # Wait max 5 seconds
                    
                    # Create new stream
                    camera_stream = CameraStream(ip_address)
                    camera_stream.start()
                    self.camera_streams[ip_address] = camera_stream
                    
            return self.camera_streams[ip_address]

    def stop_inactive_streams(self):
        from app.models import Camera
        with self.lock:
            logger.info("Checking for inactive camera streams.")
            for ip_address in list(self.camera_streams.keys()):
                camera = Camera.query.filter_by(ip_address=ip_address).first()
                if not camera or not camera.status:
                    logger.info(f"Stopping inactive camera stream for IP: {ip_address}")
                    stream = self.camera_streams[ip_address]
                    stream.stop()
                    
                    # Wait for thread to finish, but don't block indefinitely
                    if stream.is_alive():
                        stream.join(timeout=10)
                        if stream.is_alive():
                            logger.warning(f"Camera stream thread for {ip_address} did not stop gracefully")
                    
                    del self.camera_streams[ip_address]

    def stop_all(self):
        with self.lock:
            logger.info("Stopping all camera streams.")
            for ip_address, camera_stream in list(self.camera_streams.items()):
                camera_stream.stop()
                if camera_stream.is_alive():
                    camera_stream.join(timeout=10)
                    if camera_stream.is_alive():
                        logger.warning(f"Camera stream thread for {ip_address} did not stop gracefully")
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
                    self.camera_streams[ip_address].stop()
                except Exception as e:
                    logger.warning(f"Error stopping dead stream {ip_address}: {e}")
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
        self._initialize_capture()
        logger.info(f"Initialized CameraStream for IP: {self.ip_address}")

    def _initialize_capture(self):
        """Initialize the video capture with proper error handling"""
        try:
            if self.ip_address == 'http://1.1.1.1':
                self.capture = cv2.VideoCapture(0)
            else:
                self.capture = cv2.VideoCapture(self.ip_address)
            
            if self.capture is not None:
                self.capture.set(cv2.CAP_PROP_FPS, 30)
                # Set buffer size to prevent frame accumulation
                self.capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                
            if not self.capture.isOpened():
                logger.error(f"Failed to open camera stream for IP: {self.ip_address}")
                self.connection_failed = True
        except Exception as e:
            logger.error(f"Exception while initializing camera {self.ip_address}: {e}")
            self.connection_failed = True

    def run(self):
        logger.info(f"Camera stream started for IP: {self.ip_address}")
        consecutive_failures = 0
        max_consecutive_failures = 10
        
        while self.running:
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
                        self.frame = frame
                    consecutive_failures = 0  # Reset failure count on success
                else:
                    consecutive_failures += 1
                    logger.warning(f"Failed to read frame from IP: {self.ip_address} (attempt {consecutive_failures})")
                    
                    if consecutive_failures >= 3:  # Try reconnecting after 3 consecutive failures
                        self._reconnect()
                        time.sleep(1)
                    
            except Exception as e:
                logger.error(f"Exception while reading frame from {self.ip_address}: {e}")
                consecutive_failures += 1
                if consecutive_failures >= 3:
                    self._reconnect()
                time.sleep(1)
        
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
            return self.frame.copy() if self.frame is not None else None

    def stop(self):
        """Gracefully stop the camera stream"""
        logger.info(f"Stopping camera stream for IP: {self.ip_address}")
        self.running = False
        
        # Give the thread a moment to finish current operations
        time.sleep(0.1)
        
        if self.capture is not None:
            try:
                self.capture.release()
            except Exception as e:
                logger.warning(f"Error releasing capture during stop for {self.ip_address}: {e}")
            finally:
                self.capture = None
        
        logger.info(f"Camera stream stopped for IP: {self.ip_address}")

    def is_healthy(self):
        """Check if the camera stream is healthy"""
        return self.running and not self.connection_failed and self.capture is not None and self.capture.isOpened()
