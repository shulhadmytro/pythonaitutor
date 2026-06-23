import streamlit as st
import streamlit_authenticator as stauth
import yaml
from yaml.loader import SafeLoader
import chromadb
from sentence_transformers import SentenceTransformer
from deep_translator import GoogleTranslator
import json
import os
import time
import requests
import bcrypt

# ==========================================
# ХЕЛПЕРИ ДЛЯ РОБОТИ З ФАЙЛАМИ
# ==========================================
def save_config(config_data):
    """Безпечне збереження конфігурації користувачів."""
    try:
        with open('config.yaml', 'w', encoding='utf-8') as f:
            yaml.dump(config_data, f, default_flow_style=False, allow_unicode=True)
    except Exception as e:
        st.error(f"Помилка збереження конфігурації: {e}")

def load_all_data():
    """Завантаження історії чатів та налаштувань."""
    if IS_GUEST or not HISTORY_FILE or not os.path.exists(HISTORY_FILE):
        return {}, {}, False
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data.get("chats", {}), data.get("trash", {}), data.get("use_llm_api", False)
    except (json.JSONDecodeError, IOError):
        return {}, {}, False
    return {}, {}, False

def save_all_data(chats, trash, use_llm_api, force_file=None):
    """Збереження даних користувача на диск."""
    file_to_save = force_file or HISTORY_FILE
    if (IS_GUEST and not force_file) or not file_to_save:
        return 
    try:
        with open(file_to_save, "w", encoding="utf-8") as f:
            json.dump({"chats": chats, "trash": trash, "use_llm_api": use_llm_api}, f, ensure_ascii=False, indent=4)
    except Exception as e:
        st.error(f"Помилка збереження історії: {e}")

# ==========================================
# 1. ЗАВАНТАЖЕННЯ КОНФІГУРАЦІЇ ТА АВТЕНТИФІКАЦІЯ
# ==========================================
try:
    with open('config.yaml', 'r', encoding='utf-8') as file:
        config = yaml.load(file, Loader=SafeLoader) or {}
except FileNotFoundError:
    st.error("Помилка: Файл 'config.yaml' не знадено! Створіть його поруч із program.py.")
    st.stop()

if 'credentials' not in config:
    config['credentials'] = {'usernames': {}}
if 'usernames' not in config['credentials']:
    config['credentials']['usernames'] = {}

config['cookie'] = {'name': 'auth_cookie_v3_navigation', 'key': 'signature_key_v3', 'expiry_days': 30}

authenticator = stauth.Authenticate(
    config['credentials'],
    config['cookie']['name'],
    config['cookie']['key'],
    config['cookie']['expiry_days']
)

if "is_guest" not in st.session_state:
    st.session_state["is_guest"] = False

if "auth_page" not in st.session_state:
    st.session_state["auth_page"] = "login"

# Перевірка чи активована авторизація користувача
if not st.session_state.get("authentication_status") and not st.session_state["is_guest"]:
    st.title("🎓 Python AI Tutor")
    
    if st.session_state["auth_page"] == "login":
        st.subheader("🔐 Вхід в акаунт")
        authenticator.login(location='main')
        
        if st.session_state["authentication_status"] is False:
            st.error('Неправильний логін або пароль')
            
        st.write("---")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("📝 Створити новий акаунт", use_container_width=True):
                st.session_state["auth_page"] = "register"
                st.rerun()
        with col2:
            if st.button("🚀 Увійти як гість", use_container_width=True):
                st.session_state["is_guest"] = True
                st.session_state["username"] = "guest"
                st.session_state["name"] = "Гість"
                st.rerun()
                
    elif st.session_state["auth_page"] == "register":
        st.subheader("📝 Створення нового акаунта")
        with st.form("registration_form"):
            new_username = st.text_input("Оберіть унікальний логін (англійською)*").strip().lower()
            new_name = st.text_input("Ваше ім'я та прізвище*")
            new_email = st.text_input("Email")
            new_password = st.text_input("Пароль*", type="password")
            new_password_repeat = st.text_input("Повторіть пароль*", type="password")
            submit_reg = st.form_submit_button("Зареєструватися та увійти", type="primary")
            
            if submit_reg:
                if not new_username or not new_name or not new_password:
                    st.error("Будь ласка, заповніть усі обов'язові поля (*)")
                elif new_username in config['credentials']['usernames']:
                    st.error("Цей логін вже зайнятий!")
                elif new_password != new_password_repeat:
                    st.error("Паролі не збігаються!")
                elif len(new_password) < 6:
                    st.error("Пароль має бути не менше 6 символів.")
                else:
                    salt = bcrypt.gensalt()
                    hashed_password = bcrypt.hashpw(new_password.encode('utf-8'), salt).decode('utf-8')
                    
                    config['credentials']['usernames'][new_username] = {
                        'email': new_email,
                        'name': new_name,
                        'password': hashed_password
                    }
                    save_config(config)
                    st.session_state["authentication_status"] = True
                    st.session_state["username"] = new_username
                    st.session_state["name"] = new_name
                    st.success("🎉 Акаунт успішно створено!")
                    time.sleep(1)
                    st.rerun()
                    
        if st.button("← Повернутися до вікна входу", use_container_width=True):
            st.session_state["auth_page"] = "login"
            st.rerun()
            
    st.stop()

