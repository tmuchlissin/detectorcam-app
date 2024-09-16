from flask import Blueprint, render_template

chatbot = Blueprint('chatbot', __name__)

@chatbot.route('/about')
def about():
    return render_template('about.html')


@chatbot.route('/chatbot/documents')
def documents():
    return render_template('chatbot/documents.html', navbar_title='Chatbot/Documents')

@chatbot.route('/chatbot/live-chat')
def live_chat():
    return render_template('chatbot/live_chat.html', navbar_title='Chatbot/Live Chat')