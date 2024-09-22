from flask import Blueprint, render_template

main = Blueprint('main', __name__)

@main.route('/')
def index():
    cards = [
        {"title": "CCTV Count", "content": "Isi dari Card 1", "bg_color": "blue-500"},
        {"title": "Detector Count", "content": "Isi dari Card 2", "bg_color": "green-500"},
        {"title": "No PPE Detected", "content": "Isi dari Card 3", "bg_color": "teal-500"},
        {"title": "Reckless Driver", "content": "Isi dari Card 4", "bg_color": "yellow-500"},
        {"title": "SOS Detected", "content": "Isi dari Card 5", "bg_color": "purple-500"},
        {"title": "Fire Detected", "content": "Isi dari Card 5", "bg_color": "emerald-500"}
    ]
    return render_template('index.html', navbar_title='Dashboard', cards=cards)
