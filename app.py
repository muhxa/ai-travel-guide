import os
import requests
from flask import Flask, request, jsonify, session, render_template
from flask_sqlalchemy import SQLAlchemy  # библиотека для работы с базой данных
from werkzeug.security import generate_password_hash, check_password_hash  # для шифрования паролей
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()  # загружаем настройки

app = Flask(__name__)
app.secret_key = "secret-key"  # ключ, чтобы сайт помнил, кто вошел

# Подключение к базе данных PostgreSQL
app.config['SQLALCHEMY_DATABASE_URI'] = "postgresql://postgres@localhost/travel_db"
db = SQLAlchemy(app)  # создаем инструмент для работы с базой


# Таблицы

class User(db.Model):
    #Таблица с пользователями
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)  # уникальный номер
    username = db.Column(db.String(80), unique=True)  # логин
    password = db.Column(db.String(200))  # зашифрованный пароль


class History(db.Model):
    #Таблица истории запросов
    __tablename__ = 'history'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer)  # кто спросил
    country = db.Column(db.String(100))  # про какую страну
    question = db.Column(db.Text)  # вопрос
    answer = db.Column(db.Text)  # ответ ИИ


# При запуске создаем таблицы, если их нет
with app.app_context():
    db.create_all()


# Вспомогательные функции

def get_country(name):
    #Получает данные  (REST Countries API)
    try:
        # Делаем запрос к внешнему сайту
        r = requests.get(f"https://restcountries.com/v3.1/name/{name}", timeout=10)
        data = r.json()[0]  # берем первый результат
        return {
            "name": data['name']['common'],
            "capital": data.get('capital', ['N/A'])[0],
            "currencies": "Информация есть",
            "languages": "Информация есть",
            "population": data.get('population', 0)
        }
    except:
        return None  # если ошибка или страна не найдена


def ask_ai(question):
    #Отправляет вопрос в локальный ИИ (Ollama)
    try:
        # Стучимся в программу Ollama на твоем компьютере
        r = requests.post("http://localhost:11434/api/chat", json={
            "model": "mistral",  # имя модели
            "messages": [{"role": "user", "content": question}],
            "stream": False  # ждем полный ответ
        }, timeout=60)
        return r.json()['message']['content']
    except:
        return "Ошибка подключения к ИИ. Проверь, запущена ли Ollama."


# Маршруты (Страницы сайта)

@app.route("/")
def index():
    #Главная страница
    user = None
    # Если пользователь входил, ищем его в базе по ID из сессии
    if "uid" in session:
        user = db.session.get(User, session["uid"])

    # Передаем имя пользователя в HTML шаблон
    return render_template("index.html", username=user.username if user else None)


@app.route("/login", methods=["POST"])
def login():
    #Вход в систему
    data = request.get_json()
    u = data.get("username")
    p = data.get("password")

    # Ищем пользователя в базе
    user = User.query.filter_by(username=u).first()

    # Если пользователя нет — ошибка
    if not user:
        return jsonify({"error": "Пользователь не найден. Зарегистрируйтесь."}), 404

    # Если пароль не подошел — ошибка
    if not check_password_hash(user.password, p):
        return jsonify({"error": "Неверный пароль"}), 401

    # Запоминаем ID пользователя в сессии (вход выполнен)
    session["uid"] = user.id
    return jsonify({"success": True})


@app.route("/register", methods=["POST"])
def register():
    #Регистрация нового пользователя
    data = request.get_json()
    u = data.get("username")
    p = data.get("password")

    # Проверка: а нет ли уже такого пользователя?
    existing_user = User.query.filter_by(username=u).first()
    if existing_user:
        return jsonify({"error": "Такой пользователь уже есть"}), 409

    # Создаем нового пользователя и шифруем пароль
    new_user = User(username=u, password=generate_password_hash(p))

    try:
        db.session.add(new_user)
        db.session.commit()  # Сохраняем в базу
    except Exception as e:
        db.session.rollback()  # Если ошибка — отменяем изменения
        return jsonify({"error": "Ошибка базы данных"}), 500

    # Сразу входим под ним
    session["uid"] = new_user.id
    return jsonify({"success": True})

@app.route("/logout", methods=["POST"])
def logout():
    #Выход из системы
    session.clear()  # очищаем память о пользователе
    return jsonify({"success": True})

@app.route("/ask", methods=["POST"])
def ask():
    #Обработка вопроса пользователя
    # Проверка: если не вошел в систему, доступ запрещен
    if "uid" not in session:
        return jsonify({"error": "Войдите в систему"}), 401

    data = request.get_json()
    country_name = data.get("country")
    q = data.get("query")

    # Шаг 1: Получаем факты о стране через внешний API
    info = get_country(country_name)
    if not info:
        return jsonify({"error": "Страна не найдена"}), 404

    # Шаг 2: Формируем вопрос для ИИ и получаем ответ
    prompt = f"Расскажи про {country_name}. Вопрос туриста: {q}. Отвечай подробно на русском."
    answer = ask_ai(prompt)

    # Шаг 3: Сохраняем историю в базу данных PostgreSQL
    h = History(user_id=session["uid"], country=info['name'], question=q, answer=answer)

    try:
        db.session.add(h)  # добавляем запись
        db.session.commit()  # сохраняем изменения
    except Exception as e:
        db.session.rollback()
        print(f"Ошибка сохранения: {e}")

    # Шаг 4: Отправляем ответ обратно на сайт
    return jsonify({"answer": answer, "country_info": info})


if __name__ == "__main__":
    print("Сайт запущен: http://127.0.0.1:5000")
    app.run(debug=True)