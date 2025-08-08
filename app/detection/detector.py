from flask import Blueprint, render_template, request, redirect, url_for, flash, Response
from app.models import Camera, Model, Detector
from app.forms import DetectorForm
import cv2
from datetime import datetime
import pytz
import logging
import time
from app.utils.detector import annotated_frames  # Fixed import path

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
    detectors = Detector.query.all()

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
    detector = Detector.query.get_or_404(id)
    form = DetectorForm()
    cameras = Camera.query.all()
    models = Model.query.all()
    form.camera_id.choices = [(camera.id, camera.location) for camera in cameras]
    form.model_id.choices = [(model.id, model.model_name) for model in models]

    if request.method == 'POST':
        if form.validate_on_submit():
            detector.camera_id = form.camera_id.data
            detector.model_id = form.model_id.data
            detector.running = form.running.data
            detector.updated_at = datetime.now(wib)
            try:
                from app import db
                db.session.commit()
                logger.info(f"Detector updated: ID={id}, Running={detector.running}")
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

    form.camera_id.data = detector.camera_id
    form.model_id.data = detector.model_id
    form.running.data = detector.running
    return render_template('detector/edit_detector.html', form=form, detector=detector)

@detector.route('/view_detector/<int:id>', methods=['GET'])
def view_detector(id):
    """
    Menampilkan halaman view untuk satu detector.
    Halaman HTML akan memanggil route 'stream_detector' untuk menampilkan video.
    """
    detector_obj = Detector.query.get_or_404(id)
    camera = Camera.query.get(detector_obj.camera_id)
    model = Model.query.get(detector_obj.model_id)

    # Memeriksa apakah detektor dan kamera aktif
    if not detector_obj.running:
        flash('Detector is not active. Please turn it on first.', 'warning')
        return redirect(url_for('detector.main_detector'))
    
    if not camera or not camera.status:
        flash('Camera is not active. Please turn it on first.', 'warning')
        return redirect(url_for('detector.main_detector'))
    
    # Memeriksa apakah file model ada
    if not model or not model.model_file:
        flash('Model file is missing. Please upload the model file again.', 'danger')
        return redirect(url_for('detector.main_detector'))

    return render_template('detection/view_detector.html', detector=detector_obj)

@detector.route('/stream_detector/<int:id>')
def stream_detector(id):
    """
    Route ini khusus untuk streaming video dari detector yang sudah diproses.
    """
    from flask import current_app
    
    # Pemeriksaan awal untuk memastikan detektor ada dan berjalan
    detector_obj = Detector.query.get(id)
    if not detector_obj or not detector_obj.running:
        logger.warning(f"Attempted to stream inactive or non-existent detector {id}")
        return "Detector is off or does not exist", 400

    def generate_frames(detector_id, app):
        """Generator function for streaming frames with YOLO detection"""
        frame_count = 0
        max_empty_frames = 150  # ~5 detik pada 30fps
        empty_frame_count = 0
        last_check_time = time.time()
        
        logger.info(f"Starting frame generation for detector {detector_id}")
        
        while True:
            try:
                current_time = time.time()
                
                # Periksa status detektor setiap detik
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
                
                # Cek apakah frame yang sudah dianotasi tersedia
                frame = annotated_frames.get(detector_id)
                if frame is not None:
                    empty_frame_count = 0  # Reset counter
                    
                    # Encode frame sebagai JPEG
                    encode_params = [cv2.IMWRITE_JPEG_QUALITY, 85]
                    ret, buffer = cv2.imencode('.jpg', frame, encode_params)
                    
                    if ret:
                        # Yield frame dalam format multipart
                        yield (b'--frame\r\n'
                               b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
                        frame_count += 1
                    else:
                        logger.warning(f"Failed to encode frame for detector {detector_id}")
                else:
                    # Jika frame tidak tersedia, tunggu sebentar
                    empty_frame_count += 1
                    if empty_frame_count >= max_empty_frames:
                        logger.warning(f"No annotated frames available for detector {detector_id} for too long, stopping stream")
                        break
                    time.sleep(0.033)  # Tunggu frame berikutnya
                
            except GeneratorExit:
                logger.info(f"Client disconnected from detector {detector_id} stream")
                break
            except Exception as e:
                logger.error(f"Error in frame generation for detector {detector_id}: {e}")
                break
        
        logger.info(f"Frame generation stopped for detector {detector_id}. Total frames: {frame_count}")

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
    detector = Detector.query.get_or_404(id)
    from app import db
    db.session.delete(detector)
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