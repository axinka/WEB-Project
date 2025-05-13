import uuid
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, send_from_directory, \
    abort
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
from geopy.geocoders import Nominatim
import os
import requests
import secrets
from flask_wtf.csrf import CSRFProtect
from werkzeug.utils import secure_filename

MAX_AVATAR_SIZE = 2 * 1024 * 1024  # 2MB

app = Flask(__name__)
app.secret_key = 'd9a7b83c5f1e4a2b8c7d6e5f4a3b2c1d8e7f6a5b4c3d2e1f0a9b8c7d6e5f4'
csrf = CSRFProtect(app)

app.config['TIMEZONE_OFFSET'] = timedelta(hours=3)



def generate_csrf_token():
    token = secrets.token_hex(32)  # Генерирует случайный токен длиной 64 символа (32 байта в шестнадцатеричном формате)
    return token

csrf_token = generate_csrf_token()

UPLOAD_FOLDER = 'static/uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

AVATARS_FOLDER = os.path.join(UPLOAD_FOLDER, 'avatars')
if not os.path.exists(AVATARS_FOLDER):
    os.makedirs(AVATARS_FOLDER)

MOVIES_UPLOAD_FOLDER = os.path.join('static', 'uploads', 'movies')

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def dict_factory(cursor, row):
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            return redirect(url_for('login'))

        conn = sqlite3.connect('movies.db')
        cur = conn.cursor()
        cur.execute("SELECT role FROM users WHERE username = ?", (session['username'],))
        user = cur.fetchone()
        conn.close()

        if not user or user[0] != 'admin':
            abort(403)  # Forbidden
        return f(*args, **kwargs)

    return decorated_function

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

# Функция для получения всех фильмов в виде словаря
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
                'actors': movie[8],
                'author_id': movie[9],
                'updated_at': movie[10],
                'created_at': movie[11]
            }
    return movies_dict

# Функция для получения фильмов с пагинацией для главной страницы
def get_paginated_movies(page=1, per_page=30):
    conn = sqlite3.connect('movies.db')
    try:
        conn.row_factory = dict_factory
        cur = conn.cursor()
        offset = (page - 1) * per_page
        cur.execute('''SELECT id, name, picture, rating, year, author_id 
                       FROM movies 
                       LIMIT ? OFFSET ?''', (per_page, offset))
        movies = cur.fetchall()

        cur.execute('SELECT COUNT(*) FROM movies')
        total = cur.fetchone()['COUNT(*)']
        total_pages = (total + per_page - 1) // per_page

        return movies, total_pages
    finally:
        conn.close()

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

# Получение списка просмотренных фильмов с пагинацией
def get_watched_movies(user_id, page=1, per_page=30):
    conn = sqlite3.connect('movies.db')
    try:
        conn.row_factory = dict_factory
        cur = conn.cursor()
        offset = (page - 1) * per_page
        cur.execute('''SELECT m.id, m.name, m.picture, m.rating, m.year, m.author_id 
                       FROM movies m
                       JOIN watched_movies wm ON m.id = wm.movie_id
                       WHERE wm.user_id = ?
                       LIMIT ? OFFSET ?''', (user_id, per_page, offset))
        movies = cur.fetchall()

        # Получаем общее количество фильмов для пагинации
        cur.execute('''SELECT COUNT(*) 
                       FROM watched_movies wm
                       JOIN movies m ON m.id = wm.movie_id
                       WHERE wm.user_id = ?''', (user_id,))
        total = cur.fetchone()['COUNT(*)']
        total_pages = (total + per_page - 1) // per_page

        return movies, total_pages
    except sqlite3.Error as e:
        print(f"Ошибка при получении просмотренных фильмов: {e}")
        return [], 0
    finally:
        conn.close()

def get_average_rating(user_id):
    conn = sqlite3.connect('movies.db')
    try:
        cur = conn.cursor()
        cur.execute('''SELECT COALESCE(AVG(m.rating), 0.0) 
                       FROM movies m
                       JOIN watched_movies w ON m.id = w.movie_id
                       WHERE w.user_id = ?''', (user_id,))
        result = cur.fetchone()[0]
        print(f"Average rating for user {user_id}: {result}")  # Отладочный вывод
        return result if result is not None else 0.0
    finally:
        conn.close()

