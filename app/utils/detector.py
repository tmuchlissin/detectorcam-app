import os
import threading
import time
import logging
import tempfile
from collections import deque
from ultralytics import YOLO
from .cctv import CameraStreamManager

# Setup logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(threadName)s - %(levelname)s - %(message)s')
file_handler = logging.FileHandler('detector.log')
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

# Store annotated frames and FPS info for detector streaming
annotated_frames = {}
detector_fps_info = {}

class FPSCalculator:
    def __init__(self, window_size=30):
        self.window_size = window_size
        self.frame_times = deque(maxlen=window_size)
        self.last_fps = 0.0
    
    def update(self):
        current_time = time.time()
        self.frame_times.append(current_time)
        
        if len(self.frame_times) >= 2:
            time_diff = self.frame_times[-1] - self.frame_times[0]
            if time_diff > 0:
                self.last_fps = (len(self.frame_times) - 1) / time_diff
        
        return self.last_fps

class DetectorThread(threading.Thread):
    def __init__(self, app, detector_id, camera_stream, camera_ip, camera_stream_manager):
        super().__init__(name=f"DetectorThread-{detector_id}")
        self.app = app
        self.detector_id = detector_id
        self.camera_stream = camera_stream
        self.camera_ip = camera_ip
        self.camera_stream_manager = camera_stream_manager
        self.consumer_id = f"detector_{detector_id}"
        self.running = True
        self.lock = threading.Lock()
        self.yolo_model = None
        self.temp_model_file = None
        
        # FPS calculation
        self.fps_calculator = FPSCalculator()
        self.inference_times = deque(maxlen=30)  # Store last 30 inference times
        
        # Register this detector as a consumer
        if self.camera_stream:
            self.camera_stream.add_consumer(self.consumer_id)
        
        logger.info(f"Initialized DetectorThread for detector ID: {self.detector_id} - Consumer: {self.consumer_id}")
    
    def _load_model_from_database(self):
        """Load YOLO model from database binary data"""
        try:
            from app.models import Detector, Model
            with self.app.app_context():
                detector = Detector.query.get(self.detector_id)
                if not detector:
                    logger.error(f"Detector not found for ID: {self.detector_id}")
                    return False
                
                model = Model.query.get(detector.model_id)
                if not model or not model.model_file:
                    logger.error(f"Model not found or model file is empty for detector ID: {self.detector_id}")
                    return False
                
                # Create temporary file for the model
                import tempfile
                self.temp_model_file = tempfile.NamedTemporaryFile(suffix='.pt', delete=False)
                self.temp_model_file.write(model.model_file)
                self.temp_model_file.close()
                
                # Load YOLO model from temporary file
                from ultralytics import YOLO
                self.yolo_model = YOLO(self.temp_model_file.name)
                logger.info(f"Successfully loaded model {model.model_name} for detector ID: {self.detector_id}")
                return True
                
        except Exception as e:
            logger.error(f"Error loading model for detector ID: {self.detector_id}: {e}")
            return False
    
    def _calculate_average_inference_time(self):
        """Calculate average inference time from recent measurements"""
        if len(self.inference_times) > 0:
            return sum(self.inference_times) / len(self.inference_times)
        return 0.0
    
    def run(self):
        logger.info(f"DetectorThread started for detector ID: {self.detector_id}")
        
        # Load model from database
        if not self._load_model_from_database():
            logger.error(f"Failed to load model for detector ID: {self.detector_id}")
            return
        
        frame_count = 0
        
        try:
            while self.running:
                try:
                    # Check if detector is still active every 30 frames
                    if frame_count % 30 == 0:
                        with self.app.app_context():
                            from app.models import Detector, Camera
                            current_detector = Detector.query.get(self.detector_id)
                            if not current_detector or not current_detector.running:
                                logger.info(f"Detector {self.detector_id} became inactive, stopping thread")
                                break
                            
                            current_camera = Camera.query.get(current_detector.camera_id)
                            if not current_camera or not current_camera.status:
                                logger.info(f"Camera for detector {self.detector_id} became inactive, stopping thread")
                                break
                    
                    if self.camera_stream is None or not self.camera_stream.is_healthy():
                        logger.debug(f"Camera stream unhealthy for detector ID: {self.detector_id}")
                        time.sleep(1)
                        continue
                    
                    # Get frame from camera stream
                    frame = self.camera_stream.get_frame()
                    if frame is not None:
                        try:
                            with self.lock:
                                # Measure inference time
                                inference_start = time.time()
                                
                                # Run YOLO detection on the frame
                                results = self.yolo_model(frame, verbose=False)
                                
                                # Calculate inference time
                                inference_time = time.time() - inference_start
                                self.inference_times.append(inference_time)
                                
                                # Get annotated frame with bounding boxes
                                annotated_frame = results[0].plot(
                                    conf=True,
                                    labels=True,
                                    boxes=True,
                                    line_width=2,
                                    font_size=12
                                )
                                
                                # Update FPS calculation
                                current_fps = self.fps_calculator.update()
                                avg_inference_time = self._calculate_average_inference_time()
                                
                                # Store the annotated frame for streaming
                                annotated_frames[self.detector_id] = annotated_frame
                                
                                # Store FPS and performance info
                                detector_fps_info[self.detector_id] = {
                                    'fps': round(current_fps, 1),
                                    'inference_time': round(avg_inference_time * 1000, 1),  # Convert to ms
                                    'detections': len(results[0].boxes),
                                    'last_update': time.time()
                                }
                                
                                # Log detection results occasionally
                                if len(results[0].boxes) > 0 and frame_count % 60 == 0:
                                    detections = len(results[0].boxes)
                                    logger.info(f"Detector {self.detector_id}: {detections} objects, FPS: {current_fps:.1f}, Inference: {avg_inference_time*1000:.1f}ms")
                                    
                        except Exception as e:
                            logger.error(f"Error processing frame for detector ID: {self.detector_id}: {e}")
                            
                    else:
                        time.sleep(0.1)  # Short sleep when no frame available
                    
                    frame_count += 1
                    time.sleep(0.033)  # ~30 FPS
                    
                except Exception as e:
                    logger.error(f"Unexpected error in detector thread {self.detector_id}: {e}")
                    time.sleep(1)
                    
        except Exception as e:
            logger.error(f"Critical error in detector thread {self.detector_id}: {e}")
        finally:
            self._cleanup()
        
        logger.info(f"DetectorThread for detector ID: {self.detector_id} finished")
    
    def _cleanup(self):
        """Cleanup resources"""
        try:
            # Remove consumer from camera stream
            if self.camera_stream and hasattr(self.camera_stream, 'remove_consumer'):
                self.camera_stream.remove_consumer(self.consumer_id)
            
            # Release stream in manager
            if self.camera_stream_manager and self.camera_ip:
                self.camera_stream_manager.release_stream(self.camera_ip, self.consumer_id)
            
            # Clean up temporary model file
            if self.temp_model_file and os.path.exists(self.temp_model_file.name):
                try:
                    os.unlink(self.temp_model_file.name)
                    logger.info(f"Cleaned up temporary model file for detector ID: {self.detector_id}")
                except Exception as e:
                    logger.warning(f"Failed to clean up temporary model file: {e}")
            
            # Remove annotated frame and FPS info from global dicts
            if self.detector_id in annotated_frames:
                del annotated_frames[self.detector_id]
            
            if self.detector_id in detector_fps_info:
                del detector_fps_info[self.detector_id]
                
        except Exception as e:
            logger.error(f"Error during cleanup for detector {self.detector_id}: {e}")
    
    def stop(self):
        logger.info(f"Stopping DetectorThread for detector ID: {self.detector_id}")
        self.running = False
    
    def join(self, timeout=None):
        """Override join to ensure proper cleanup"""
        super().join(timeout)
        if self.is_alive():
            logger.warning(f"DetectorThread {self.detector_id} did not stop gracefully")

