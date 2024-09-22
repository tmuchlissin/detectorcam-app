from io import BytesIO
from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file, current_app
from app.extensions import db
from app.models import Document
from werkzeug.utils import secure_filename
import os
from datetime import datetime 

chatbot = Blueprint('chatbot', __name__)

# Fungsi untuk memeriksa apakah file ekstensi diperbolehkan
ALLOWED_EXTENSIONS = {
    'txt', 'pdf', 'png', 'jpg', 'jpeg',
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
        'txt': 'text/plain',
        # Tambahkan MIME types lain sesuai kebutuhan
    }
    return mime_types.get(ext, 'application/octet-stream')  # Default untuk unknown


@chatbot.route('/chatbot/documents', methods=['GET', 'POST'])
def documents():
    if request.method == 'POST':
        # Ambil semua file yang diunggah
        files = request.files.getlist('files[]')
        
        if not files or not all(allowed_file(file.filename) for file in files):
            flash('Some files are not allowed or no file uploaded!', 'error')
            return redirect(url_for('chatbot.documents'))
        
        # Loop untuk memproses setiap file
        for file in files:
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                file_data = file.read()
                
                # Simpan data ke database untuk setiap file
                new_document = Document(title_file=filename, file_data=file_data)
                db.session.add(new_document)
        
        db.session.commit()
        flash('Folder and files uploaded successfully!', 'success')
        return redirect(url_for('chatbot.documents'))

    # Ambil nomor halaman dari query string, default ke halaman 1
    page = request.args.get('page', 1, type=int)
    per_page = 10  # Jumlah dokumen per halaman

    # Pencarian dokumen berdasarkan judul file
    search_query = request.args.get('search', '')

    if search_query:
        # Jika ada query pencarian, filter dokumen berdasarkan judul
        documents = Document.query.filter(Document.title_file.ilike(f'%{search_query}%')).paginate(page=page, per_page=per_page)
    else:
        # Jika tidak ada query, tampilkan semua dokumen dengan pagination
        documents = Document.query.paginate(page=page, per_page=per_page)

    return render_template('chatbot/documents.html', navbar_title='Chatbot/Documents', documents=documents, search_query=search_query)


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
    
    return render_template('chatbot/view_document.html', navbar_title='Chatbot/Documents/View',
                        document=document, 
                        mime_type=mime_type,
                        preview_url=preview_url)

@chatbot.route('/chatbot/documents/update/<int:file_id>', methods=['POST'])
def update_file(file_id):
    document = Document.query.get_or_404(file_id)
    
    # Ambil file baru
    new_file = request.files.get('new_file')

    if new_file and allowed_file(new_file.filename):
        filename = secure_filename(new_file.filename)
        file_data = new_file.read()

        # Update dokumen dengan file baru
        document.title_file = filename
        document.file_data = file_data
        document.updated_at = datetime.utcnow()

        db.session.commit()

        flash('Document updated successfully!', 'success')
    else:
        flash('File not allowed or no file selected!', 'error')

    return redirect(url_for('chatbot.documents'))



@chatbot.route('/chatbot/documents/download/<int:file_id>')
def download_file(file_id):
    document = Document.query.get_or_404(file_id)
    if document.file_data:
        return send_file(BytesIO(document.file_data), 
                        download_name=document.title_file, 
                        as_attachment=True) 
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

@chatbot.route('/chatbot/delete_all_documents', methods=['POST'])
def delete_all_documents():
    try:
        # Menghapus semua dokumen
        Document.query.delete()
        db.session.commit()
        flash('All documents have been deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()  # Jika ada error, batalkan perubahan
        flash(f'Error deleting documents: {str(e)}', 'error')
    
    return redirect(url_for('chatbot.documents'))


@chatbot.route('/chatbot/live-chat')
def live_chat():
    return render_template('chatbot/live_chat.html', navbar_title='Chatbot/Live Chat')
