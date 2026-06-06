import os #для API
import requests
from flask import Flask, request, jsonify, session, render_template
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = "secret-key"
# подяключаем к базе данных
app.config['SQLALCHEMY_DATABASE_URI'] = "postgresql://postgres@localhost/travel_db"
db = SQLAlchemy(app)


CITIES_DB = {
    "france": ["Париж", "Ницца", "Лион", "Марсель", "Бордо", "Страсбург"],
    "italy": ["Рим", "Милан", "Венеция", "Флоренция", "Неаполь"],
    "spain": ["Мадрид", "Барселона", "Валенсия", "Севилья"],
    "germany": ["Берлин", "Мюнхен", "Гамбург", "Кёльн"],
    "japan": ["Токио", "Киото", "Осака", "Хиросима", "Саппоро"],
    "united states of america": ["Нью-Йорк", "Лос-Анджелес", "Чикаго", "Майами", "Лас-Вегас"],
    "thailand": ["Бангкок", "Пхукет", "Паттайя", "Чиангмай"],
    "turkey": ["Стамбул", "Анталья", "Анкара", "Измир"],
    "egypt": ["Каир", "Шарм-эль-Шейх", "Хургада", "Луксор"],
    "united kingdom": ["Лондон", "Манчестер", "Ливерпуль", "Эдинбург"],
    "russia": ["Москва", "Санкт-Петербург", "Казань", "Сочи"]
}


class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True)
    password = db.Column(db.String(200))


class History(db.Model):
    __tablename__ = 'history'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer)
    country = db.Column(db.String(100))
    question = db.Column(db.Text)
    answer = db.Column(db.Text)


with app.app_context():
    db.create_all()


def get_country(name):
    try:
        clean_name = name.strip().lower() #красивый ввод без лишних пробелов и с мал буквы
        import urllib.parse
        encoded_name = urllib.parse.quote(clean_name) #спец символы для ссылки

        # Пробуем найти страну
        r = requests.get(f"https://restcountries.com/v3.1/name/{encoded_name}?fullText=false", timeout=15)

        if r.status_code != 200:
            return None

        data = r.json()[0] #первый красивый словарь с поиска берём
#ДОП для городов
        # Определяем ключ для поиска городов
        api_name = data['name']['common'].lower()

        cities = []
        if clean_name in CITIES_DB: #проверка по исходному вводу
            cities = CITIES_DB[clean_name]
        elif api_name in CITIES_DB: # проверка по красивому вводу
            cities = CITIES_DB[api_name]

        return {
            "name": data['name']['common'],
            "capital": data.get('capital', ['Нет данных'])[0],
            "languages": ", ".join(data.get('languages', {}).values()) if data.get('languages') else "Нет данных",
            "currencies": ", ".join([c['name'] for c in data.get('currencies', {}).values()]) if data.get(
                'currencies') else "Нет данных",
            "cities": cities  # Передаем список городов
        }

    except Exception as e: #если стрчока - ошибка, не падает сайт
        print(f"Ошибка API: {e}")
        return None


def ask_ai(question):
    try:
        api_key = os.getenv("MISTRAL_API_KEY") #ищем ключ в .env
        if not api_key:
            return "Ошибка: API ключ не найден."

        r = requests.post(
            "https://api.mistral.ai/v1/chat/completions",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
            json={
                "model": "mistral-small-latest",
                "messages": [{"role": "user", "content": question}]
            }
        )
        return r.json()['choices'][0]['message']['content']
    except Exception as e:
        return f"Ошибка ИИ: {str(e)}"


@app.route("/") #запускает функцию главной страницы когда кто то на моём адресе
def index():
    user = None
    if "uid" in session: #условие uid в спец словаре
        user = db.session.get(User, session["uid"]) #ищем в базе
    return render_template("index.html", username=user.username if user else None)


@app.route("/login", methods=["POST"])#post прячет данные внутри запроса
def login():
    data = request.get_json()
    u = data.get("username")
    p = data.get("password")
    user = User.query.filter_by(username=u).first() #sql-запрос
    if not user:
        return jsonify({"error": "Пользователь не найден"}), 404
    if not check_password_hash(user.password, p):
        return jsonify({"error": "Неверный пароль"}), 401
    session["uid"] = user.id
    return jsonify({"success": True})


@app.route("/register", methods=["POST"])#post прячет данные внутри запроса
def register():
    data = request.get_json()
    u = data.get("username")
    p = data.get("password")
    if User.query.filter_by(username=u).first(): #User.query -обрщанеи к таблцие пользователей
        return jsonify({"error": "Такой пользователь уже есть"}), 409
    new_user = User(username=u, password=generate_password_hash(p))
    try:
        db.session.add(new_user)# висит в памяти
        db.session.commit()# сохраняем
    except:
        db.session.rollback()
        return jsonify({"error": "Ошибка БД"}), 500
    session["uid"] = new_user.id
    return jsonify({"success": True})


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"success": True})


@app.route("/ask", methods=["POST"])
def ask():
    if "uid" not in session:
        return jsonify({"error": "Войдите в систему"}), 401

    data = request.get_json()
    country_name = data.get("country")
    q = data.get("query")

    # Получаем данные о стране (включая список городов)
    info = get_country(country_name)
    if not info:
        return jsonify({"error": "Страна не найдена"}), 404

    # Формируем умный запрос
    city_context = f" (город: {data.get('city', 'вся страна')})" if data.get('city') else ""

    prompt_text = (
        f"Ты — эксперт-консультант по путешествиям.\n"
        f"Страна: {info['name']}{city_context}.\n"
        f"Вопрос туриста: '{q}'\n\n"
        f"ЗАДАЧА:\n"
        f"1. Дай ответ в 3-4 предложенияименно на этот вопрос.\n"
        f"2. В конце добавь блок 'Полезные контакты:' со ссылкой, телефоном и советом.\n"
        f"Пиши на русском. Не используй жирный шрифт (**) и (##)."
    )

    answer = ask_ai(prompt_text)
    answer = answer.replace("**", "").replace("\n", "<br>")

    h = History(user_id=session["uid"], country=info['name'], question=q, answer=answer)
    try:
        db.session.add(h)
        db.session.commit()
    except:
        db.session.rollback()

    return jsonify({"answer": answer, "country_info": info})


if __name__ == "__main__":
    print("Сайт: http://127.0.0.1:5000")
    app.run(debug=True)
