from flask import Flask, render_template, request, session, redirect, url_for, g
from werkzeug.exceptions import abort
import sqlite3, secrets, time
app = Flask(__name__)

# Генерировать с помощью команды `py -3 -c "import secrets; print(secrets.token_hex())"`
#app.secret_key = b'dc566b25c26ac0f2d5a96321a155c41133ecdc8409ff868ec063a2c3e8414e75'

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect('main.db', detect_types=sqlite3.PARSE_DECLTYPES)
        g.db.row_factory = sqlite3.Row
    return g.db

def close_db():
    db = g.pop('db', None)
    if db is not None:
        db.close()

def valid_login(username, password):
    db = get_db()
    reader_id = db.execute("SELECT reader_id FROM readers WHERE `username` = ? AND `password` = ?", (username, password)).fetchone()
    if reader_id:
        token = secrets.token_hex()
        date = round(time.time())
        db.execute("INSERT INTO tokens VALUES (?, ?, ?, ?)", (token, reader_id[0], date, date))
        db.commit()
        return token
    return None

def invalid_token(token):
    db = get_db()
    db.execute("DELETE FROM tokens WHERE `token` = ?", (token,))
    db.commit()

def token_is_valid(token):
    db = get_db()
    result = db.execute("SELECT token FROM tokens WHERE `token` = ?", (token,)).fetchone()
    if result is not None:
        if result[0] == token:
            date = round(time.time())
            db.execute("UPDATE tokens SET `date_lastauth` = ? WHERE `token` = ?", (date, token))
            db.commit()
            return True
    return False

def create_account(username, password):
    db = get_db()
    db.execute("INSERT INTO readers (username, password) VALUES (?, ?)", (username, password))
    db.commit()

def add_book(title, year, author, max_pages, description, artwork):
    db = get_db()
    db.execute("INSERT INTO books (title, year, author, max_pages, description, artwork) VALUES (?, ?, ?, ?, ?, ?)", (title, year, author, max_pages, description, artwork))
    db.commit()

def edit_book(book_id, title, year, author, max_pages, description, artwork):
    db = get_db()
    db.execute("UPDATE books SET `title` = ?, `year` = ?, `author` = ?, `max_pages` = ?, `description` = ?, `artwork` = ? WHERE `book_id` = ?",
               (title, year, author, max_pages, description, artwork, book_id))
    db.commit()

def get_book(book):
    return get_db().execute("SELECT * FROM books WHERE `book_id` = ?", (book,)).fetchone()

def get_books():
    return get_db().execute("SELECT * FROM books").fetchall()

def search_book(name):
    name = f'%{name}%'
    return get_db().execute("SELECT * FROM books WHERE `title` LIKE ?", (name,)).fetchall()

def is_in_progress(token, book_id):
    db = get_db()
    user_id = db.execute("SELECT reader_id FROM tokens WHERE `token` = ?", (token,)).fetchone()
    progress_id = db.execute("SELECT id FROM progress WHERE `reader_id` = ? AND `book_id` = ?", (user_id[0], book_id)).fetchone()
    return progress_id

def change_progress(token, book_id):
    db = get_db()
    progress_id = is_in_progress(token, book_id)
    user_id = db.execute("SELECT reader_id FROM tokens WHERE `token` = ?", (token,)).fetchone()
    if progress_id:
        db.execute("DELETE FROM progress WHERE `id` = ?", (progress_id[0],))
    else:
        db.execute("INSERT INTO progress (reader_id, book_id) VALUES (?, ?)", (user_id[0], book_id))
    db.commit()

def get_progress(token):
    db = get_db()
    user_id = db.execute("SELECT reader_id FROM tokens WHERE `token` = ?", (token,)).fetchone()
    return db.execute("SELECT *, books.title, books.max_pages FROM progress JOIN books ON progress.book_id = books.book_id WHERE `reader_id` = ?", (user_id[0],)).fetchall()

def is_admin(token):
    db = get_db()
    user_id = db.execute("SELECT reader_id FROM tokens WHERE `token` = ?", (token,)).fetchone()
    admin = db.execute("SELECT is_admin FROM readers WHERE `reader_id` = ?", (user_id[0],)).fetchone()
    return admin[0] == 1

