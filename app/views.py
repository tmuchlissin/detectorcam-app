from flask import Blueprint, render_template

main = Blueprint('main', __name__)

@main.route('/')
def index():
    cards = [
        {"title": "CCTV Count", "content": "Isi dari Card 1", "bg_color": "blue-500", "icon": "fas fa-video"},
        {"title": "Detector Count", "content": "Isi dari Card 2", "bg_color": "green-500", "icon": "fas fa-tachometer-alt"},
        {"title": "No PPE Detected", "content": "Isi dari Card 3", "bg_color": "teal-500", "icon": "fas fa-user-shield"},
        {"title": "Reckless Driver", "content": "Isi dari Card 4", "bg_color": "yellow-500", "icon": "fas fa-car-crash"},
        {"title": "SOS Detected", "content": "Isi dari Card 5", "bg_color": "purple-500", "icon": "fas fa-exclamation-triangle"},
        {"title": "Fire Detected", "content": "Isi dari Card 6", "bg_color": "emerald-500", "icon": "fas fa-fire"}
    ]
    return render_template('index.html', cards=cards)
