from flask_wtf import FlaskForm
from wtforms import StringField, SelectField, BooleanField, SubmitField
from flask_wtf.file import FileField, FileAllowed
from wtforms.validators import DataRequired, ValidationError
import re

from flask_wtf import FlaskForm
from wtforms import StringField, BooleanField, SelectField, SubmitField
from wtforms.validators import DataRequired, ValidationError
import re

from flask_wtf import FlaskForm
from wtforms import StringField, BooleanField, SelectField, SubmitField
from wtforms.validators import DataRequired, ValidationError
import re

class CameraForm(FlaskForm):
    location = StringField('Location', validators=[DataRequired()])
    ip_address = StringField('IP Address/Stream URL', validators=[DataRequired()])
    status = BooleanField('Status (On/Off)', default=False)
    type = SelectField(
        'CCTV Type',
        choices=[('Parking Area', 'Parking Area'), ('Main Room', 'Main Room'), ('Entrance', 'Entrance'), ('Droid Cam', 'Droid Cam')],
        validators=[DataRequired()]
    )

    def validate_ip_address(form, field):
        http_pattern = r"^http:\/\/(?:(?:\d{1,3}\.){3}\d{1,3}|[\w\-\.]+)(?::\d{1,5})?(?:\/video)?$"
        
        rtsp_pattern = r"^rtsp:\/\/(?:[\w]+:[\w]+@)?(?:(?:\d{1,3}\.){3}\d{1,3}|[\w\-\.]+)(?::\d{1,5})?(?:\/[\w\/\-\.]+)?(?:\?[\w=&\-]+)?$"
        
        if re.match(http_pattern, field.data):
            url_without_protocol = field.data.split('//')[1]
            host_portion = url_without_protocol.split('/')[0]
            host_only = host_portion.split(':')[0]
            
            if re.match(r"^(?:\d{1,3}\.){3}\d{1,3}$", host_only):
                segments = host_only.split('.')
                if any(not segment.isdigit() or not (0 <= int(segment) <= 255) for segment in segments):
                    raise ValidationError('Invalid IP Address format. IP segments should be between 0 and 255.')
    
        elif re.match(rtsp_pattern, field.data):
            url_without_protocol = field.data.split('//')[1]

            if '@' in url_without_protocol:
                host_portion = url_without_protocol.split('@')[1]
            else:
                host_portion = url_without_protocol
            
            host_only = host_portion.split(':')[0].split('/')[0]

            if re.match(r"^(?:\d{1,3}\.){3}\d{1,3}$", host_only):
                segments = host_only.split('.')
                if any(not segment.isdigit() or not (0 <= int(segment) <= 255) for segment in segments):
                    raise ValidationError('Invalid IP Address format. IP segments should be between 0 and 255.')
        
        else:
            raise ValidationError(
                'Stream URL must follow HTTP or RTSP format:\n'
                'HTTP: "http://host[:port]/video" (e.g., http://192.168.1.106:4747/video, http://localhost:8080/video)\n'
                'RTSP: "rtsp://[username:password@]host[:port][/path][?params]" '
                '(e.g., rtsp://localhost:8554/mystream/test, rtsp://192.168.1.111/MediaInput/h264)'
            )

    submit = SubmitField('Add CCTV')

class ModelForm(FlaskForm):
    model_name = StringField('Model Name', validators=[DataRequired()])
    model_file = FileField('Model File', validators=[
        FileAllowed(['pt'], 'Invalid file format!')
    ])
    submit = SubmitField('Add Model')

class DetectorForm(FlaskForm):
    camera_id = SelectField('Camera', choices=[], validators=[DataRequired()], coerce=int)
    model_id = SelectField('Model', choices=[], validators=[DataRequired()], coerce=int)
    running = BooleanField('Running', default=False)
    submit = SubmitField('Add Detector')