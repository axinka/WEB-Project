from flask import Flask, render_template, request
import sqlite3

app = Flask(__name__)


def get_top_movies():
    conn = sqlite3.connect('movies.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, name_ru, rating_kinopoisk, poster_url 
        FROM movies 
        ORDER BY rating_kinopoisk DESC 
        LIMIT 10
    ''')
    movies = cursor.fetchall()
    conn.close()
    return movies


def get_movie_details(movie_id):
    conn = sqlite3.connect('movies.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT name_ru, genre, description, year, country, 
               rating_kinopoisk, poster_url, actors 
        FROM movies 
        WHERE id = ?
    ''', (movie_id,))
    movie = cursor.fetchone()
    conn.close()
    return movie


def get_movies_by_genre(genre, limit=20, offset=0):
    conn = sqlite3.connect('movies.db')
    cursor = conn.cursor()

    # Вычисляем кол-во фильмов определенного жанра
    cursor.execute('''
        SELECT COUNT(*) 
        FROM movies 
        WHERE genre LIKE ?
    ''', (f'%{genre}%',))
    total_movies = cursor.fetchone()[0]

    # Получаем фильмы с разбивкой на страницы
    cursor.execute('''
        SELECT id, name_ru, rating_kinopoisk, poster_url 
        FROM movies 
        WHERE genre LIKE ? 
        ORDER BY rating_kinopoisk DESC 
        LIMIT ? OFFSET ?
    ''', (f'%{genre}%', limit, offset))
    movies = cursor.fetchall()
    conn.close()
    return movies, total_movies


@app.route('/')
def home():
    top_movies = get_top_movies()
    genres = [
        'триллер', 'фантастика', 'мелодрама', 'драма', 'криминал',
        'комедия', 'боевик', 'фэнтези', 'приключения', 'ужасы',
        'вестерн', 'детектив', 'биография', 'документальный',
        'семейный', 'короткометражка', 'военный', 'мультфильм',
        'спорт', 'история', 'музыка', 'мюзикл'
    ]
    return render_template('home.html', movies=top_movies, genres=genres)


@app.route('/movie/<int:movie_id>')
def movie_details(movie_id):
    movie = get_movie_details(movie_id)
    if not movie:
        return "Фильм не найден", 404
    return render_template('movie_details.html', movie=movie)


@app.route('/genre/<genre>')
def genre_movies(genre):
    # Получаем номер страницы из параметра запроса, по умолчанию равный 1
    page = request.args.get('page', 1, type=int)
    movies_per_page = 20
    # Вычисляем смещение для SQL-запроса
    offset = (page - 1) * movies_per_page
    # получаем данные о фильмах
    movies, total_movies = get_movies_by_genre(genre, limit=movies_per_page, offset=offset)
    # Подсчет общего количества страниц
    total_pages = (total_movies + movies_per_page - 1) // movies_per_page
    # Генерирование номера страниц для навигации
    page_numbers = range(1, total_pages + 1)

    return render_template('genre_movies.html', genre=genre, movies=movies, page=page,
                           page_numbers=page_numbers, total_pages=total_pages)


@app.route('/login')
def login():
    return "Страница входа"


@app.route('/register')
def register():
    return "Страница регистрации"


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)