class DetectorManager:
    def __init__(self):
        self.detectors = {}
        self.camera_manager = CameraStreamManager()
        self.lock = threading.Lock()
        self.app = None
    
    def initialize_detectors(self, app):
        """Initialize all active detectors from database"""
        self.app = app
        from app.models import Detector, Camera, Model
        
        with self.app.app_context():
            with self.lock:
                logger.info("Initializing detectors...")
                active_detectors = Detector.query.filter(Detector.running == True).all()
                
                for detector in active_detectors:
                    try:
                        # Validate camera
                        camera = Camera.query.get(detector.camera_id)
                        if not camera or not camera.status:
                            logger.warning(f"Camera {detector.camera_id} is not active or does not exist. Skipping detector {detector.id}")
                            continue
                        
                        # Validate model
                        model = Model.query.get(detector.model_id)
                        if not model or not model.model_file:
                            logger.warning(f"Model {detector.model_id} is not valid or has no model file. Skipping detector {detector.id}")
                            continue
                        
                        # Get camera stream
                        camera_stream = self.camera_manager.get_camera_stream(camera.ip_address)
                        if not camera_stream:
                            logger.warning(f"Cannot get camera stream for {camera.ip_address}. Skipping detector {detector.id}")
                            continue
                        
                        # Start detector thread
                        detector_thread = DetectorThread(self.app, detector.id, camera_stream, camera.ip_address, self.camera_manager)
                        detector_thread.start()
                        self.detectors[detector.id] = detector_thread
                        
                        logger.info(f"Detector {detector.id} started with camera stream {camera.ip_address} and model {model.model_name}")
                        
                    except Exception as e:
                        logger.error(f"Failed to initialize detector {detector.id}: {e}")
                        continue
                
                logger.info(f"Initialized {len(self.detectors)} detectors")
    
    def update_detectors(self):
        """Update detectors based on current database state"""
        if not self.app:
            logger.error("DetectorManager not initialized with app context")
            return
            
        from app.models import Detector, Camera, Model
        
        with self.app.app_context():
            with self.lock:
                logger.info("Updating detectors...")
                
                try:
                    # Get currently active detectors from database
                    active_detectors = Detector.query.filter(Detector.running == True).all()
                    active_detector_ids = {detector.id for detector in active_detectors}
                    
                    # Stop detectors that are no longer active
                    detectors_to_stop = []
                    for detector_id in list(self.detectors.keys()):
                        if detector_id not in active_detector_ids:
                            detectors_to_stop.append(detector_id)
                    
                    for detector_id in detectors_to_stop:
                        logger.info(f"Stopping detector ID: {detector_id}")
                        try:
                            detector_thread = self.detectors[detector_id]
                            detector_thread.stop()
                            detector_thread.join(timeout=5.0)
                            del self.detectors[detector_id]
                            logger.info(f"Successfully stopped detector ID: {detector_id}")
                        except Exception as e:
                            logger.error(f"Error stopping detector {detector_id}: {e}")
                    
                    # Start new detectors
                    for detector in active_detectors:
                        if detector.id not in self.detectors:
                            try:
                                # Validate camera
                                camera = Camera.query.get(detector.camera_id)
                                if not camera or not camera.status:
                                    logger.warning(f"Camera {detector.camera_id} is not active. Cannot start detector {detector.id}")
                                    continue
                                
                                # Validate model
                                model = Model.query.get(detector.model_id)
                                if not model or not model.model_file:
                                    logger.warning(f"Model {detector.model_id} is not valid. Cannot start detector {detector.id}")
                                    continue
                                
                                # Get camera stream with detector consumer ID
                                consumer_id = f"detector_{detector.id}"
                                camera_stream = self.camera_manager.get_camera_stream(camera.ip_address, consumer_id)
                                if not camera_stream:
                                    logger.warning(f"Cannot get camera stream for {camera.ip_address}. Cannot start detector {detector.id}")
                                    continue
                                
                                # Start new detector thread
                                detector_thread = DetectorThread(
                                    self.app, 
                                    detector.id, 
                                    camera_stream, 
                                    camera.ip_address,
                                    self.camera_manager
                                )
                                detector_thread.start()
                                self.detectors[detector.id] = detector_thread
                                
                                logger.info(f"Started new detector ID: {detector.id} with camera {camera.ip_address} and model {model.model_name}")
                                
                            except Exception as e:
                                logger.error(f"Error starting new detector {detector.id}: {e}")
                                continue
                    
                    logger.info(f"Detector update completed. Active detectors: {len(self.detectors)}")
                    
                except Exception as e:
                    logger.error(f"Error during detector update: {e}")
    
    def _cleanup_unused_camera_streams(self, active_detectors):
        """Stop camera streams that are no longer needed"""
        try:
            from app.models import Camera
            
            # Get IP addresses of cameras currently used by active detectors
            active_camera_ips = set()
            for detector in active_detectors:
                camera = Camera.query.get(detector.camera_id)
                if camera:
                    active_camera_ips.add(camera.ip_address)
            
            # Stop unused camera streams
            streams_to_stop = []
            for ip_address in list(self.camera_manager.camera_streams.keys()):
                if ip_address not in active_camera_ips:
                    streams_to_stop.append(ip_address)
            
            for ip_address in streams_to_stop:
                logger.info(f"Stopping unused camera stream for IP: {ip_address}")
                try:
                    self.camera_manager.camera_streams[ip_address].stop()
                    self.camera_manager.camera_streams[ip_address].join(timeout=5.0)
                    del self.camera_manager.camera_streams[ip_address]
                    logger.info(f"Successfully stopped camera stream for IP: {ip_address}")
                except Exception as e:
                    logger.error(f"Error stopping camera stream {ip_address}: {e}")
                    
        except Exception as e:
            logger.error(f"Error during camera stream cleanup: {e}")
    
    def stop_all(self):
        """Stop all detectors and camera streams"""
        with self.lock:
            logger.info("Stopping all detectors...")
            
            # Stop all detector threads
            for detector_id, detector_thread in list(self.detectors.items()):
                try:
                    logger.info(f"Stopping detector thread {detector_id}")
                    detector_thread.stop()
                    detector_thread.join(timeout=5.0)  # Wait max 5 seconds
                    logger.info(f"Stopped detector thread {detector_id}")
                except Exception as e:
                    logger.error(f"Error stopping detector thread {detector_id}: {e}")
            
            # Clear detectors dictionary
            self.detectors.clear()
            
            # Stop all camera streams
            try:
                self.camera_manager.stop_all()
            except Exception as e:
                logger.error(f"Error stopping camera streams: {e}")
            
            # Clear annotated frames and FPS info
            global annotated_frames, detector_fps_info
            annotated_frames.clear()
            detector_fps_info.clear()
            
            logger.info("All detectors and camera streams stopped.")
    
    def get_detector_status(self):
        """Get status of all running detectors"""
        with self.lock:
            status = {}
            for detector_id, detector_thread in self.detectors.items():
                fps_info = detector_fps_info.get(detector_id, {})
                status[detector_id] = {
                    'running': detector_thread.running,
                    'alive': detector_thread.is_alive(),
                    'has_frames': detector_id in annotated_frames,
                    'fps': fps_info.get('fps', 0.0),
                    'inference_time': fps_info.get('inference_time', 0.0),
                    'detections': fps_info.get('detections', 0)
                }
            return status