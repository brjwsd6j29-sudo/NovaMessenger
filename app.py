import asyncio
import os
import tempfile
from datetime import datetime, timedelta
from flask import Flask, request, render_template_string, redirect, url_for, session, flash, send_file, jsonify
from functools import wraps
import logging

# Ваши модули
from database import (
    get_servers, get_server, get_server_by_id, get_all_clients,
    add_client, remove_client, update_expiry_date, mark_backed_up, init_db
)
from pterodactyl_api import PterodactylClient, PterodactylAPIError
from config import ADMIN_IDS, PANEL_BASE_URL

app = Flask(__name__)
app.secret_key = 'supersecretkey'  # замените на что-то случайное

# Настройка логов (можно убрать)
logging.basicConfig(level=logging.INFO)

# ------------------ Пользователи (захардкожены для демонстрации) ------------------
# В реальном проекте храните в БД
USERS = {
    'ZZLOYPP': {
        'password': 'PAANDAHOOST',
        'tg_id': 5826298831,   # из ADMIN_IDS
        'role': 'owner'
    },
    'CLIENTTLIRA2026': {
        'password': 'LIRAROMB20026',
        'tg_id': 123456789,    # должен совпадать с tg_id клиента в clients.db
        'role': 'client'
    }
}

# ------------------ Вспомогательные функции ------------------
def moscow_now():
    return datetime.utcnow() + timedelta(hours=3)

def is_expired(client):
    try:
        dt = datetime.strptime(f"{client.expiry_date} {client.expiry_time}", "%d.%m.%Y %H:%M")
        return dt <= moscow_now()
    except:
        return False

def get_status_label(status):
    labels = {
        'running': '🟢 Запущен',
        'starting': '🟡 Запускается',
        'stopping': '🟠 Останавливается',
        'offline': '🔴 Выключен'
    }
    return labels.get(status, status)

# ------------------ Декоратор для проверки входа ------------------
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('role') != 'owner':
            flash('Доступ запрещён', 'danger')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

# ------------------ Встроенные HTML-шаблоны (чтобы был один файл) ------------------
LOGIN_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Вход в систему</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body class="bg-dark text-light">
    <div class="container mt-5" style="max-width:400px;">
        <h2 class="text-center">🔐 Авторизация</h2>
        <form method="POST">
            <div class="mb-3">
                <label>Логин</label>
                <input type="text" name="username" class="form-control" required>
            </div>
            <div class="mb-3">
                <label>Пароль</label>
                <input type="password" name="password" class="form-control" required>
            </div>
            <button type="submit" class="btn btn-primary w-100">Войти</button>
            {% with messages = get_flashed_messages(with_categories=true) %}
                {% if messages %}
                    {% for category, msg in messages %}
                        <div class="alert alert-{{ category }} mt-3">{{ msg }}</div>
                    {% endfor %}
                {% endif %}
            {% endwith %}
        </form>
    </div>
