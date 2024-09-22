from app.extensions import db 
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from datetime import datetime

class Document(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title_file = db.Column(db.String(255), nullable=False)
    file_data = db.Column(db.LargeBinary, nullable=False)  # Ubah ini jika belum
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<Document {self.title_file}>'


class Camera(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    location = db.Column(db.String(100), nullable=False)
    ip_address = db.Column(db.String(100), nullable=False)
    status = db.Column(db.Boolean, default=False)
    type = db.Column(db.String(50), nullable=False)  # e.g., 'Parking', 'Main Room', etc.
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<Camera {self.location}>'