# Добавление/удаление из избранного
def toggle_favorite_movie(user_id, movie_id):
    conn = None
    try:
        conn = sqlite3.connect('movies.db')
        cur = conn.cursor()

        cur.execute("SELECT 1 FROM favorites WHERE user_id = ? AND movie_id = ?",
                    (user_id, movie_id))
        if cur.fetchone():
            cur.execute("DELETE FROM favorites WHERE user_id = ? AND movie_id = ?",
                        (user_id, movie_id))
            action = 'removed'
        else:
            cur.execute("INSERT INTO favorites (user_id, movie_id) VALUES (?, ?)",
                        (user_id, movie_id))
            action = 'added'

        conn.commit()
        return action
    except sqlite3.Error as e:
        if conn:
            conn.rollback()
        print(f"Ошибка при работе с избранным: {e}")
        return 'error'
    finally:
        if conn:
            conn.close()

# Получение списка избранных фильмов с пагинацией
def get_favorite_movies(user_id, page=1, per_page=30):
    conn = sqlite3.connect('movies.db')
    try:
        conn.row_factory = dict_factory
        cur = conn.cursor()
        offset = (page - 1) * per_page
        cur.execute('''SELECT m.id, m.name, m.picture, m.rating, m.year, m.author_id 
                       FROM movies m
                       JOIN favorites f ON m.id = f.movie_id
                       WHERE f.user_id = ?
                       LIMIT ? OFFSET ?''', (user_id, per_page, offset))
        movies = cur.fetchall()

        # Получаем общее количество фильмов для пагинации
        cur.execute('''SELECT COUNT(*) 
                       FROM favorites f
                       JOIN movies m ON m.id = f.movie_id
                       WHERE f.user_id = ?''', (user_id,))
        total = cur.fetchone()['COUNT(*)']
        total_pages = (total + per_page - 1) // per_page

        return movies, total_pages
    except sqlite3.Error as e:
        print(f"Ошибка при получении избранных фильмов: {e}")
        return [], 0
    finally:
        conn.close()

# Удаление фильма из просмотренных
def remove_watched_movie(user_id, movie_id):
    conn = None
    try:
        conn = sqlite3.connect('movies.db')
        cur = conn.cursor()
        cur.execute("DELETE FROM watched_movies WHERE user_id = ? AND movie_id = ?",
                    (user_id, movie_id))
        conn.commit()
        return True
    except sqlite3.Error as e:
        if conn:
            conn.rollback()
        print(f"Ошибка при удалении из просмотренных: {e}")
        return False
    finally:
        if conn:
            conn.close()

# Главная страница с пагинацией
@app.route('/')
def index():
    page = request.args.get('page', 1, type=int)
    movies, total_pages = get_paginated_movies(page, 30)

    return render_template('index.html',
                           movies=movies,
                           total_pages=total_pages,
                           page=page,
                           current_user=session.get('username'))

