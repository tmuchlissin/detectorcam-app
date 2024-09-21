from flask import Flask
from app.views import main
from app.detection.views import detection
from app.chatbot.views import chatbot
from app.error_pages.handlers import error_pages
from app.extensions import db, migrate,  csrf
from config import Config
import os

def create_app():
    app = Flask(__name__)
    
    # Load configuration from config.py
    app.config.from_object(Config)
    
       # Konfigurasi Upload Folder
    app.config['UPLOAD_FOLDER'] = os.path.join(os.getcwd(), 'uploads')
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # Maksimal 16MB

    # Pastikan direktori ada
    if not os.path.exists(app.config['UPLOAD_FOLDER']):
        os.makedirs(app.config['UPLOAD_FOLDER'])
    # Initialize the database and migrate
    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    # Register blueprints
    app.register_blueprint(main)
    app.register_blueprint(detection)
    app.register_blueprint(chatbot)
    app.register_blueprint(error_pages)
    
    return app