</body>
</html>
"""

DASHBOARD_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Панель управления</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body class="bg-dark text-light">
    <nav class="navbar navbar-expand-lg navbar-dark bg-black">
        <div class="container">
            <span class="navbar-brand">📦 Управление хостингом</span>
            <div class="ms-auto">
                <span class="navbar-text me-3">{{ session.username }} ({{ 'Админ' if session.role == 'owner' else 'Клиент' }})</span>
                <a href="{{ url_for('logout') }}" class="btn btn-outline-danger btn-sm">Выйти</a>
            </div>
        </div>
    </nav>
    <div class="container mt-4">
        {% if session.role == 'owner' %}
            <h2>👑 Админ-панель</h2>
            <table class="table table-dark table-striped">
                <thead><tr><th>Название</th><th>Владелец (tg)</th><th>Тариф</th><th>Доступен до</th><th>Статус</th><th>Действия</th></tr></thead>
                <tbody>
                {% for s in all_servers %}
                    <tr>
                        <td><a href="{{ url_for('server_detail', server_id=s.server_id) }}">{{ s.server_name }}</a></td>
                        <td>{{ s.tg_id }}</td>
                        <td>{{ s.tariff }}</td>
                        <td>{{ s.expiry_date }} {{ s.expiry_time }} МСК</td>
                        <td>{% if is_expired(s) %}🔴 Истёк{% else %}🟢 Активен{% endif %}</td>
                        <td>
                            <form method="POST" action="{{ url_for('admin_extend', server_id=s.server_id, days=7) }}" style="display:inline;">
                                <button class="btn btn-success btn-sm">+7д</button>
                            </form>
                            <form method="POST" action="{{ url_for('admin_extend', server_id=s.server_id, days=30) }}" style="display:inline;">
                                <button class="btn btn-success btn-sm">+30д</button>
                            </form>
                            <form method="POST" action="{{ url_for('admin_set_date', server_id=s.server_id) }}" style="display:inline;">
                                <input type="text" name="new_date" placeholder="ДД.ММ.ГГГГ" size="10" required>
                                <input type="text" name="new_time" placeholder="ЧЧ:ММ" size="5" required>
                                <button class="btn btn-primary btn-sm">Установить</button>
                            </form>
                            <form method="POST" action="{{ url_for('admin_delete', server_id=s.server_id) }}" style="display:inline;" onsubmit="return confirm('Удалить сервер?')">
                                <button class="btn btn-danger btn-sm">Удалить</button>
                            </form>
                        </td>
                    </tr>
                {% endfor %}
                </tbody>
            </table>
        {% else %}
            <h2>🖥 Мои серверы</h2>
            <div class="row">
                {% for s in user_servers %}
                    <div class="col-md-6 mb-3">
                        <div class="card bg-secondary text-light">
                            <div class="card-body">
                                <h5 class="card-title">{{ s.server_name }}</h5>
                                <p class="card-text">
                                    Тариф: {{ s.tariff }}<br>
                                    Доступен до: {{ s.expiry_date }} {{ s.expiry_time }} МСК<br>
                                    Статус: {% if is_expired(s) %}🔴 Истёк{% else %}🟢 Активен{% endif %}
                                </p>
                                <a href="{{ url_for('server_detail', server_id=s.server_id) }}" class="btn btn-primary">Управлять</a>
                            </div>
                        </div>
                    </div>
                {% endfor %}
            </div>
        {% endif %}
    </div>
</body>
</html>
"""

