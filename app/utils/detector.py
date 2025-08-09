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
    def __init__(self, app, detector_id, camera_stream, camera_ip, camera_stream_manager, tracking=False):
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
        self.tracking = tracking
        
        # --- Custom pretrained tracking ---
        self.model_name = None

        # FPS calculation
        self.fps_calculator = FPSCalculator()
        self.inference_times = deque(maxlen=30)

        # Register this detector as a consumer
        if self.camera_stream:
            self.camera_stream.add_consumer(self.consumer_id)
        
        logger.info(f"Initialized DetectorThread for detector ID: {self.detector_id} - Consumer: {self.consumer_id} - Tracking: {self.tracking}")

    def _load_model_from_database(self):
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
                
                # --- Custom pretrained tracking ---
                self.model_name = model.model_name
                
                # Create temporary file for the model
                self.temp_model_file = tempfile.NamedTemporaryFile(suffix='.pt', delete=False)
                self.temp_model_file.write(model.model_file)
                self.temp_model_file.close()
                
                # Load YOLO model from temporary file
                self.yolo_model = YOLO(self.temp_model_file.name)
                logger.info(f"Successfully loaded model {self.model_name} for detector ID: {self.detector_id}")
                return True
                
        except Exception as e:
            logger.error(f"Error loading model for detector ID: {self.detector_id}: {e}")
            return False

    def _calculate_average_inference_time(self):
        if len(self.inference_times) > 0:
            return sum(self.inference_times) / len(self.inference_times)
        return 0.0

    def run(self):
        logger.info(f"DetectorThread started for detector ID: {self.detector_id}")
        
        if not self._load_model_from_database():
            logger.error(f"Failed to load model for detector ID: {self.detector_id}")
            return
        
        frame_count = 0 
            
        # --- 1. Frame skipping logic ---
        TARGET_FPS = 15.0
        TIME_BUDGET = 1.0 / TARGET_FPS
        skip_next_frame = False
        
        try:
            while self.running:
                try:
                    if frame_count > 0 and frame_count % 30 == 0:
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
                    
                    frame = self.camera_stream.get_frame()
                    if frame is not None:
                        frame_count += 1
                        
                        # --- 2. Frame skipping logic ---
                        if skip_next_frame:
                            skip_next_frame = False
                            continue 

                        try:
                            with self.lock:
                                inference_start = time.time()
                                
                                if self.tracking:
                                    results = self.yolo_model.track(frame, persist=True, tracker="bytetrack.yaml", verbose=False)
                                else:
                                    results = self.yolo_model(frame, verbose=False)
                                    if results[0].boxes.id is not None:
                                        results[0].boxes.id = None
                                
                                # --- Custom pretrained tracking ---
                                # logger.info(f"Checking filter condition for model: '{self.model_name}'")
                                if self.model_name and self.model_name.strip().lower() == 'pretrained':
                                    person_class_id = 0
                                    mask = results[0].boxes.cls == person_class_id
                                    results[0] = results[0][mask]
                                    
                                inference_time = time.time() - inference_start
                                self.inference_times.append(inference_time)
                                
                                # --- 2. Frame skipping logic ---
                                if inference_time > TIME_BUDGET:
                                    skip_next_frame = True
                                    logger.warning(f"BOTTLENECK: Processing time {inference_time*1000:.0f}ms > Budget {TIME_BUDGET*1000:.0f}ms. Skipping next frame.")
                                
                                annotated_frame = results[0].plot(
                                    conf=True,
                                    labels=True,
                                    boxes=True,
                                    line_width=2,
                                    font_size=12
                                )
                                
                                current_fps = self.fps_calculator.update()
                                avg_inference_time = self._calculate_average_inference_time()
                                
                                annotated_frames[self.detector_id] = annotated_frame
                                
                                detector_fps_info[self.detector_id] = {
                                    'fps': round(current_fps, 1),
                                    'inference_time': round(avg_inference_time * 1000, 1),
                                    'detections': len(results[0].boxes),
                                    'last_update': time.time()
                                }
                                
                                if len(results[0].boxes) > 0 and frame_count % 60 == 0:
                                    detections = len(results[0].boxes)
                                    logger.info(f"Detector {self.detector_id}: {detections} objects, FPS: {current_fps:.1f}, Inference: {avg_inference_time*1000:.1f}ms")
                                    
                        except Exception as e:
                            logger.error(f"Error processing frame for detector ID: {self.detector_id}: {e}", exc_info=True)
                            
                    else:
                        time.sleep(0.1)
                    
                    frame_count += 1
                    time.sleep(0.033)
                    
                except Exception as e:
                    logger.error(f"Unexpected error in detector thread {self.detector_id}: {e}", exc_info=True)
                    time.sleep(1)
                    
        except Exception as e:
            logger.error(f"Critical error in detector thread {self.detector_id}: {e}", exc_info=True)
        finally:
            self._cleanup()
        
        logger.info(f"DetectorThread for detector ID: {self.detector_id} finished")
    
    def _cleanup(self):
        """Cleanup resources"""
        try:
            if self.camera_stream and hasattr(self.camera_stream, 'remove_consumer'):
                self.camera_stream.remove_consumer(self.consumer_id)
            
            if self.camera_stream_manager and self.camera_ip:
                self.camera_stream_manager.release_stream(self.camera_ip, self.consumer_id)
            
            if self.temp_model_file and os.path.exists(self.temp_model_file.name):
                try:
                    os.unlink(self.temp_model_file.name)
                    logger.info(f"Cleaned up temporary model file for detector ID: {self.detector_id}")
                except Exception as e:
                    logger.warning(f"Failed to clean up temporary model file: {e}")
            
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
        self.app = app
        self.update_detectors()

    def update_detectors(self, tracking_status={}):
        if not self.app:
            logger.error("DetectorManager not initialized with app context")
            return
            
        from app.models import Detector
        
        with self.app.app_context():
            with self.lock:
                logger.info("Updating detectors...")
                
                try:
                    active_db_detectors = {d.id: d for d in Detector.query.filter(Detector.running == True).all()}
                    active_db_ids = set(active_db_detectors.keys())
                    running_thread_ids = set(self.detectors.keys())

                    ids_to_stop = running_thread_ids - active_db_ids
                    for detector_id in ids_to_stop:
                        logger.info(f"Detector {detector_id} no longer active in DB. Stopping thread.")
                        self._stop_detector_thread(detector_id)

                    for detector_id, db_detector in active_db_detectors.items():
                        is_tracking = tracking_status.get(detector_id, False)
                        
                        if detector_id in self.detectors:
                            if self.detectors[detector_id].tracking != is_tracking:
                                logger.info(f"Tracking mode changed for detector {detector_id}. Restarting thread.")
                                self._stop_detector_thread(detector_id)
                                self._start_detector_thread(db_detector, is_tracking)
                        else:
                            logger.info(f"New active detector {detector_id}. Starting thread.")
                            self._start_detector_thread(db_detector, is_tracking)
                            
                    logger.info(f"Detector update completed. Active threads: {len(self.detectors)}")
                    
                except Exception as e:
                    logger.error(f"Error during detector update: {e}", exc_info=True)

    def _start_detector_thread(self, detector, is_tracking):
        from app.models import Camera, Model
        
        try:
            camera = Camera.query.get(detector.camera_id)
            if not camera or not camera.status:
                logger.warning(f"Camera {detector.camera_id} is not active. Cannot start detector {detector.id}")
                return

            model = Model.query.get(detector.model_id)
            if not model or not model.model_file:
                logger.warning(f"Model {detector.model_id} is not valid. Cannot start detector {detector.id}")
                return

            consumer_id = f"detector_{detector.id}"
            camera_stream = self.camera_manager.get_camera_stream(camera.ip_address, consumer_id)
            if not camera_stream:
                logger.warning(f"Cannot get camera stream for {camera.ip_address}. Cannot start detector {detector.id}")
                return

            detector_thread = DetectorThread(
                self.app,
                detector.id,
                camera_stream,
                camera.ip_address,
                self.camera_manager,
                tracking=is_tracking
            )
            detector_thread.start()
            self.detectors[detector.id] = detector_thread
            
            logger.info(f"Started detector ID: {detector.id} with tracking={is_tracking}")

        except Exception as e:
            logger.error(f"Error starting new detector {detector.id}: {e}", exc_info=True)
            
    def _stop_detector_thread(self, detector_id):
        if detector_id in self.detectors:
            try:
                detector_thread = self.detectors.pop(detector_id)
                detector_thread.stop()
                detector_thread.join(timeout=5.0)
                logger.info(f"Successfully stopped detector ID: {detector_id}")
            except Exception as e:
                logger.error(f"Error stopping detector {detector_id}: {e}")
                if detector_id in self.detectors:
                    del self.detectors[detector_id]
        else:
            logger.warning(f"Attempted to stop non-existent detector thread {detector_id}")

    def stop_all(self):
        with self.lock:
            logger.info("Stopping all detectors...")
            
            for detector_id in list(self.detectors.keys()):
                self._stop_detector_thread(detector_id)
            
            self.detectors.clear()
            
            try:
                self.camera_manager.stop_all()
            except Exception as e:
                logger.error(f"Error stopping camera streams: {e}")
            
            global annotated_frames, detector_fps_info
            annotated_frames.clear()
            detector_fps_info.clear()
            
            logger.info("All detectors and camera streams stopped.")
    
    def get_detector_status(self):
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