# Гарантуємо дефолтні значення, якщо користувач вийшов або зайшов як гість
USERNAME = st.session_state.get("username", "guest")
USER_FULL_NAME = st.session_state.get("name", "Гість")
IS_GUEST = st.session_state.get("is_guest", False)
HISTORY_FILE = None if IS_GUEST else f"chat_history_{USERNAME}.json"

API_KEY = "ВАШ_GEMINI_API_КЛЮЧ" 
API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={API_KEY}"

# ==========================================
# 2. ФУНКЦІЇ РОБОТИ З API ТА ВЕКТОРНОЮ БАЗОЮ
# ==========================================
def call_external_llm(prompt):
    if API_KEY == "ВАШ_GEMINI_API_КЛЮЧ":
        return "⚠️ Будь ласка, вкажіть діючий API Ключ у коді програми (`API_KEY`), щоб використовувати Google Gemini."
    
    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [{"parts": [{"text": f"You are a helpful Python AI Tutor. Answer precisely. User question: {prompt}"}]}],
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 1000}
    }
    try:
        response = requests.post(API_URL, headers=headers, json=payload, timeout=12)
        if response.status_code == 200:
            return response.json()['candidates'][0]['content']['parts'][0]['text']
        return f"Помилка Gemini API (Код {response.status_code}): {response.text}"
    except Exception as e:
        return f"Не вдалося зв'язатися з Gemini API: {e}"

def safe_translate_to_uk(text):
    if not text:
        return ""
    try:
        translator = GoogleTranslator(source='en', target='uk')
        if len(text) < 3500:
            return translator.translate(text)
            
        paragraphs = text.split("\n")
        translated_paragraphs = []
        current_chunk = ""
        
        for para in paragraphs:
            if len(current_chunk) + len(para) + 1 < 3500:
                current_chunk += para + "\n"
            else:
                if current_chunk.strip():
                    translated_paragraphs.append(translator.translate(current_chunk))
                current_chunk = para + "\n"
                
        if current_chunk.strip():
            translated_paragraphs.append(translator.translate(current_chunk))
            
        return "\n".join(translated_paragraphs)
    except Exception as e:
        return f"⚠️ [Помилка автоматичного перекладу: {e}]\n\n{text}"

def get_bot_response(prompt, collection_obj, model_obj, translations_dict, use_llm_api):
    if use_llm_api:
        return f"🤖 **Відповідь від Google Gemini (API):**\n\n{call_external_llm(prompt)}"
        
    if not collection_obj: 
        return "Database Error: Векторна база даних недоступна."
        
    is_en = all(ord(c) < 128 for c in prompt.replace(" ", ""))
    search_query = prompt if is_en else GoogleTranslator(source='auto', target='en').translate(prompt)
    
    res = collection_obj.query(query_embeddings=[model_obj.encode(search_query).tolist()], n_results=3)
    
    if res['documents'] and res['documents'][0]:
        documents = res['documents'][0]
        metadatas = res['metadatas'][0]
        
        selected_idx =
