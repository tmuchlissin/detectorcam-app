from flask import Blueprint, render_template, request, redirect, url_for, flash, Response
from app.models import db, Camera
from app.forms import CameraForm
import cv2

detection = Blueprint('detection', __name__)

@detection.route('/detection/object-detector/cctv', methods=['GET', 'POST'])
def cctv():
    form = CameraForm()
    if form.validate_on_submit():
        camera = Camera(
            location=form.location.data,
            ip_address=form.ip_address.data,
            status=False,  # Default status is set to False
            type=form.type.data
        )
        db.session.add(camera)
        db.session.commit()
        flash('Camera added successfully!', 'success')
        return redirect(url_for('detection.cctv'))

    cameras = Camera.query.all()
    return render_template('detection/cctv.html', form=form, cameras=cameras)

@detection.route('/detection/object-detector/cctv/edit/<int:id>', methods=['POST'])
def edit_camera(id):
    camera = Camera.query.get_or_404(id)
    camera.location = request.form['location']
    camera.ip_address = request.form['ip_address']
    camera.type = request.form['type']
    camera.status = True if request.form['status'] == 'true' else False

    try:
        db.session.commit()
        flash('Camera updated successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        print(f"Error: {e}")
        flash('Error updating camera. Please try again.', 'danger')

    return redirect(url_for('detection.cctv'))

@detection.route('/detection/object-detector/cctv/delete/<int:id>', methods=['POST'])
def delete_camera(id):
    camera = Camera.query.get_or_404(id)
    db.session.delete(camera)
    db.session.commit()
    flash('Camera deleted successfully!', 'success')
    return redirect(url_for('detection.cctv'))


@detection.route('/detection/object-detector/cctv/delete_all_cameras', methods=['POST'])
def delete_all_cameras():
    try:
        # Menghapus semua dokumen
        Camera.query.delete()
        db.session.commit()
        flash('All cameras have been deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()  # Jika ada error, batalkan perubahan
        flash(f'Error deleting cameras: {str(e)}', 'error')
    
    return redirect(url_for('detection.cctv'))

@detection.route('/detection/object-detector/cctv/view/<int:id>', methods=['GET'])
def view_camera(id):
    camera = Camera.query.get_or_404(id)

    def gen_frames():
        # Untuk contoh ini, "http://1.1.1.1" adalah URL kamera dummy, ganti sesuai kebutuhan
        address = 0 if camera.ip_address == "http://1.1.1.1" else camera.ip_address

        # Membuka video stream dengan URL DroidCam atau IP Kamera lainnya
        cap = cv2.VideoCapture(address)

        if not cap.isOpened():
            print(f"Error: Cannot open video stream from {address}")
            return
        
        print(f"Stream opened successfully from {address}")
        
        while True:
            success, frame = cap.read()
            if not success:
                print("Error: No frame received.")
                break
            
            ret, buffer = cv2.imencode('.jpg', frame)
            if ret:
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
            else:
                print("Error: Frame encoding failed.")

    # Jika kamera aktif, stream video
    if camera.status:
        return Response(gen_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')
    
    return "Kamera tidak aktif", 404



    
@detection.route('/detection/object-detector/report')
def report():
    return render_template('detection/report.html', navbar_title='Detection/Report')

@detection.route('/detection/object-detector/contact')
def contact():
    return render_template('detection/contact.html', navbar_title='Detection/Contact')

@detection.route('/detection/object-detector/ppe')
def ppe():
    return render_template('detection/ppe.html', navbar_title='Detection/Object Detector/PPE Detector')

@detection.route('/detection/object-detector/driver')
def driver():
    return render_template('detection/driver.html', navbar_title='Detection/Object Detector/Driver Detector')

@detection.route('/detection/object-detector/danger-condition')
def danger_condition():
    return render_template('detection/danger_condition.html', navbar_title='Detection/Object Detector/Danger Condition')

@detection.route('/detection/object-detector/fire')
def fire():
    return render_template('detection/fire.html', navbar_title='Detection/Object Detector/Fire')
