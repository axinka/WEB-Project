from flask import Flask, request, render_template
import os

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'static/uploads'  # Папка для сохранения загруженных файлов

# Убедитесь, что папка существует
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

@app.route('/', methods=['GET', 'POST'])
def upload_file():
    if request.method == 'POST':
        if 'file' not in request.files:
            return 'No file part'
        file = request.files['file']
        if file.filename == '':
            return 'No selected file'
        if file:
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
            file.save(file_path)
            print("Файл успешно загружен и сохранен!")  # Сообщение в консоль при успешной загрузке
            return render_template('10052025.html', filename=file.filename)
    return render_template('10052025.html')

if __name__ == '__main__':
    app.run(debug=True)