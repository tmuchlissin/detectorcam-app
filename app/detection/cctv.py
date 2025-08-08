from flask import Blueprint, render_template, request, redirect, url_for, flash, Response
from app.models import Camera, Detector
from app.forms import CameraForm
import cv2
import logging
import time
from app.utils.detector import CameraStreamManager

logger = logging.getLogger(__name__)

cctv = Blueprint('cctv', __name__, url_prefix='/cctv')

# Initialize CameraStreamManager
camera_stream_manager = CameraStreamManager()

@cctv.route('/main', methods=['GET', 'POST'])
def main_cctv():
    form = CameraForm()
    if form.validate_on_submit():
        from app import db
        camera = Camera(
            location=form.location.data,
            ip_address=form.ip_address.data,
            status=form.status.data,
            type=form.type.data
        )
        db.session.add(camera)
        db.session.commit()
        logger.info(f"Camera added: {camera.location}, IP: {camera.ip_address}")
        flash('Camera added successfully!', 'success')
        return redirect(url_for('cctv.main_cctv'))

    cameras = Camera.query.all()
    return render_template('detection/cctv.html', form=form, cameras=cameras)

@cctv.route('/edit/<int:id>', methods=['POST'])
def edit_camera(id):
    camera = Camera.query.get_or_404(id)
    form = CameraForm()
    if form.validate_on_submit():
        camera.location = form.location.data
        camera.ip_address = form.ip_address.data
        camera.type = form.type.data
        old_status = camera.status
        camera.status = form.status.data
        try:
            from app import db
            db.session.commit()
            logger.info(f"Camera updated: ID={id}, Status={camera.status}")
            if not camera.status and old_status:
                camera_stream_manager.stop_inactive_streams()
            flash('Camera updated successfully!', 'success')
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error updating camera: {e}")
            flash('Error updating camera. Please try again.', 'danger')
    else:
        logger.debug(f"Form validation failed: {form.errors}")
        flash('Please fill in all required fields.', 'danger')
    return redirect(url_for('cctv.main_cctv'))

@cctv.route('/view/<int:id>', methods=['GET'])
def view_camera(id):
    camera = Camera.query.get_or_404(id)

    if not camera.status:
        flash('Camera is not active. Please turn on the camera first.', 'danger')
        return redirect(url_for('cctv.main_cctv'))

    return render_template('detection/view_cctv.html', camera=camera)

@cctv.route('/stream/<int:id>')
def stream_camera(id):
    from flask import current_app

    camera = Camera.query.get_or_404(id)

    if not camera.status:
        return "Camera is off", 400

    camera_stream_manager.cleanup_dead_streams()
    camera_stream = camera_stream_manager.get_camera_stream(camera.ip_address)

    if camera_stream is None:
        return "Stream not available", 500

    def generate_frames(camera_stream, app, camera_id):
        frame_count = 0
        max_empty_frames = 150
        empty_frame_count = 0

        # --- TAMBAHAN: Variabel untuk menghitung FPS ---
        fps = 0
        frame_counter_for_fps = 0
        start_time = time.time()
        # -----------------------------------------------

        while True:
            try:
                if frame_count % 30 == 0:
                    with app.app_context():
                        current_camera = Camera.query.get(camera_id)
                        if not current_camera or not current_camera.status:
                            logger.info(f"Camera {camera_id} became inactive during streaming")
                            break

                frame = camera_stream.get_frame()
                if frame is not None:
                    empty_frame_count = 0
                    
                    # --- MODIFIKASI: Logika untuk menghitung dan menggambar FPS di KANAN ATAS ---
                    frame_counter_for_fps += 1
                    if frame_counter_for_fps % 30 == 0:
                        end_time = time.time()
                        elapsed_time = end_time - start_time
                        fps = frame_counter_for_fps / elapsed_time
                        frame_counter_for_fps = 0
                        start_time = time.time()
                    
                    # Siapkan properti teks dan font
                    text = f"FPS: {fps:.2f}"
                    font = cv2.FONT_HERSHEY_SIMPLEX
                    font_scale = 0.7
                    font_thickness = 2
                    color = (0, 255, 0) # Warna Hijau

                    # Dapatkan ukuran teks untuk penempatan dinamis
                    (text_width, text_height), _ = cv2.getTextSize(text, font, font_scale, font_thickness)
                    
                    # Hitung posisi agar berada di pojok kanan atas
                    # Posisi X = Lebar Frame - Lebar Teks - Margin Kanan (10px)
                    # Posisi Y = Margin Atas (30px)
                    position = (frame.shape[1] - text_width - 10, 30)

                    # Tulis teks FPS di frame video
                    cv2.putText(frame, text, position, font, font_scale, color, font_thickness)
                    # -------------------------------------------------------------

                    ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                    if ret:
                        yield (b'--frame\r\n'
                               b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
                    else:
                        logger.warning(f"Failed to encode frame for camera {camera_id}")
                else:
                    # ... (logika empty frame tetap sama) ...
                    empty_frame_count += 1
                    if empty_frame_count >= max_empty_frames:
                        logger.warning(f"Too many empty frames for camera {camera_id}, stopping stream")
                        break

                frame_count += 1
                time.sleep(0.033)

            except GeneratorExit:
                logger.info(f"Client disconnected from camera {id} stream")
                break
            except Exception as e:
                logger.error(f"Error in frame generation for camera {id}: {e}")
                break

    return Response(
        generate_frames(camera_stream, current_app._get_current_object(), id),
        mimetype='multipart/x-mixed-replace; boundary=frame'
    )
    
@cctv.route('/delete/<int:id>', methods=['POST'])
def delete_camera(id):
    camera = Camera.query.get_or_404(id)
    if Detector.query.filter_by(camera_id=id).first():
        flash('Cannot delete camera. It is currently in use by a detector.', 'error')
        return redirect(url_for('cctv.main_cctv'))
    
    from app import db
    db.session.delete(camera)
    db.session.commit()
    camera_stream_manager.stop_inactive_streams()
    flash('Camera deleted successfully!', 'success')
    return redirect(url_for('cctv.main_cctv'))

@cctv.route('/delete_all_cameras', methods=['POST'])
def delete_all_cameras():
    try:
        from app import db
        if Detector.query.first():
            flash('Cannot delete all cameras. Some cameras are in use by detectors.', 'error')
        else:
            Camera.query.delete()
            db.session.commit()
            camera_stream_manager.stop_all()
            flash('All cameras have been deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting cameras: {str(e)}', 'error')
    return redirect(url_for('cctv.main_cctv'))