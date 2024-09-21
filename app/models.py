from app.extensions import db 
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from datetime import datetime

class Document(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title_file = db.Column(db.String(255), nullable=False)  # This should match the column in your database
    file_data = db.Column(db.LargeBinary, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<Document {self.title}>'
    
    