SERVER_DETAIL_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Сервер {{ server.server_name }}</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        .status-running { color: #3fb950; }
        .status-offline { color: #f85149; }
        .status-starting, .status-stopping { color: #d29922; }
    </style>
</head>
<body class="bg-dark text-light">
    <nav class="navbar navbar-expand-lg navbar-dark bg-black">
        <div class="container">
            <span class="navbar-brand">🖥 {{ server.server_name }}</span>
            <div class="ms-auto">
                <a href="{{ url_for('dashboard') }}" class="btn btn-outline-secondary btn-sm">Назад</a>
                <a href="{{ url_for('logout') }}" class="btn btn-outline-danger btn-sm">Выйти</a>
            </div>
        </div>
    </nav>
    <div class="container mt-4">
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, msg in messages %}
                    <div class="alert alert-{{ category }}">{{ msg }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}

        <div class="row">
            <div class="col-md-6">
                <h4>📊 Статус</h4>
                <ul class="list-group bg-dark">
                    <li class="list-group-item bg-secondary text-light">Тариф: {{ server.tariff }}</li>
                    <li class="list-group-item bg-secondary text-light">Доступен до: {{ server.expiry_date }} {{ server.expiry_time }} МСК</li>
                    <li class="list-group-item bg-secondary text-light">
                        Статус: <span class="status-{{ status_data.state }}">{{ status_data.state_label }}</span>
                        {% if is_expired(server) %} <span class="text-danger">⚠️ Истёк</span>{% endif %}
                    </li>
                    <li class="list-group-item bg-secondary text-light">CPU: {{ status_data.cpu }}%</li>
                    <li class="list-group-item bg-secondary text-light">RAM: {{ status_data.ram_mb }} МБ</li>
                    <li class="list-group-item bg-secondary text-light">Диск: {{ status_data.disk_mb }} МБ</li>
                </ul>
                <div class="mt-3">
                    {% if not is_expired(server) %}
                        <form method="POST" action="{{ url_for('power_action', server_id=server.server_id, action='start') }}" style="display:inline;">
                            <button class="btn btn-success">▶️ Запустить</button>
                        </form>
                        <form method="POST" action="{{ url_for('power_action', server_id=server.server_id, action='stop') }}" style="display:inline;">
                            <button class="btn btn-danger">⏹ Остановить</button>
                        </form>
                    {% else %}
                        <div class="alert alert-warning">⛔ Управление заблокировано – срок истёк</div>
                    {% endif %}
                </div>
            </div>
            <div class="col-md-6">
                <h4>📋 Логи</h4>
                <form method="POST" action="{{ url_for('view_logs', server_id=server.server_id) }}">
                    <button class="btn btn-info">Показать логи</button>
                </form>
                {% if logs %}
                    <pre class="bg-black text-light p-2 mt-2" style="max-height:200px; overflow-y:auto;">{{ logs }}</pre>
                {% endif %}
                <hr>
                <h4>📂 Файлы</h4>
                <a href="{{ url_for('files_page', server_id=server.server_id) }}" class="btn btn-primary">Управление файлами</a>
            </div>
        </div>
    </div>
</body>
</html>
"""

FILES_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Файлы {{ server.server_name }}</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body class="bg-dark text-light">
    <nav class="navbar navbar-expand-lg navbar-dark bg-black">
        <div class="container">
            <span class="navbar-brand">📂 Файлы: {{ server.server_name }}</span>
            <div class="ms-auto">
                <a href="{{ url_for('server_detail', server_id=server.server_id) }}" class="btn btn-outline-secondary btn-sm">Назад</a>
            </div>
        </div>
    </nav>
    <div class="container mt-4">
        <h4>Список файлов (корень)</h4>
        <ul class="list-group bg-dark">
            {% for entry in file_list %}
                <li class="list-group-item bg-secondary text-light">
                    {% if entry.is_file %}📄{% else %}📁{% endif %} {{ entry.name }} ({{ entry.size_str }})
                </li>
            {% else %}
                <li class="list-group-item bg-secondary text-light">Папка пуста</li>
            {% endfor %}
        </ul>

        <hr>
        <h5>📥 Скачать файл</h5>
        <form method="POST" action="{{ url_for('download_file', server_id=server.server_id) }}" class="row g-2">
            <div class="col-auto">
                <input type="text" name="filename" class="form-control" placeholder="имя_файла.py" required>
            </div>
            <div class="col-auto">
                <button class="btn btn-success">Скачать</button>
            </div>
        </form>

        <hr>
        <h5>📤 Загрузить файл или .zip</h5>
        <form method="POST" action="{{ url_for('upload_file', server_id=server.server_id) }}" enctype="multipart/form-data" class="row g-2">
            <div class="col-auto">
                <input type="file" name="file" class="form-control" required>
            </div>
            <div class="col-auto">
                <button class="btn btn-primary">Загрузить</button>
            </div>
        </form>
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, msg in messages %}
                    <div class="alert alert-{{ category }} mt-3">{{ msg }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}
    </div>
</body>
</html>
"""

# ------------------ Роуты ------------------
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = USERS.get(username)
        if user and user['password'] == password:
            session['username'] = username
            session['role'] = user['role']
            session['tg_id'] = user['tg_id']
            return redirect(url_for('dashboard'))
        else:
            flash('Неверный логин или пароль', 'danger')
    return render_template_string(LOGIN_TEMPLATE)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/')
def index():
    if 'username' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    user_tg = session['tg_id']
    role = session['role']
    if role == 'owner':
        all_servers = get_all_clients()
        return render_template_string(DASHBOARD_TEMPLATE, all_servers=all_servers, user_servers=[], is_expired=is_expired)
    else:
        user_servers = get_servers(user_tg)
        return render_template_string(DASHBOARD_TEMPLATE, all_servers=[], user_servers=user_servers, is_expired=is_expired)

@app.route('/server/<server_id>')
@login_required
def server_detail(server_id):
    client = get_server(session['tg_id'], server_id)
    if not client and session['role'] != 'owner':
        flash('Доступ запрещён', 'danger')
        return redirect(url_for('dashboard'))
    if not client:
        client = get_server_by_id(server_id)
        if not client:
            flash('Сервер не найден', 'danger')
            return redirect(url_for('dashboard'))
    # Получаем статус
    status_data = {'state': 'unknown', 'state_label': 'Неизвестно', 'cpu': 0, 'ram_mb': 0, 'disk_mb': 0}
    try:
        api = PterodactylClient(client.server_id, client.api_key)
        resources = asyncio.run(api.get_resources())
        attrs = resources.get('attributes', {})
        state = attrs.get('current_state', 'unknown')
        res = attrs.get('resources', {})
        status_data = {
            'state': state,
            'state_label': get_status_label(state),
            'cpu': res.get('cpu_absolute', 0),
            'ram_mb': res.get('memory_bytes', 0) / 1024 / 1024,
            'disk_mb': res.get('disk_bytes', 0) / 1024 / 1024
        }
    except Exception as e:
        flash(f'Ошибка получения статуса: {e}', 'warning')
    return render_template_string(SERVER_DETAIL_TEMPLATE, server=client, status_data=status_data, is_expired=is_expired, logs=None)

@app.route('/power/<server_id>/<action>', methods=['POST'])
@login_required
def power_action(server_id, action):
    client = get_server(session['tg_id'], server_id)
    if not client and session['role'] != 'owner':
        flash('Доступ запрещён', 'danger')
        return redirect(url_for('dashboard'))
    if not client:
        client = get_server_by_id(server_id)
        if not client:
            flash('Сервер не найден', 'danger')
            return redirect(url_for('dashboard'))
    if is_expired(client):
        flash('Срок аренды истёк, действие запрещено', 'danger')
        return redirect(url_for('server_detail', server_id=server_id))
    try:
        api = PterodactylClient(client.server_id, client.api_key)
        asyncio.run(api.send_power_signal(action))
        flash(f'Команда "{action}" отправлена', 'success')
    except Exception as e:
        flash(f'Ошибка: {e}', 'danger')
    return redirect(url_for('server_detail', server_id=server_id))

@app.route('/logs/<server_id>', methods=['POST'])
@login_required
def view_logs(server_id):
    client = get_server(session['tg_id'], server_id)
    if not client and session['role'] != 'owner':
        flash('Доступ запрещён', 'danger')
        return redirect(url_for('dashboard'))
    if not client:
        client = get_server_by_id(server_id)
    if not client:
        flash('Сервер не найден', 'danger')
        return redirect(url_for('dashboard'))
    try:
        api = PterodactylClient(client.server_id, client.api_key)
        lines = asyncio.run(api.get_console_logs(lines=300, listen_seconds=4.0))
        log_text = '\n'.join(lines) if lines else 'Консоль пуста'
    except Exception as e:
        log_text = f'Ошибка получения логов: {e}'
    # Получаем статус заново для отображения
    status_data = {'state': 'unknown', 'state_label': 'Неизвестно', 'cpu': 0, 'ram_mb': 0, 'disk_mb': 0}
    try:
        resources = asyncio.run(api.get_resources())
        attrs = resources.get('attributes', {})
        state = attrs.get('current_state', 'unknown')
        res = attrs.get('resources', {})
        status_data = {
            'state': state,
            'state_label': get_status_label(state),
            'cpu': res.get('cpu_absolute', 0),
            'ram_mb': res.get('memory_bytes', 0) / 1024 / 1024,
            'disk_mb': res.get('disk_bytes', 0) / 1024 / 1024
        }
    except:
        pass
    return render_template_string(SERVER_DETAIL_TEMPLATE, server=client, status_data=status_data, is_expired=is_expired, logs=log_text)

@app.route('/files/<server_id>')
@login_required
def files_page(server_id):
    client = get_server(session['tg_id'], server_id)
    if not client and session['role'] != 'owner':
        flash('Доступ запрещён', 'danger')
        return redirect(url_for('dashboard'))
    if not client:
        client = get_server_by_id(server_id)
    if not client:
        flash('Сервер не найден', 'danger')
        return redirect(url_for('dashboard'))
    file_list = []
    try:
        api = PterodactylClient(client.server_id, client.api_key)
        entries = asyncio.run(api.list_files('/'))
        for e in entries:
            size_str = f"{e.size_bytes} Б"
            if e.size_bytes >= 1024*1024:
                size_str = f"{e.size_bytes/1024/1024:.1f} МБ"
            elif e.size_bytes >= 1024:
                size_str = f"{e.size_bytes/1024:.0f} КБ"
            file_list.append({'name': e.name, 'is_file': e.is_file, 'size_str': size_str})
    except Exception as e:
        flash(f'Ошибка получения списка файлов: {e}', 'danger')
    return render_template_string(FILES_TEMPLATE, server=client, file_list=file_list)

@app.route('/download/<server_id>', methods=['POST'])
@login_required
def download_file(server_id):
    client = get_server(session['tg_id'], server_id)
    if not client and session['role'] != 'owner':
        flash('Доступ запрещён', 'danger')
        return redirect(url_for('dashboard'))
    if not client:
        client = get_server_by_id(server_id)
    if not client:
        flash('Сервер не найден', 'danger')
        return redirect(url_for('dashboard'))
    filename = request.form.get('filename')
    if not filename:
        flash('Имя файла не указано', 'danger')
        return redirect(url_for('files_page', server_id=server_id))
    try:
        api = PterodactylClient(client.server_id, client.api_key)
        url = asyncio.run(api.get_download_url(filename))
        # Скачиваем файл в память
        import aiohttp
        async def fetch():
            async with aiohttp.ClientSession() as sess:
                async with sess.get(url) as resp:
                    if resp.status != 200:
                        raise Exception(f'HTTP {resp.status}')
                    return await resp.read()
        file_data = asyncio.run(fetch())
        # Отправляем как вложение
        return send_file(
            io.BytesIO(file_data),
            as_attachment=True,
            download_name=filename
        )
    except Exception as e:
        flash(f'Ошибка скачивания: {e}', 'danger')
        return redirect(url_for('files_page', server_id=server_id))

@app.route('/upload/<server_id>', methods=['POST'])
@login_required
def upload_file(server_id):
    client = get_server(session['tg_id'], server_id)
    if not client and session['role'] != 'owner':
        flash('Доступ запрещён', 'danger')
        return redirect(url_for('dashboard'))
    if not client:
        client = get_server_by_id(server_id)
    if not client:
        flash('Сервер не найден', 'danger')
        return redirect(url_for('dashboard'))
    if 'file' not in request.files:
        flash('Файл не выбран', 'danger')
        return redirect(url_for('files_page', server_id=server_id))
    file = request.files['file']
    if file.filename == '':
        flash('Файл не выбран', 'danger')
        return redirect(url_for('files_page', server_id=server_id))
    filename = file.filename
    try:
        file_bytes = file.read()
        api = PterodactylClient(client.server_id, client.api_key)
        upload_url = asyncio.run(api.get_upload_url())
        asyncio.run(api.upload_file(upload_url, filename, file_bytes))
        if filename.lower().endswith('.zip'):
            asyncio.run(api.decompress_file(filename))
        # Перезагружаем сервер
        asyncio.run(api.send_power_signal('restart'))
        flash(f'Файл {filename} успешно загружен и сервер перезагружен', 'success')
    except Exception as e:
        flash(f'Ошибка загрузки: {e}', 'danger')
    return redirect(url_for('files_page', server_id=server_id))

# ------------------ Админские роуты ------------------
@app.route('/admin/extend/<server_id>/<int:days>', methods=['POST'])
@login_required
@admin_required
def admin_extend(server_id, days):
    srv = get_server_by_id(server_id)
    if not srv:
        flash('Сервер не найден', 'danger')
        return redirect(url_for('dashboard'))
    try:
        new_date = datetime.strptime(srv.expiry_date, "%d.%m.%Y") + timedelta(days=days)
        new_date_str = new_date.strftime("%d.%m.%Y")
        update_expiry_date(server_id, new_date_str)
        flash(f'Срок продлён на {days} дней', 'success')
    except Exception as e:
        flash(f'Ошибка: {e}', 'danger')
    return redirect(url_for('dashboard'))

@app.route('/admin/set_date/<server_id>', methods=['POST'])
@login_required
@admin_required
def admin_set_date(server_id):
    new_date = request.form.get('new_date')
    new_time = request.form.get('new_time')
    if not new_date or not new_time:
        flash('Дата и время обязательны', 'danger')
        return redirect(url_for('dashboard'))
    try:
        datetime.strptime(new_date, "%d.%m.%Y")
        datetime.strptime(new_time, "%H:%M")
    except:
        flash('Неверный формат (ДД.ММ.ГГГГ и ЧЧ:ММ)', 'danger')
        return redirect(url_for('dashboard'))
    update_expiry_date(server_id, new_date, new_time)
    flash('Дата и время обновлены', 'success')
    return redirect(url_for('dashboard'))

@app.route('/admin/delete/<server_id>', methods=['POST'])
@login_required
@admin_required
def admin_delete(server_id):
    srv = get_server_by_id(server_id)
    if not srv:
        flash('Сервер не найден', 'danger')
        return redirect(url_for('dashboard'))
    removed = remove_client(srv.tg_id, server_id)
    if removed:
        flash('Сервер удалён', 'success')
    else:
        flash('Ошибка удаления', 'danger')
    return redirect(url_for('dashboard'))

# ------------------ Запуск ------------------
if __name__ == '__main__':
    init_db()  # создаст таблицы, если их нет
    app.run(host='0.0.0.0', port=5000, debug=True)