@app.before_request
def check_token():
    if 'token' in session:
        token = session['token']
        if token_is_valid(token):
            db = get_db()
            reader_id = db.execute("SELECT reader_id FROM tokens WHERE `token` = ?", (token,)).fetchone()
            g.user = db.execute("SELECT * FROM readers WHERE `reader_id` = ?", (reader_id[0],)).fetchone()
        else:
            session.clear()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/search', methods=['GET'])
def search():
    query = None
    books = None
    count = None
    if request.method == 'GET':
        query = request.args.get('q', '')
        books = search_book(query)
        count = len(books)
    return render_template('search.html', query=query, books=books, count=count)

@app.route('/books')
def show_books():
    books = get_books()
    count = len(books)
    return render_template('books.html', books=books, count=count)

@app.route('/book/<int:book_id>')
def show_book(book_id=None):
    if book_id:
        book = get_book(book_id)
        in_progress = None
        if book:
            if 'user' in g:
                in_progress = is_in_progress(session['token'], book_id)
            return render_template('book.html', book=book, in_progress=in_progress)
        else:
            abort(404)
    else:
        return redirect(url_for('index'))

@app.route('/editprogress/<int:book_id>')
def edit_progress(book_id=None):
    if 'user' not in g:
        abort(403)
    else:
        if get_book(book_id):
            change_progress(session['token'], book_id)
            return redirect(url_for('show_book', book_id=book_id))
        else:
            abort(404)

@app.route('/edit_book')
@app.route('/edit_book/<int:book_id>', methods=['POST', 'GET'])
def edit_books(book_id=None):
    if 'user' not in g:
        return redirect(url_for('index'))
    else:
        if is_admin(session['token']):
            notify = None
            if book_id:
                if request.method == 'POST':
                    edit_book(book_id, request.form['title'], request.form['year'], request.form['author'], request.form['max_pages'], request.form['description'], request.form['artwork'])
                    notify = 'Изменения внесены.'
                book = get_book(book_id)
                if book:
                    return render_template('edit-book.html', book=book, notify=notify)
                else:
                    abort(404)
            else:
                books = get_books()
                return render_template('edit-book-pick.html', books=books)
        else:
            abort(403)

@app.route('/add_book', methods=['POST', 'GET'])
def create_book():
    if 'user' not in g:
        return redirect(url_for('index'))
    else:
        if is_admin(session['token']):
            notify = None
            if request.method == 'POST':
                add_book(request.form['title'], request.form['year'], request.form['author'], request.form['max_pages'], request.form['description'], request.form['artwork'])
                notify = 'Книга добавлена.'
            return render_template('add-book.html', notify=notify)
        else:
            abort(403)

@app.route('/login', methods=['POST', 'GET'])
def show_login():
    if 'user' not in g:
        error = None
        if request.method == 'POST':
            session['token'] = valid_login(request.form['username'], request.form['password'])
            if session['token']:
                app.logger.debug(f'A successful login to {request.form['username']} account.')
                return redirect(url_for('index'))
            else:
                app.logger.error('A failed attempt to login!')
                error = 'Неверные данные'
        return render_template('login.html', error=error)
    else:
        return redirect(url_for('index'))

@app.route('/register', methods=['POST', 'GET'])
def show_register():
    if 'user' not in g:
        error = None
        if request.method == 'POST':
            create_account(request.form['username'], request.form['password'])
            session['token'] = valid_login(request.form['username'], request.form['password'])
            if session['token']:
                app.logger.debug(f'A new account {request.form['username']} was created.')
                return redirect(url_for('index'))
            else:
                app.logger.error('A failed attempt to create an account!')
                error = 'Произошла ошибка при создании аккаунта.'
        return render_template('register.html', error=error)
    else:
        return redirect(url_for('index'))

@app.route('/profile')
def profile():
    if 'user' not in g:
        return redirect(url_for('show_login'))
    else:
        progress = get_progress(session['token'])
        return render_template('profile.html', progress=progress)

@app.route('/logout')
def logout():
    invalid_token(session['token'])
    session.clear()
    return redirect(url_for('index'))

@app.errorhandler(404)
def page_not_found(error):
    return render_template('404.html'), 404