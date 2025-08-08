from app.extensions import db
from datetime import datetime


class Camera(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    location = db.Column(db.String(100), nullable=False)
    ip_address = db.Column(db.String(100), nullable=False)
    status = db.Column(db.Boolean, default=False)
    type = db.Column(db.String(50), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<Camera {self.location}>'


class Model(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    model_name = db.Column(db.String(120), index=True)
    original_filename = db.Column(db.String(120)) 
    model_file = db.Column(db.LargeBinary)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<Model {self.model_name}>'


class Detector(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    camera_id = db.Column(db.Integer, db.ForeignKey('camera.id'), nullable=False) 
    model_id = db.Column(db.Integer, db.ForeignKey('model.id'), nullable=False) 
    running = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, onupdate=datetime.utcnow)

    camera = db.relationship('Camera', backref='detectors')  
    model = db.relationship('Model', backref='detectors')  

    def __repr__(self):
        return f'<Detector CCTV ID {self.camera_id}, model ID {self.model_id}>'


class ObjectDetected(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    detector_id = db.Column(db.Integer, db.ForeignKey('detector.id'), nullable=False)  
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, onupdate=datetime.utcnow)
    
    detector = db.relationship('Detector', backref='objects_detected')  

    def __repr__(self):
        return f'<ObjectDetected Detector ID {self.detector_id}>'
