from flask import Blueprint, render_template

detection = Blueprint('detection', __name__)

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