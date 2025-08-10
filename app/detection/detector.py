from flask import Blueprint, render_template, request, redirect, url_for, flash, Response, jsonify
from app.models import Camera, Model, Detector
from app.forms import DetectorForm
import cv2
from datetime import datetime
import pytz
import logging
import time
from app.utils.detector import annotated_frames, detector_fps_info
from app.utils.webrtc import init_webrtc_manager
from aiortc import RTCPeerConnection, RTCSessionDescription
from aiortc.contrib.signaling import TcpSocketSignaling
import asyncio

logger = logging.getLogger(__name__)
detector = Blueprint('detector', __name__, url_prefix="/detector")
wib = pytz.timezone('Asia/Jakarta')

@detector.route('/main', methods=['GET', 'POST'])
def main_detector():
    form = DetectorForm()
    cameras = Camera.query.all()
    models = Model.query.all()
    form.camera_id.choices = [(camera.id, camera.location) for camera in cameras]
    form.model_id.choices = [(model.id, model.model_name) for model in models]
    
    # Sort detectors by camera.id in ascending order
    detectors = Detector.query.join(Camera).order_by(Camera.id.asc()).all()
    
    if form.validate_on_submit():
        from app import db
        new_detector = Detector(
            camera_id=form.camera_id.data,
            model_id=form.model_id.data,
            running=form.running.data,
            created_at=datetime.now(wib),
            updated_at=datetime.now(wib)
        )
        try:
            db.session.add(new_detector)
            db.session.commit()
            logger.info(f"Detector added: ID={new_detector.id}, Camera ID={new_detector.camera_id}")
            flash('Detector added successfully!', 'success')
            from app import detector_manager
            detector_manager.update_detectors()
        except Exception as e:
            db.session.rollback()
            flash(f'Error adding detector: {str(e)}', 'danger')
        return redirect(url_for('detector.main_detector'))
    
    return render_template('detection/detector.html', form=form, cameras=cameras, models=models, detectors=detectors)

@detector.route('/edit_detector/<int:id>', methods=['GET', 'POST'])
def edit_detector(id):
    detector_obj = Detector.query.get_or_404(id)
    form = DetectorForm()
    cameras = Camera.query.all()
    models = Model.query.all()
    form.camera_id.choices = [(camera.id, camera.location) for camera in cameras]
    form.model_id.choices = [(model.id, model.model_name) for model in models]
    
    if request.method == 'POST':
        if form.validate_on_submit():
            detector_obj.camera_id = form.camera_id.data
            detector_obj.model_id = form.model_id.data
            detector_obj.running = form.running.data
            detector_obj.updated_at = datetime.now(wib)
            
            try:
                from app import db
                db.session.commit()
                logger.info(f"Detector updated: ID={id}, Running={detector_obj.running}")
                flash('Detector updated successfully!', 'success')
                from app import detector_manager
                detector_manager.update_detectors()
                return redirect(url_for('detector.main_detector'))
            except Exception as e:
                db.session.rollback()
                flash(f'Error updating detector: {str(e)}', 'danger')
                return redirect(url_for('detector.main_detector'))
        else:
            flash('Please fill in all required fields.', 'danger')
    
    form.camera_id.data = detector_obj.camera_id
    form.model_id.data = detector_obj.model_id
    form.running.data = detector_obj.running
    
    return render_template('detector/edit_detector.html', form=form, detector=detector_obj)

@detector.route('/view_detector/<int:id>', methods=['GET'])
def view_detector(id):
    detector_obj = Detector.query.get_or_404(id)
    camera = Camera.query.get(detector_obj.camera_id)
    model = Model.query.get(detector_obj.model_id)
    tracking = request.args.get('tracking', 'false').lower() == 'true'

    if not detector_obj.running:
        flash('Detector is not active. Please turn it on first.', 'warning')
        return redirect(url_for('detector.main_detector'))

    if not camera or not camera.status:
        flash('Camera is not active. Please turn it on first.', 'warning')
        return redirect(url_for('detector.main_detector'))

    if not model or not model.model_file:
        flash('Model file is missing. Please upload the model file again.', 'danger')
        return redirect(url_for('detector.main_detector'))
    
    return render_template('detection/view_detector.html', 
                           detector=detector_obj, 
                           tracking=tracking,
                           webrtc_enabled=True)

@detector.route('/fps_info/<int:id>')
def get_fps_info(id):
    fps_info = detector_fps_info.get(id, {
        'fps': 0.0,
        'inference_time': 0.0,
        'detections': 0,
        'last_update': 0
    })
    
    # Check if data is stale (older than 5 seconds)
    current_time = time.time()
    if current_time - fps_info.get('last_update', 0) > 5:
        fps_info = {
            'fps': 0.0,
            'inference_time': 0.0,
            'detections': 0,
            'last_update': current_time
        }
    
    return jsonify(fps_info)

