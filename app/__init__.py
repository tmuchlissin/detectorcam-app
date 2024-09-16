from flask import Flask
from app.views import main
from app.detection.views import detection
from app.chatbot.views import chatbot
from app.extensions import db, migrate
from config import Config

def create_app():
    app = Flask(__name__)
    
    # Load configuration from config.py
    app.config.from_object(Config)
    
    # Initialize the database and migrate
    db.init_app(app)
    migrate.init_app(app, db)
    
    # Register blueprints
    app.register_blueprint(main)
    app.register_blueprint(detection)
    app.register_blueprint(chatbot)
    
    return app
