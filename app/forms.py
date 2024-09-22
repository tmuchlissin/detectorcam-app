from flask_wtf import FlaskForm
from wtforms import StringField, SelectField, BooleanField, SubmitField
from wtforms.validators import DataRequired, ValidationError
import re

class CameraForm(FlaskForm):
    location = StringField('Location', validators=[DataRequired()])
    ip_address = StringField('IP Address', validators=[DataRequired()])
    status = BooleanField('Status (On/Off)', default=False)

    # Dropdown for camera type
    type = SelectField(
        'Camera Type', 
        choices=[('Parking Area', 'Parking Area'), ('Main Room', 'Main Room'), ('Entrance', 'Entrance'), ('Droid Cam','Droid Cam')],
        validators=[DataRequired()]
    )

    def validate_ip_address(form, field):
        ip_pattern = r"^http:\/\/(?:\d{1,3}\.){3}\d{1,3}(?::\d{1,5})?(?:\/video)?$"
        
        # Validasi apakah format IP Address sesuai dengan pola
        if not re.match(ip_pattern, field.data):
            raise ValidationError(
                'IP Address must follow the format: "http://xxx.xxx.xxx.xxx[:port]/video". Example: http://192.168.1.106:4747/video.'
            )

        # Validasi apakah setiap segmen IP berada di antara 0-255
        ip_portion = field.data.split('//')[1].split('/')[0]  # Ambil bagian sebelum "/video"
        ip_only = ip_portion.split(':')[0]  # Ambil hanya IP tanpa port

        segments = ip_only.split('.')
        if len(segments) != 4 or any(not segment.isdigit() or not (0 <= int(segment) <= 255) for segment in segments):
            raise ValidationError('Invalid IP Address format. IP segments should be between 0 and 255.')

    submit = SubmitField('Add Camera')