@detector.route('/webrtc_offer/<int:id>', methods=['POST'])
def webrtc_offer(id):
    try:
        params = request.json
        if not params or 'sdp' not in params or 'type' not in params:
            return jsonify({"error": "Invalid request"}), 400
            
        # Create low-latency SDP
        sdp = params["sdp"]
        sdp = sdp.replace("a=mid:0", "a=mid:0\r\na=x-google-flag:conference")
        sdp = sdp.replace("useinbandfec=1", "useinbandfec=1; stereo=1; maxaveragebitrate=510000")
        sdp += "a=rtcp-fb:100 nack\r\n"
        sdp += "a=rtcp-fb:100 nack pli\r\n"
        sdp += "a=rtcp-fb:100 goog-remb\r\n"
        sdp += "a=rtcp-fb:100 transport-cc\r\n"
        sdp += "a=min-latency:0\r\n"
        sdp += "a=max-latency:100\r\n"
        
        # Add detector ID to SDP for identification
        sdp += f"a=detector_id:{id}\r\n"
        
        offer = RTCSessionDescription(sdp=sdp, type=params["type"])
        
        # Connect to signaling server
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            signaling = TcpSocketSignaling('127.0.0.1', 9999)
            loop.run_until_complete(signaling.connect())
            loop.run_until_complete(signaling.send(offer))
            logger.info(f"Sent offer for detector {id}")
            
            # Wait for answer
            answer = loop.run_until_complete(asyncio.wait_for(signaling.receive(), timeout=5.0))
            if not isinstance(answer, RTCSessionDescription):
                raise Exception("Invalid answer received")
                
            return jsonify({
                "sdp": answer.sdp,
                "type": answer.type
            })
        except asyncio.TimeoutError:
            logger.error("Signaling timeout")
            return jsonify({"error": "Signaling timeout"}), 500
        except Exception as e:
            logger.error(f"WebRTC offer error: {e}", exc_info=True)
            return jsonify({"error": "Internal server error"}), 500
        finally:
            loop.run_until_complete(signaling.close())
            loop.close()
    except Exception as e:
        logger.error(f"WebRTC offer error: {e}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500

@detector.route('/stream_detector/<int:id>')
def stream_detector(id):
    from flask import current_app
    from app import detector_manager

    tracking = request.args.get('tracking', 'false').lower() == 'true'
    
    detector_obj = Detector.query.get(id)
    if not detector_obj or not detector_obj.running:
        logger.warning(f"Attempted to stream inactive or non-existent detector {id}")
        return "Detector is off or does not exist", 400
    
    detector_manager.update_detectors(tracking_status={id: tracking})
    
    def generate_frames(detector_id, app):
        frame_count = 0
        max_empty_frames = 150  # ~5 seconds at 30fps
        empty_frame_count = 0
        last_check_time = time.time()
        
        logger.info(f"Starting detector frame generation for detector {detector_id}")
        
        while True:
            try:
                current_time = time.time()
                
                if current_time - last_check_time >= 1.0:
                    with app.app_context():
                        current_detector = Detector.query.get(detector_id)
                        if not current_detector or not current_detector.running:
                            logger.info(f"Detector {detector_id} became inactive during streaming")
                            break
                        
                        current_camera = Camera.query.get(current_detector.camera_id)
                        if not current_camera or not current_camera.status:
                            logger.info(f"Camera for detector {detector_id} became inactive during streaming")
                            break
                    
                    last_check_time = current_time
                
                frame = annotated_frames.get(detector_id)
                if frame is not None:
                    empty_frame_count = 0
                    
                    # Add client-side timestamp
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
                    cv2.putText(
                        frame, 
                        f"C: {timestamp}", 
                        (10, frame.shape[0] - 30), 
                        cv2.FONT_HERSHEY_SIMPLEX, 
                        0.8, 
                        (0, 255, 0), 
                        2, 
                        cv2.LINE_AA
                    )
                    
                    encode_params = [cv2.IMWRITE_JPEG_QUALITY, 85]
                    ret, buffer = cv2.imencode('.jpg', frame, encode_params)
                    
                    if ret:
                        yield (b'--frame\r\n'
                               b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
                        frame_count += 1
                    else:
                        logger.warning(f"Failed to encode frame for detector {detector_id}")
                else:
                    empty_frame_count += 1
                    if empty_frame_count >= max_empty_frames:
                        logger.warning(f"No annotated frames available for detector {detector_id} for too long, stopping stream")
                        break
                    time.sleep(0.033)
                
            except GeneratorExit:
                logger.info(f"Client disconnected from detector {detector_id} stream")
                break
            except Exception as e:
                logger.error(f"Error in frame generation for detector {detector_id}: {e}")
                break
        
        logger.info(f"Detector frame generation stopped for detector {detector_id}. Total frames: {frame_count}")
    
    return Response(
        generate_frames(id, current_app._get_current_object()),
        mimetype='multipart/x-mixed-replace; boundary=frame',
        headers={
            'Cache-Control': 'no-cache, no-store, must-revalidate',
            'Pragma': 'no-cache',
            'Expires': '0'
        }
    )

@detector.route('/delete_detector/<int:id>', methods=['POST'])
def delete_detector(id):
    detector_obj = Detector.query.get_or_404(id)
    from app import db
    db.session.delete(detector_obj)
    db.session.commit()
    logger.info(f"Detector deleted: ID={id}")
    flash('Detector deleted successfully!', 'success')
    from app import detector_manager
    detector_manager.update_detectors()
    return redirect(url_for('detector.main_detector'))

@detector.route('/delete_all_detectors', methods=['POST'])
def delete_all_detectors():
    from app import db
    Detector.query.delete()
    db.session.commit()
    logger.info("All detectors deleted")
    flash('All detectors deleted successfully!', 'success')
    from app import detector_manager
    detector_manager.update_detectors()
    return redirect(url_for('detector.main_detector'))