from flask import Blueprint, render_template, request, redirect, url_for, flash
from app.models import db, Model
from app.forms import ModelForm
from datetime import datetime 
import pytz
from flask import jsonify
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

model = Blueprint('model', __name__, url_prefix='/model')

wib = pytz.timezone('Asia/Jakarta')

ALLOWED_MODEL_EXTENSIONS = {'pt'}  

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_MODEL_EXTENSIONS

@model.route('/setting', methods=['GET', 'POST'])
def setting_model():
    form = ModelForm()
    if form.validate_on_submit():
        file = form.model_file.data
        original_filename = file.filename
        
        if file and allowed_file(file.filename):
            file_data = file.read()
            now = datetime.now(wib)

            new_model = Model(
                model_name=form.model_name.data,
                model_file=file_data, 
                original_filename=original_filename,  
                created_at=now,      
                updated_at=now      
            )

            db.session.add(new_model)
            db.session.commit()
            flash('Model added successfully!', 'success')
            return redirect(url_for('model.setting_model'))
        else:
            flash('Invalid file format! Please upload a .pt file.', 'danger')

    models = Model.query.all()
    return render_template('detection/model.html', form=form, models=models)

@model.route('/delete_model/<int:id>', methods=['POST'])
def delete_model(id):
    model = Model.query.get_or_404(id)
    db.session.delete(model)
    db.session.commit()
    flash('Model deleted successfully!', 'success')
    return redirect(url_for('model.setting_model'))

@model.route('/delete_all_models', methods=['POST'])
def delete_all_models():
    Model.query.delete()
    db.session.commit()
    flash('All models deleted successfully!', 'success')
    return redirect(url_for('model.setting_model'))


@model.route('/edit_model/<int:id>', methods=['GET','POST'])
def edit_model(id):
    model = Model.query.get_or_404(id)
    form = ModelForm()
    
    if request.method == 'GET':
        return jsonify({'model_name': model.model_name})
    
    if form.validate_on_submit():
        model.model_name = form.model_name.data

        if form.model_file.data:
            file = form.model_file.data
            if allowed_file(file.filename):
                model.model_file = file.read()  
                model.original_filename = file.filename 

        model.updated_at = datetime.now(wib)

        db.session.commit()
        flash('Model updated successfully!', 'success')
        return redirect(url_for('model.setting_model'))
    else:
        flash('Failed to update the model. Please check the form and try again.', 'danger')

    return redirect(url_for('model.setting_model'))