# Страница фильма
@app.route('/film/<film_name>')
def film(film_name):
    movies = get_movies()
    film_data = movies.get(film_name)
    if not film_data:
        return "Фильм не найден", 404
    if 'https://' not in film_data['picture']:
        url_bool = True
    else:
        url_bool = False

    print(film_data)
    print(session.get('username'))

    map_image = get_country_map(film_data['country'])
    desc_len = len(film_data['description'])
    height = max(100, (desc_len // 100) * 20)

    is_favorite = False
    is_watched = False
    user_data = None
    role = None


    if 'username' in session:
        conn = sqlite3.connect('movies.db')
        conn.row_factory = dict_factory  # Убедитесь, что используете dict_factory
        cur = conn.cursor()

        # Получаем данные пользователя как словарь
        cur.execute("SELECT id, role FROM users WHERE username = ?", (session['username'],))
        user_data = cur.fetchone()

        if user_data:
            # Проверяем избранное
            cur.execute("SELECT 1 FROM favorites WHERE user_id = ? AND movie_id = ?",
                        (user_data['id'], film_data['id']))
            is_favorite = bool(cur.fetchone())

            # Проверяем просмотренные
            cur.execute("SELECT 1 FROM watched_movies WHERE user_id = ? AND movie_id = ?",
                        (user_data['id'], film_data['id']))
            is_watched = bool(cur.fetchone())

            role = user_data.get('role')

        conn.close()

    return render_template('film.html',
                           film=film_data,
                           is_favorite=is_favorite,
                           is_watched=is_watched,
                           map_image=map_image,
                           desc_height=f"{height}px",
                           current_user=session.get('username'),
                           current_id=session.get('id'),
                           user_data=user_data,
                           role=role,
                           url_bool=url_bool)
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
        role = request.form['role']

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
            cur.execute("INSERT INTO users (username, email, password_hash, role) VALUES (?, ?, ?, ?)",
                        (username, email, hashed_pw, role))
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
    query = request.args.get('query', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = 20  # Количество результатов на странице
    print(query)

    if not query:
        return redirect(url_for('index'))

    conn = sqlite3.connect('movies.db')
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Получаем общее количество результатов
    cur.execute('''SELECT COUNT(*) FROM movies 
                   WHERE name LIKE ? OR name LIKE ?''',
                (f'%{query}%', f'%{query.capitalize()}%'))
    total = cur.fetchone()[0]

    # Рассчитываем общее количество страниц
    total_pages = (total + per_page - 1) // per_page
    page = max(1, min(page, total_pages))

    # Получаем результаты для текущей страницы
    offset = (page - 1) * per_page
    cur.execute('''SELECT * FROM movies 
                   WHERE name LIKE ? OR name LIKE ?
                   LIMIT ? OFFSET ?''',
                (f'%{query}%', f'%{query.capitalize()}%', per_page, offset))

    movies = {}
    for row in cur.fetchall():
        short_name = row['name'] if len(row['name']) < 34 else row['name'][:31] + '...'
        movies[row['name']] = {
            'sh_name': short_name,
            'year': row['year'],
            'rating': row['rating'],
            'picture': row['picture']
        }

    print(movies)

    conn.close()

    return render_template('search_results.html',
                           query=query,
                           results=movies,
                           page=page,
                           total_pages=total_pages, items=movies.items(), current_user=session.get('username'))
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
    conn.row_factory = dict_factory
    cur = conn.cursor()

    # Получаем данные пользователя
    cur.execute("SELECT id, username, email, created_at, role FROM users WHERE username = ?", (session['username'],))
    user = cur.fetchone()

    if not user:
        session.pop('username', None)
        flash('Пользователь не найден', 'error')
        return redirect(url_for('login'))

    # Преобразуем строку created_at в datetime объект
    if isinstance(user['created_at'], str):
        user['created_at'] = datetime.strptime(user['created_at'], '%Y-%m-%d %H:%M:%S')

    # Остальной код...
    # Получаем избранные и просмотренные фильмы с пагинацией
    favorite_page = request.args.get('favorite_page', 1, type=int)
    watched_page = request.args.get('watched_page', 1, type=int)
    favorite_movies, favorite_total_pages = get_favorite_movies(user['id'], favorite_page, 30)
    watched_movies, watched_total_pages = get_watched_movies(user['id'], watched_page, 30)

    # Получаем статистику
    cur.execute("SELECT COUNT(*) FROM watched_movies WHERE user_id = ?", (user['id'],))
    watched_count = cur.fetchone()['COUNT(*)']

    cur.execute("SELECT COUNT(*) FROM favorites WHERE user_id = ?", (user['id'],))
    favorites_count = cur.fetchone()['COUNT(*)']

    conn.close()


    print(watched_movies)
    print(user)

    # Предотвращаем кэширование страницы
    response = render_template('profile.html',
                               current_user=user,
                               favorite_movies=favorite_movies,
                               favorite_total_pages=favorite_total_pages,
                               favorite_page=favorite_page,
                               watched_movies=watched_movies,
                               watched_total_pages=watched_total_pages,
                               watched_page=watched_page,
                               watched_count=watched_count,
                               favorites_count=favorites_count,
                               average_rating=round(get_average_rating(user['id']), 1))
    response = app.make_response(response)
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '-1'
    return response

# Маршрут для добавления в просмотренные
@app.route('/add-watched/<int:movie_id>', methods=['POST'])
def add_watched(movie_id):
    if 'username' not in session:
        flash('Требуется авторизация', 'error')
        return redirect(url_for('login'))

    conn = None
    try:
        conn = sqlite3.connect('movies.db')
        cur = conn.cursor()

        # 1. Получаем ID пользователя
        cur.execute("SELECT id FROM users WHERE username = ?", (session['username'],))
        user = cur.fetchone()
        if not user:
            flash('Пользователь не найден', 'error')
            return redirect(url_for('index'))

        # 2. Проверяем существование фильма
        cur.execute("SELECT name FROM movies WHERE id = ?", (movie_id,))
        movie = cur.fetchone()
        if not movie:
            flash('Фильм не найден', 'error')
            return redirect(url_for('index'))

        # 3. Добавляем в просмотренные (если еще не добавлен)
        success = add_watched_movie(user[0], movie_id)
        if success:
            flash('Фильм добавлен в просмотренные', 'success')
        else:
            flash('Фильм уже в просмотренных', 'info')

        # Перенаправляем обратно на страницу фильма
        return redirect(url_for('film', film_name=movie[0]))

    except sqlite3.Error as e:
        if conn:
            conn.rollback()
        flash(f'Ошибка базы данных: {str(e)}', 'error')
        return redirect(url_for('index'))
    finally:
        if conn:
            conn.close()

# Маршрут для работы с избранным
@app.route('/toggle-favorite/<int:movie_id>', methods=['POST'])
def toggle_favorite(movie_id):
    if 'username' not in session:
        flash('Требуется авторизация', 'error')
        return redirect(url_for('login'))

    conn = None
    try:
        conn = sqlite3.connect('movies.db')
        cur = conn.cursor()

        # Проверка пользователя
        cur.execute("SELECT id FROM users WHERE username = ?", (session['username'],))
        user = cur.fetchone()
        if not user:
            flash('Пользователь не найден', 'error')
            return redirect(url_for('index'))

        # Проверка существования фильма
        cur.execute("SELECT name FROM movies WHERE id = ?", (movie_id,))
        movie = cur.fetchone()
        if not movie:
            flash('Фильм не найден', 'error')
            return redirect(url_for('index'))

        # Вызов функции toggle_favorite_movie
        action = toggle_favorite_movie(user[0], movie_id)
        if action in ['added', 'removed']:
            flash('Фильм добавлен в избранное' if action == 'added' else 'Фильм удалён из избранного', 'success')
        else:
            flash('Ошибка при обновлении избранного', 'error')

        # Перенаправляем обратно на страницу фильма
        return redirect(url_for('film', film_name=movie[0]))

    except sqlite3.Error as e:
        print(f"Ошибка в маршруте toggle_favorite: {e}, movie_id: {movie_id}")
        flash(f'Ошибка базы данных: {str(e)}', 'error')
        return redirect(url_for('index'))
    finally:
        if conn:
            conn.close()

# Маршрут для удаления из просмотренных
@app.route('/remove-watched/<int:movie_id>', methods=['POST'])
def remove_watched(movie_id):
    if 'username' not in session:
        flash('Требуется авторизация', 'error')
        return redirect(url_for('login'))

    conn = None
    try:
        conn = sqlite3.connect('movies.db')
        cur = conn.cursor()

        # 1. Получаем ID пользователя
        cur.execute("SELECT id FROM users WHERE username = ?", (session['username'],))
        user = cur.fetchone()
        if not user:
            flash('Пользователь не найден', 'error')
            return redirect(url_for('index'))

        # 2. Проверяем существование фильма
        cur.execute("SELECT name FROM movies WHERE id = ?", (movie_id,))
        movie = cur.fetchone()
        if not movie:
            flash('Фильм не найден', 'error')
            return redirect(url_for('index'))

        # 3. Проверяем существование записи
        cur.execute("SELECT 1 FROM watched_movies WHERE user_id = ? AND movie_id = ?",
                    (user[0], movie_id))
        if not cur.fetchone():
            flash('Фильм не найден в просмотренных', 'error')
            return redirect(url_for('film', film_name=movie[0]))

        # 4. Удаляем из просмотренных
        success = remove_watched_movie(user[0], movie_id)
        if success:
            flash('Фильм удалён из просмотренных', 'success')
        else:
            flash('Ошибка при удалении из просмотренных', 'error')

        # Перенаправляем обратно на страницу фильма
        return redirect(url_for('film', film_name=movie[0]))

    except sqlite3.Error as e:
        if conn:
            conn.rollback()
        flash(f'Ошибка базы данных: {str(e)}', 'error')
        return redirect(url_for('index'))
    finally:
        if conn:
            conn.close()

# Маршрут для загрузки аватара
@app.route('/upload-avatar', methods=['POST'])
def upload_avatar():
    if 'username' not in session:
        flash('Требуется авторизация', 'error')
        return redirect(url_for('login'))

    if 'avatar' not in request.files:
        flash('Файл не выбран', 'error')
        return redirect(url_for('profile'))

    file = request.files['avatar']
    if file.filename == '':
        flash('Файл не выбран', 'error')
        return redirect(url_for('profile'))

    if not allowed_file(file.filename):
        flash('Недопустимый формат файла. Разрешены: png, jpg, jpeg, gif', 'error')
        return redirect(url_for('profile'))

    try:
        # Генерируем уникальное имя файла
        ext = file.filename.rsplit('.', 1)[1].lower()
        filename = f"{session['username']}_{uuid.uuid4().hex[:8]}.{ext}"
        filepath = os.path.join(AVATARS_FOLDER, filename)

        # Проверяем, существует ли директория и доступна ли она для записи
        if not os.path.exists(AVATARS_FOLDER):
            os.makedirs(AVATARS_FOLDER)

        # Сохраняем файл
        file.save(filepath)

        # Проверяем, что файл действительно сохранён
        if not os.path.exists(filepath):
            flash('Не удалось сохранить файл на сервере', 'error')
            return redirect(url_for('profile'))

        # Обновляем БД
        conn = sqlite3.connect('movies.db')
        cur = conn.cursor()
        cur.execute("UPDATE users SET avatar = ? WHERE username = ?",
                   (filename, session['username']))
        conn.commit()
        conn.close()

        flash('Аватар успешно загружен!', 'success')
        return redirect(url_for('profile'))
    except Exception as e:
        flash(f'Ошибка при загрузке аватара: {str(e)}', 'error')
        return redirect(url_for('profile'))

@app.route('/uploads/avatars/<filename>')
def uploaded_avatar(filename):
    # Предотвращаем кэширование изображения
    response = send_from_directory(AVATARS_FOLDER, filename)
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '-1'
    return response

@app.route('/add_movie', methods=['GET', 'POST'])
@admin_required
def add_movie():
    errors = {}
    current_year = datetime.now().year

    if request.method == 'POST':
        try:
            # Валидация данных
            name = request.form.get('name', '').strip()
            if not name:
                errors['name'] = "Название фильма обязательно"

            genre = request.form.get('genre', '').strip()
            if not genre:
                errors['genre'] = "Жанр обязателен"

            description = request.form.get('description', '').strip()
            if not description:
                errors['description'] = "Описание обязательно"

            year = request.form.get('year', '').strip()
            if not year:
                errors['year'] = "Год выпуска обязателен"
            else:
                try:
                    year = int(year)
                    if year < 1900 or year > current_year:
                        errors['year'] = f"Год должен быть между 1900 и {current_year}"
                except ValueError:
                    errors['year'] = "Некорректный год"

            country = request.form.get('country', '').strip()
            if not country:
                errors['country'] = "Страна обязательна"

            rating = request.form.get('rating', '').strip()
            if rating:
                try:
                    rating = float(rating)
                    if rating < 0 or rating > 10:
                        errors['rating'] = "Рейтинг должен быть от 0 до 10"
                except ValueError:
                    errors['rating'] = "Некорректный рейтинг"
            else:
                rating = None

            actors = request.form.get('actors', '').strip()

            # Обработка файла
            picture_filename = None
            if 'picture' in request.files:
                file = request.files['picture']
                if file.filename != '':
                    if not allowed_file(file.filename):
                        errors['picture'] = "Допустимы только файлы изображений (PNG, JPG, JPEG, GIF)"
                    else:
                        filename = secure_filename(file.filename)
                        unique_filename = f"{datetime.now().timestamp()}_{filename}"
                        os.makedirs(MOVIES_UPLOAD_FOLDER, exist_ok=True)
                        file.save(os.path.join(MOVIES_UPLOAD_FOLDER, unique_filename))
                        picture_filename = unique_filename

            # Если нет ошибок - сохраняем фильм
            if not errors:
                conn = sqlite3.connect('movies.db')
                cur = conn.cursor()
                cur.execute("SELECT id FROM users WHERE username = ?", (session['username'],))
                author_id = cur.fetchone()[0]
                if not picture_filename:
                    picture_filename = 'https://kinopoiskapiunofficial.tech/images/posters/kp/1185710.jpg'

                cur.execute('''INSERT INTO movies 
                              (name, genre, description, year, country, rating, 
                               picture, actors, author_id, created_at)
                              VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))''',
                            (name, genre, description, year, country, rating,
                             picture_filename, actors, author_id))
                conn.commit()
                conn.close()

                flash('Фильм успешно добавлен!', 'success')
                return redirect(url_for('index'))

        except Exception as e:
            flash(f'Ошибка при добавлении фильма: {str(e)}', 'error')

    return render_template('add_movie.html',
                         current_year=current_year,
                         errors=errors, current_user=session.get('username'))


@app.route('/edit_movie/<int:movie_id>', methods=['GET', 'POST'])
@admin_required
def edit_movie(movie_id):
    conn = sqlite3.connect('movies.db')
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Получаем текущие данные фильма
    cur.execute("SELECT * FROM movies WHERE id = ?", (movie_id,))
    film = cur.fetchone()

    if not film:
        flash('Фильм не найден', 'error')
        return redirect(url_for('index'))

    # Проверяем, что текущий пользователь - автор фильма
    cur.execute("SELECT id FROM users WHERE username = ?", (session['username'],))
    current_user_id = cur.fetchone()[0]

    if film['author_id'] != current_user_id:
        flash('Вы можете редактировать только свои фильмы', 'error')
        return redirect(url_for('index'))

    errors = {}
    current_year = datetime.now().year

    if request.method == 'POST':
        try:
            # Валидация данных
            name = request.form.get('name', '').strip()
            if not name:
                errors['name'] = "Название фильма обязательно"

            genre = request.form.get('genre', '').strip()
            if not genre:
                errors['genre'] = "Жанр обязателен"

            description = request.form.get('description', '').strip()
            if not description:
                errors['description'] = "Описание обязательно"

            year = request.form.get('year', '').strip()
            if not year:
                errors['year'] = "Год выпуска обязателен"
            else:
                try:
                    year = int(year)
                    if year < 1900 or year > current_year:
                        errors['year'] = f"Год должен быть между 1900 и {current_year}"
                except ValueError:
                    errors['year'] = "Некорректный год"

            country = request.form.get('country', '').strip()
            if not country:
                errors['country'] = "Страна обязательна"

            rating = request.form.get('rating', '').strip()
            if rating:
                try:
                    rating = float(rating)
                    if rating < 0 or rating > 10:
                        errors['rating'] = "Рейтинг должен быть от 0 до 10"
                except ValueError:
                    errors['rating'] = "Некорректный рейтинг"
            else:
                rating = None

            actors = request.form.get('actors', '').strip()

            # Обработка постера
            picture_filename = film['picture']
            remove_picture = request.form.get('remove_picture') == 'on'

            if remove_picture:
                # Удаляем текущий постер
                if picture_filename:
                    try:
                        os.remove(os.path.join('static', 'uploads', 'movies', picture_filename))
                    except Exception as e:
                        print(f"Ошибка при удалении файла: {e}")
                picture_filename = 'https://kinopoiskapiunofficial.tech/images/posters/kp/1185710.jpg'

            if 'picture' in request.files:
                file = request.files['picture']
                if file.filename != '':
                    if not allowed_file(file.filename):
                        errors['picture'] = "Допустимы только файлы изображений (PNG, JPG, JPEG, GIF)"
                    else:
                        # Удаляем старый постер, если он есть
                        if picture_filename:
                            try:
                                os.remove(os.path.join('static', 'uploads', 'movies', picture_filename))
                            except Exception as e:
                                print(f"Ошибка при удалении старого файла: {e}")

                        # Сохраняем новый постер
                        filename = secure_filename(file.filename)
                        unique_filename = f"{datetime.now().timestamp()}_{filename}"
                        os.makedirs(os.path.join('static', 'uploads', 'movies'), exist_ok=True)
                        file.save(os.path.join('static', 'uploads', 'movies', unique_filename))
                        picture_filename = unique_filename

            # Если нет ошибок - обновляем фильм

            if not errors:
                cur.execute('''UPDATE movies SET
                            name = ?, genre = ?, description = ?,
                            year = ?, country = ?, rating = ?,
                            picture = ?, actors = ?, updated_at = CURRENT_TIMESTAMP
                            WHERE id = ?''',
                            (name, genre, description, year, country, rating,
                             picture_filename, actors, movie_id))
                now = datetime.now().replace(microsecond=0)

                cur.execute('''UPDATE movies SET
                                              updated_at = ?
                                              WHERE id = ?''',
                            (now, movie_id))

                conn.commit()
                flash('Фильм успешно обновлен!', 'success')
                return redirect(url_for('film', film_name=name))

        except Exception as e:
            conn.rollback()
            flash(f'Ошибка при обновлении фильма: {str(e)}', 'error')
        finally:
            conn.close()

    # Для GET запроса или при ошибках в POST
    return render_template('edit_movie.html',
                           film=film,
                           current_year=current_year,
                           errors=errors, current_user=session.get('username'))

@app.route('/delete_movie/<int:movie_id>', methods=['POST'])
@admin_required
def delete_movie(movie_id):
    conn = None
    try:
        conn = sqlite3.connect('movies.db')
        cur = conn.cursor()

        # 1. Проверяем существование фильма и его автора
        cur.execute("""
            SELECT m.id, m.author_id, m.picture, u.id 
            FROM movies m
            JOIN users u ON u.username = ?
            WHERE m.id = ?
        """, (session['username'], movie_id))

        movie_data = cur.fetchone()

        if not movie_data:
            flash('Фильм не найден', 'error')
            return redirect(url_for('index'))

        # 2. Проверяем, что текущий пользователь - автор фильма
        if movie_data[1] != movie_data[3]:
            flash('Вы можете удалять только свои фильмы', 'error')
            return redirect(url_for('index'))

        # 3. Удаляем файл постера, если он существует
        if movie_data[2]:  # если есть путь к изображению
            try:
                poster_path = os.path.join('static', 'uploads', 'movies', movie_data[2])
                if os.path.exists(poster_path):
                    os.remove(poster_path)
            except Exception as e:
                print(f"Ошибка при удалении файла: {e}")

        # 4. Удаляем фильм из базы данных
        cur.execute("DELETE FROM movies WHERE id = ?", (movie_id,))

        # 5. Удаляем связанные данные
        cur.execute("DELETE FROM favorites WHERE movie_id = ?", (movie_id,))
        cur.execute("DELETE FROM watched_movies WHERE movie_id = ?", (movie_id,))

        conn.commit()
        flash('Фильм успешно удален', 'success')

    except sqlite3.Error as e:
        if conn:
            conn.rollback()
        flash(f'Ошибка базы данных: {str(e)}', 'error')
    finally:
        if conn:
            conn.close()

    return redirect(url_for('my_movies'))

@app.route('/my_movies')
@admin_required
def my_movies():
    # Получаем ID текущего пользователя
    conn = sqlite3.connect('movies.db')
    conn.row_factory = sqlite3.Row  # Для работы с колонками как со словарем
    cur = conn.cursor()

    # Получаем фильмы текущего пользователя
    cur.execute('''
        SELECT id, name, picture, year, rating 
        FROM movies 
        WHERE author_id = (SELECT id FROM users WHERE username = ?)
        ORDER BY created_at DESC
    ''', (session['username'],))

    movies = cur.fetchall()
    conn.close()

    return render_template('my_movies.html', movies=movies, current_user=session.get('username'))




if __name__ == '__main__':
    init_db()
    app.run()