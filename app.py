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
                'actors': movie[8]
            }
    return movies_dict

# Функция для получения фильмов с пагинацией для главной страницы
def get_paginated_movies(page=1, per_page=30):
    conn = sqlite3.connect('movies.db')
    try:
        cur = conn.cursor()
        offset = (page - 1) * per_page
        cur.execute('''SELECT id, name, picture, rating, year 
                       FROM movies 
                       LIMIT ? OFFSET ?''', (per_page, offset))
        movies = cur.fetchall()

        # Получаем общее количество фильмов для пагинации
        cur.execute('SELECT COUNT(*) FROM movies')
        total = cur.fetchone()[0]
        total_pages = (total + per_page - 1) // per_page

        return movies, total_pages
    except sqlite3.Error as e:
        print(f"Ошибка при получении фильмов: {e}")
        return [], 0
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
        cur = conn.cursor()
        offset = (page - 1) * per_page
        cur.execute('''SELECT m.id, m.name, m.picture, m.rating, m.year 
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
        total = cur.fetchone()[0]
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
        cur = conn.cursor()
        offset = (page - 1) * per_page
        cur.execute('''SELECT m.id, m.name, m.picture, m.rating, m.year 
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
        total = cur.fetchone()[0]
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

    map_image = get_country_map(film_data['country'])

    # Рассчитываем высоту блока описания
    desc_len = len(film_data['description'])
    height = max(100, (desc_len // 100) * 20)

    is_favorite = False
    is_watched = False
    if 'username' in session:
        conn = sqlite3.connect('movies.db')
        cur = conn.cursor()
        cur.execute("SELECT id FROM users WHERE username = ?", (session['username'],))
        user = cur.fetchone()
        if user:
            # Проверяем, добавлен ли фильм в избранное
            cur.execute("SELECT 1 FROM favorites WHERE user_id = ? AND movie_id = ?",
                        (user[0], film_data['id']))
            is_favorite = bool(cur.fetchone())

            # Проверяем, просмотрен ли фильм
            cur.execute("SELECT 1 FROM watched_movies WHERE user_id = ? AND movie_id = ?",
                        (user[0], film_data['id']))
            is_watched = bool(cur.fetchone())
        conn.close()

    return render_template('film.html',
                           film=film_data,
                           is_favorite=is_favorite,
                           is_watched=is_watched,
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

    # Получаем избранные и просмотренные фильмы с пагинацией
    favorite_page = request.args.get('favorite_page', 1, type=int)
    watched_page = request.args.get('watched_page', 1, type=int)
    favorite_movies, favorite_total_pages = get_favorite_movies(user[0], favorite_page, 30)
    watched_movies, watched_total_pages = get_watched_movies(user[0], watched_page, 30)

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

    # Предотвращаем кэширование страницы
    response = render_template('profile.html',
                               current_user=user_data,
                               favorite_movies=favorite_movies,
                               favorite_total_pages=favorite_total_pages,
                               favorite_page=favorite_page,
                               watched_movies=watched_movies,
                               watched_total_pages=watched_total_pages,
                               watched_page=watched_page,
                               average_rating=get_average_rating(user_data['id']))
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

if __name__ == '__main__':
    init_db()
    app.run()