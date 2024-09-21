from io import BytesIO
from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file, current_app
from app.extensions import db
from app.models import Document
from werkzeug.utils import secure_filename
import os

chatbot = Blueprint('chatbot', __name__)

# Fungsi untuk memeriksa apakah file ekstensi diperbolehkan
ALLOWED_EXTENSIONS = {
    'txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif',
    'docx', 'pptx', 'xlsx'  # Tambahkan ekstensi baru di sini
}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_mime_type(filename):
    ext = filename.rsplit('.', 1)[1].lower()
    mime_types = {
        'pdf': 'application/pdf',
        'jpg': 'image/jpeg',
        'jpeg': 'image/jpeg',
        'png': 'image/png',
        'gif': 'image/gif',
        'txt': 'text/plain',
        # Tambahkan MIME types lain sesuai kebutuhan
    }
    return mime_types.get(ext, 'application/octet-stream')  # Default untuk unknown


@chatbot.route('/chatbot/documents', methods=['GET', 'POST'])
def documents():
    if request.method == 'POST':
        file = request.files['file']
        
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file_data = file.read()

            # Simpan data ke database
            new_document = Document(title_file=filename, file_data=file_data)
            db.session.add(new_document)
            db.session.commit()

            flash('Document uploaded successfully!', 'success')
            return redirect(url_for('chatbot.documents'))

    # Fetch all documents from the database
    documents = Document.query.all()
    return render_template('chatbot/documents.html', documents=documents)

@chatbot.route('/chatbot/documents/preview/<int:file_id>')
def preview_file(file_id):
    document = Document.query.get_or_404(file_id)
    return send_file(BytesIO(document.file_data), 
                     download_name=document.title_file, 
                     as_attachment=False)  # Pratinjau file


@chatbot.route('/chatbot/documents/view/<int:file_id>')
def view_document(file_id):
    document = Document.query.get_or_404(file_id)
    mime_type = get_mime_type(document.title_file)

    # URL pratinjau untuk file PDF dan gambar
    preview_url = url_for('chatbot.preview_file', file_id=document.id)
    
    return render_template('chatbot/view_document.html', 
                           document=document, 
                           mime_type=mime_type,
                           preview_url=preview_url)

@chatbot.route('/chatbot/documents/download/<int:file_id>')
def download_file(file_id):
    document = Document.query.get_or_404(file_id)
    if document.file_data:
        return send_file(BytesIO(document.file_data), 
                         download_name=document.title_file, 
                         as_attachment=True)  # Memaksa unduhan
    else:
        flash("No file data found!", "error")
        return redirect(url_for('chatbot.documents'))



@chatbot.route('/chatbot/documents/delete/<int:file_id>', methods=['POST'])
def delete_document(file_id):
    document = Document.query.get_or_404(file_id)
    db.session.delete(document)
    db.session.commit()
    flash('Document deleted successfully!', 'success')
    return redirect(url_for('chatbot.documents'))


@chatbot.route('/chatbot/live-chat')
def live_chat():
    return render_template('chatbot/live_chat.html', navbar_title='Chatbot/Live Chat')
