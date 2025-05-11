import uuid
from datetime import datetime

from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, send_from_directory
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
from geopy.geocoders import Nominatim
import os
import requests
from werkzeug.utils import secure_filename
from flask_wtf.csrf import CSRFProtect

MAX_AVATAR_SIZE = 2 * 1024 * 1024  # 2MB

app = Flask(__name__)
app.secret_key = 'd9a7b83c5f1e4a2b8c7d6e5f4a3b2c1d8e7f6a5b4c3d2e1f0a9b8c7d6e5f4'
csrf = CSRFProtect(app)

UPLOAD_FOLDER = 'static/uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

AVATARS_FOLDER = os.path.join(UPLOAD_FOLDER, 'avatars')
if not os.path.exists(AVATARS_FOLDER):
    os.makedirs(AVATARS_FOLDER)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS
# При инициализации БД
def init_db():
    conn = sqlite3.connect('movies.db')
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                 username TEXT UNIQUE NOT NULL,
                 email TEXT UNIQUE NOT NULL,
                 password_hash TEXT NOT NULL,
                 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                 last_login TIMESTAMP,
                 avatar TEXT)''')

    # Таблица для избранных фильмов
    c.execute('''CREATE TABLE IF NOT EXISTS favorites
                 (user_id INTEGER,
                 movie_id INTEGER,
                 added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                 FOREIGN KEY(user_id) REFERENCES users(id),
                 FOREIGN KEY(movie_id) REFERENCES movies(id),
                 PRIMARY KEY(user_id, movie_id))''')

    c.execute('''CREATE TABLE IF NOT EXISTS watched_movies
                     (user_id INTEGER,
                     movie_id INTEGER,
                     watched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                     FOREIGN KEY(user_id) REFERENCES users(id),
                     FOREIGN KEY(movie_id) REFERENCES movies(id),
                     PRIMARY KEY(user_id, movie_id))''')

    conn.commit()
    conn.close()

# Функция для получения списка фильмов
def get_movies():
    conn = sqlite3.connect('movies.db')
    cur = conn.cursor()
    movies = cur.execute("SELECT * FROM movies").fetchall()
    conn.close()

    movies_dict = {}
    for movie in movies:
        if movie[1]:
            short_name = movie[1] if len(movie[1]) < 34 else movie[1][:31] + '...'
            movies_dict[movie[1]] = {
                'id': movie[0],
                'name': movie[1],
                'sh_name': short_name,
                'genre': movie[2],
                'description': movie[3],
                'year': movie[4],
                'country': movie[5],
                'rating': movie[6] or 0.0,
                'picture': movie[7],
                'actors': movie[8]
            }
    return movies_dict


# Функция для получения карты страны
def get_country_map(country):
    try:
        geolocator = Nominatim(user_agent="film_app")
        location = geolocator.geocode(country)
        if not location:
            return None

        params = {
            "ll": f"{location.longitude},{location.latitude}",
            "z": 4,
            "size": "600,400",
            "pt": f"{location.longitude},{location.latitude},pm2rdm",
            "apikey": "f3a0fe3a-b07e-4840-a1da-06f18b2ddf13"  # Получите на developer.tech.yandex.ru
        }

        response = requests.get("https://static-maps.yandex.ru/v1?", params=params)
        if response.status_code == 200:
            filename = f"map_{country.replace(' ', '_')}.png"
            path = os.path.join(UPLOAD_FOLDER, filename)
            with open(path, 'wb') as f:
                f.write(response.content)
            return filename
    except Exception as e:
        print(f"Ошибка при получении карты: {e}")
    return None





# Добавление фильма в просмотренные
def add_watched_movie(user_id, movie_id):
    conn = sqlite3.connect('movies.db')
    try:
        cur = conn.cursor()
        cur.execute("INSERT OR IGNORE INTO watched_movies (user_id, movie_id) VALUES (?, ?)",
                    (user_id, movie_id))
        conn.commit()
        return True
    except sqlite3.Error as e:
        print(f"Ошибка при добавлении в просмотренные: {e}")
        return False
    finally:
        conn.close()


# Получение списка просмотренных фильмов
def get_watched_movies(user_id):
    conn = sqlite3.connect('movies.db')
    try:
        cur = conn.cursor()
        cur.execute('''SELECT m.id, m.name, m.picture 
                       FROM movies m
                       JOIN watched_movies wm ON m.id = wm.movie_id
                       WHERE wm.user_id = ?''', (user_id,))
        return cur.fetchall()
    except sqlite3.Error as e:
        print(f"Ошибка при получении просмотренных фильмов: {e}")
        return []
    finally:
        conn.close()

def get_average_rating(user_id):
    conn = sqlite3.connect('movies.db')
    try:
        cur = conn.cursor()
        cur.execute('''SELECT AVG(m.rating) 
                       FROM movies m
                       JOIN watched_movies w ON m.id = w.movie_id
                       WHERE w.user_id = ?''', (user_id,))
        return cur.fetchone()[0]
    finally:
        conn.close()

# Добавление/удаление из избранного
def toggle_favorite_movie(user_id, movie_id):
    conn = sqlite3.connect('movies.db')
    try:
        cur = conn.cursor()

        # Проверяем, есть ли уже в избранном
        cur.execute("SELECT 1 FROM favorites WHERE user_id = ? AND movie_id = ?",
                    (user_id, movie_id))
        if cur.fetchone():
            # Удаляем из избранного
            cur.execute("DELETE FROM favorites WHERE user_id = ? AND movie_id = ?",
                        (user_id, movie_id))
            action = 'removed'
        else:
            # Добавляем в избранное
            cur.execute("INSERT INTO favorites (user_id, movie_id) VALUES (?, ?)",
                        (user_id, movie_id))
            action = 'added'

        conn.commit()
        return action
    except sqlite3.Error as e:
        print(f"Ошибка при работе с избранным: {e}")
        return 'error'
    finally:
        conn.close()


# Получение списка избранных фильмов
def get_favorite_movies(user_id):
    conn = sqlite3.connect('movies.db')
    try:
        cur = conn.cursor()
        cur.execute('''SELECT m.id, m.name, m.picture, m.rating 
                       FROM movies m
                       JOIN favorites f ON m.id = f.movie_id
                       WHERE f.user_id = ?''', (user_id,))
        return cur.fetchall()
    except sqlite3.Error as e:
        print(f"Ошибка при получении избранных фильмов: {e}")
        return []
    finally:
        conn.close()

# Главная страница
@app.route('/')
def index():
    movies = get_movies()
    movies_list = list(movies.values())

    # Разбиваем на страницы по 8 фильмов
    per_page = 8
    pages = [movies_list[i:i + per_page] for i in range(0, len(movies_list), per_page)]

    return render_template('index.html',
                           pages=pages,
                           current_user=session.get('username'))


# Страница фильма
@app.route('/film/<film_name>')
def film(film_name):
    movies = get_movies()
    film_data = movies.get(film_name)
    if not film_data:
        return "Фильм не найден", 404

    map_image = get_country_map(film_data['country'])

    # Рассчитываем высоту блока описания
    desc_len = len(film_data['description'])
    height = max(100, (desc_len // 100) * 20)  # Примерная высота

    is_favorite = False
    if 'username' in session:
        conn = sqlite3.connect('movies.db')
        cur = conn.cursor()
        cur.execute("SELECT id FROM users WHERE username = ?", (session['username'],))
        user = cur.fetchone()
        if user:
            cur.execute("SELECT 1 FROM favorites WHERE user_id = ? AND movie_id = ?",
                        (user[0], film_data['id']))
            is_favorite = bool(cur.fetchone())
        conn.close()
    return render_template('film.html',
                           film=film_data,
                           is_favorite=is_favorite,
                           map_image=map_image,
                           desc_height=f"{height}px",
                           current_user=session.get('username'))


# Авторизация
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        conn = sqlite3.connect('movies.db')
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE username = ?", (username,))
        user = cur.fetchone()
        conn.close()

        if user and check_password_hash(user[3], password):
            session['username'] = username
            return redirect(url_for('index'))
        else:
            flash('Неверное имя пользователя или пароль', 'error')

    return render_template('login.html')


# Регистрация
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']

        if len(password) < 8:
            flash('Пароль должен быть не менее 8 символов', 'error')
            return redirect(url_for('register'))

        try:
            conn = sqlite3.connect('movies.db')
            cur = conn.cursor()

            # Проверка существующего пользователя
            cur.execute("SELECT 1 FROM users WHERE username = ? OR email = ?",
                        (username, email))
            if cur.fetchone():
                flash('Пользователь с такими данными уже существует', 'error')
                return redirect(url_for('register'))

            # Добавление нового пользователя
            hashed_pw = generate_password_hash(password)
            cur.execute("INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)",
                        (username, email, hashed_pw))
            conn.commit()

            flash('Регистрация успешна! Теперь войдите в систему.', 'success')
            return redirect(url_for('login'))

        except sqlite3.Error as e:
            flash(f'Ошибка базы данных: {str(e)}', 'error')
        finally:
            conn.close()

    return render_template('register.html')


# Выход
@app.route('/logout')
def logout():
    session.pop('username', None)
    return redirect(url_for('index'))


@app.route('/check-film')
def check_film():
    query = request.args.get('query', '').strip().lower()
    movies = get_movies()

    # Проверка точного совпадения
    for film_name in movies:
        if query == film_name.lower():
            return jsonify({'exists': True, 'film_name': film_name})

    # Проверка частичного совпадения
    for film_name in movies:
        if query in film_name.lower():
            return jsonify({'exists': True, 'film_name': film_name})

    return jsonify({'exists': False})


@app.route('/search')
def search():
    query = request.args.get('query', '').strip().lower()
    movies = get_movies()

    results = [
        (name, data) for name, data in movies.items()
        if query in name.lower()
    ]
    print(results)

    if not results:
        flash(f'Фильм "{query}" не найден', 'error')
        return redirect(url_for('index'))

    if len(results) == 1:
        return redirect(url_for('film', film_name=results[0][0]))

    # Если несколько результатов
    return render_template('search_results.html',
                           results=results,
                           query=query)


@app.route('/search-suggest')
def search_suggest():
    query = request.args.get('query', '').strip().lower()
    movies = get_movies()
    results = []
    exact_match = None

    for name, data in movies.items():
        if query == name.lower():
            exact_match = name
            results.insert(0, {  # Добавляем точное совпадение первым
                'name': name,
                'year': data['year'],
                'genre': data['genre'],
                'rating': data['rating']
            })
        elif query in name.lower():
            results.append({
                'name': name,
                'year': data['year'],
                'genre': data['genre'],
                'rating': data['rating']
            })

    return jsonify({
        'results': results[:10],  # Ограничиваем 10 результатами
        'exactMatch': exact_match
    })


@app.route('/profile')
def profile():
    if 'username' not in session:
        flash('Для просмотра профиля необходимо войти в систему', 'error')
        return redirect(url_for('login'))

    conn = sqlite3.connect('movies.db')
    cur = conn.cursor()

    # Получаем данные пользователя
    cur.execute("SELECT * FROM users WHERE username = ?", (session['username'],))
    user = cur.fetchone()

    if not user:
        session.pop('username', None)
        flash('Пользователь не найден', 'error')
        return redirect(url_for('login'))

    # Получаем избранные и просмотренные фильмы
    favorite_movies = get_favorite_movies(user[0])
    watched_movies = get_watched_movies(user[0])

    # Получаем статистику
    cur.execute("SELECT COUNT(*) FROM watched_movies WHERE user_id = ?", (user[0],))
    watched_count = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM favorites WHERE user_id = ?", (user[0],))
    favorites_count = cur.fetchone()[0]

    conn.close()

    user_data = {
        'id': user[0],
        'username': user[1],
        'email': user[2],
        'avatar': user[6] if len(user) > 6 else None,
        'created_at': datetime.strptime(user[4], '%Y-%m-%d %H:%M:%S') if user[4] else datetime.now(),
        'watched_count': watched_count,
        'favorites_count': favorites_count
    }

    return render_template('profile.html',
                           current_user=user_data,
                           favorite_movies=favorite_movies,
                           watched_movies=watched_movies, average_rating=get_average_rating(user_data['id']))


# Маршрут для добавления в просмотренные
@app.route('/add-watched/<int:movie_id>', methods=['POST'])
def add_watched(movie_id):
    if 'username' not in session:
        return jsonify({'error': 'Требуется авторизация'}), 401

    conn = None
    try:
        conn = sqlite3.connect('movies.db')
        cur = conn.cursor()

        # 1. Получаем ID пользователя
        cur.execute("SELECT id FROM users WHERE username = ?", (session['username'],))
        user = cur.fetchone()
        if not user:
            return jsonify({'error': 'Пользователь не найден'}), 404

        # 2. Проверяем существование фильма
        cur.execute("SELECT 1 FROM movies WHERE id = ?", (movie_id,))
        if not cur.fetchone():
            return jsonify({'error': 'Фильм не найден'}), 404

        # 3. Добавляем в просмотренные (если еще не добавлен)
        cur.execute(
            "INSERT OR IGNORE INTO watched_movies (user_id, movie_id) VALUES (?, ?)",
            (user[0], movie_id)
        )
        conn.commit()

        # 4. Возвращаем успешный ответ
        return jsonify({
            'success': True,
            'message': 'Фильм добавлен в просмотренные'
        })

    except sqlite3.Error as e:
        if conn:
            conn.rollback()
        return jsonify({'error': f'Ошибка базы данных: {str(e)}'}), 500
    finally:
        if conn:
            conn.close()
            
# Маршрут для работы с избранным
@app.route('/toggle-favorite/<int:movie_id>', methods=['POST'])
def toggle_favorite(movie_id):
    if 'username' not in session:
        return jsonify({'error': 'Требуется авторизация'}), 401

    conn = sqlite3.connect('movies.db')
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE username = ?", (session['username'],))
    user = cur.fetchone()
    conn.close()

    if not user:
        return jsonify({'error': 'Пользователь не найден'}), 404

    action = toggle_favorite_movie(user[0], movie_id)
    if action in ['added', 'removed']:
        return jsonify({'success': True, 'action': action})
    else:
        return jsonify({'error': 'Ошибка при обновлении избранного'}), 500

@app.route('/upload-avatar-page')
def upload_avatar_page():
    if 'username' not in session:
        return redirect(url_for('login'))
    return render_template('upload_avatar.html')

@app.route('/upload-avatar', methods=['POST'])
def upload_avatar():
    if 'username' not in session:
        return jsonify({'error': 'Требуется авторизация'}), 401

    if 'avatar' not in request.files:
        return jsonify({'error': 'Файл не выбран'}), 400

    file = request.files['avatar']
    if file.filename == '':
        return jsonify({'error': 'Файл не выбран'}), 400

    if not allowed_file(file.filename):
        return jsonify({'error': 'Недопустимый формат файла'}), 400

    try:
        # Генерируем уникальное имя файла
        ext = file.filename.rsplit('.', 1)[1].lower()
        filename = f"{session['username']}_{uuid.uuid4().hex[:8]}.{ext}"
        filepath = os.path.join(AVATARS_FOLDER, filename)

        # Сохраняем файл
        file.save(filepath)

        # Обновляем БД
        conn = sqlite3.connect('movies.db')
        cur = conn.cursor()
        cur.execute("UPDATE users SET avatar = ? WHERE username = ?",
                   (filename, session['username']))
        conn.commit()
        conn.close()

        return jsonify({
            'success': True,
            'avatar_url': url_for('static', filename=f'uploads/avatars/{filename}')
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/uploads/avatars/<filename>')
def uploaded_avatar(filename):
    return send_from_directory(AVATARS_FOLDER, filename)

if __name__ == '__main__':
    init_db()
    app.run()