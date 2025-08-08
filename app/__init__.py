from flask import Flask
from app.views import main
from app.detection.cctv import cctv
from app.detection.detector import detector
from app.detection.model import model
from app.extensions import db, migrate, csrf
from app.utils.detector import DetectorManager
import os
import signal

def handle_shutdown_signal(signal, frame):
    print("Shutting down detector manager...")
    detector_manager.stop_all()
    print("Detector manager stopped.")
    os._exit(0)

def create_app():
    app = Flask(__name__)
    app.config.from_object('config.Config')
    app.config['WTF_CSRF_ENABLED'] = False

    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)

    # Register blueprints
    app.register_blueprint(main)
    app.register_blueprint(cctv)
    app.register_blueprint(detector)
    app.register_blueprint(model)

    # Initialize DetectorManager
    global detector_manager
    detector_manager = DetectorManager()
    with app.app_context():
        detector_manager.initialize_detectors(app)

    # Handle shutdown signals
    signal.signal(signal.SIGINT, handle_shutdown_signal)
    signal.signal(signal.SIGTERM, handle_shutdown_signal)

    return app