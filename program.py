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
                    st.error("Пароль має бути не менше 6 symbols.")
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
        
        selected_idx = 0
        for idx, meta in enumerate(metadatas):
            if meta.get("source") == "local_doc":
                selected_idx = idx
                break
                
        ans = documents[selected_idx]
        meta = metadatas[selected_idx]
        
        if not is_en: 
            ans = safe_translate_to_uk(ans)
            
        src = translations_dict["source_local" if meta.get("source") == "local_doc" else "source_cf"]
        return f"**Джерело:** {src} (ID: `{meta.get('source_id', meta.get('index', '?'))}`)\n\n{ans}"
        
    return "Відповідь не знайдена у локальній базі."

# --- ІНІЦІАЛІЗАЦІЯ СТАНУ СЕСІЇ ---
if "chat_archive" not in st.session_state:
    chats, trash, use_llm = load_all_data()
    st.session_state.chat_archive = chats
    st.session_state.trash_archive = trash
    st.session_state.use_llm_api = use_llm

defaults = {
    "current_chat_id": "New Chat",
    "previous_chat_id": "New Chat",
    "messages": [],
    "settings_mode": False,
    "language": "UA",
    "editing_msg_idx": None
}

for key, value in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = value

# ==========================================
# ВИПРАВЛЕНИЙ CSS-БЛОК (Стрілка бічної панелі тепер працює)
# ==========================================
st.markdown(
    "<style>"
    "[data-testid='stAppDeployButton'], [data-testid='stToolbarActions'] {display:none!important;} "
    "[data-testid='stToolbar'] {background: transparent!important;} "
    "[data-testid='stMainBlockContainer'] {padding-top:2rem!important;} "
    ".edit-btn button {padding:2px 8px!important; font-size:12px!important; min-height:24px!important;}"
    "</style>", 
    unsafe_allow_html=True
)

translations = {
    "UA": {"title": "Python AI Tutor", "menu": "📜 Ваші чати", "new_chat": "+ Новий чат", "settings": "⚙️ Налаштування", "back": "←", "rename": "✏️ Назва", "delete": "🗑️ Видалити", "input_placeholder": "Запитайте щось про Python...", "lang_label": "Мова", "save": "OK", "source_local": "🏠 Теорія", "source_cf": "🧠 Алгоритми", "trash_title": "🗑️ Кошик", "trash_empty": "Кошик порожній", "restore": "🔄 Відновити", "clear_trash": "🚨 Очистити кошик", "edit_msg": "✏️ Редагувати", "cancel": "Скасувати", "llm_toggle": "🤖 Використивувати Google Gemini (API)", "logout": "🚪 Вийти з акаунта"},
    "EN": {"title": "Python AI Tutor", "menu": "📜 Your Chats", "new_chat": "+ New Chat", "settings": "⚙️ Settings", "back": "←", "rename": "✏️ Rename", "delete": "🗑️ Delete", "input_placeholder": "Ask something about Python...", "lang_label": "Language", "save": "OK", "source_local": "🏠 Theory", "source_cf": "🧠 Algorithms", "trash_title": "🗑️ Trash Bin", "trash_empty": "Trash is empty", "restore": "🔄 Restore", "clear_trash": "🚨 Empty Trash", "edit_msg": "✏️ Edit", "cancel": "Cancel", "llm_toggle": "🤖 Use Google Gemini (API)", "logout": "🚪 Log Out"}
}
t = translations[st.session_state.language]

@st.cache_resource
def load_resources():
    try: 
        return SentenceTransformer('all-MiniLM-L6-v2'), chromadb.PersistentClient(path="./python_tutor_vector_db").get_collection(name="python_knowledge")
    except Exception: 
        return SentenceTransformer('all-MiniLM-L6-v2'), None

model, collection = load_resources()
st.set_page_config(
    page_title=t["title"], 
    page_icon="🎓", 
    layout="wide", 
    initial_sidebar_state="expanded"
)

def exit_settings():
    st.session_state.settings_mode = False
    st.session_state.current_chat_id = st.session_state.previous_chat_id
    if st.session_state.current_chat_id == "New Chat":
        st.session_state.messages = []
    else:
        st.session_state.messages = st.session_state.chat_archive.get(st.session_state.current_chat_id, [])
    st.session_state.editing_msg_idx = None

# ==========================================
# 3. ІНТЕРФЕЙС ТА СТРУКТУРА СТОРІНКИ (БІЧНА ПАНЕЛЬ)
# ==========================================
with st.sidebar:
    if IS_GUEST:
        st.markdown("👤 Режим: **Гість**")
    else:
        st.markdown(f"👤 Користувач: **{USER_FULL_NAME}**")
        
    st.write("---")

    if st.session_state.settings_mode:
        if st.button(t["back"], key="back_to_chat_btn", use_container_width=True):
            exit_settings()
            st.rerun()
        
    st.title(t["menu"])
    if st.button(t["new_chat"], use_container_width=True, type="primary"):
        st.session_state.current_chat_id = "New Chat"
        st.session_state.messages = []
        st.session_state.settings_mode = False
        st.session_state.editing_msg_idx = None
        st.session_state.previous_chat_id = "New Chat"
        st.rerun()
    
    st.write("---")
    
    for chat_id in reversed(list(st.session_state.chat_archive.keys())):
        cols = st.columns([0.85, 0.15])
        if cols[0].button(chat_id, key=f"sel_{chat_id}", use_container_width=True):
            st.session_state.current_chat_id = chat_id
            st.session_state.messages = st.session_state.chat_archive[chat_id]
            st.session_state.settings_mode = False
            st.session_state.editing_msg_idx = None
            st.session_state.previous_chat_id = chat_id
            st.rerun()
            
        with cols[1].popover("⋮"):
            if st.button(t["delete"], key=f"del_{chat_id}", use_container_width=True):
                st.session_state.trash_archive[chat_id] = st.session_state.chat_archive.pop(chat_id)
                save_all_data(st.session_state.chat_archive, st.session_state.trash_archive, st.session_state.use_llm_api)
                if st.session_state.current_chat_id == chat_id: 
                    st.session_state.current_chat_id = "New Chat"
                    st.session_state.messages = []
                    st.session_state.previous_chat_id = "New Chat"
                st.rerun()
                
            new_n = st.text_input(t["rename"], value=chat_id, key=f"inp_{chat_id}")
            if new_n and new_n != chat_id and st.button(t["save"], key=f"sv_{chat_id}"):
                st.session_state.chat_archive[new_n] = st.session_state.chat_archive.pop(chat_id)
                if st.session_state.current_chat_id == chat_id: 
                    st.session_state.current_chat_id = new_n
                if st.session_state.previous_chat_id == chat_id: 
                    st.session_state.previous_chat_id = new_n
                save_all_data(st.session_state.chat_archive, st.session_state.trash_archive, st.session_state.use_llm_api)
                st.rerun()

    st.markdown("<div style='height: 10vh'></div>", unsafe_allow_html=True)
    if st.button(t["settings"], use_container_width=True):
        if st.session_state.settings_mode: 
            exit_settings()
        else:
            st.session_state.previous_chat_id = st.session_state.current_chat_id
            st.session_state.settings_mode = True
            st.session_state.editing_msg_idx = None
        st.rerun()

# ==========================================
# 4. ОСНОВНИЙ ЕКРАН (НАЛАШТУВАННЯ АБО ЧАТ)
# ==========================================
if st.session_state.settings_mode:
    st.title(t["settings"])
    
    st.subheader("👤 Акаунт")
    if IS_GUEST:
        st.info("💡 Ви увійшли як гість. Створіть постійний акаунт, щоб зберегти ці чати.")
        with st.expander("📝 Зареєструвати цей акаунт та зберегти чати", expanded=False):
            with st.form("guest_registration_form"):
                g_username = st.text_input("Оберіть унікальний логін (англійською)*").strip().lower()
                g_name = st.text_input("Ваше ім'я та прізвище*")
                g_email = st.text_input("Email")
                g_password = st.text_input("Пароль*", type="password")
                g_password_repeat = st.text_input("Повторіть пароль*", type="password")
                submit_g_reg = st.form_submit_button("Створити постійний акаунт", type="primary")
                
                if submit_g_reg:
                    if not g_username or not g_name or not g_password:
                        st.error("Будь ласка, заповніть усі обов'язові поля (*)")
                    elif g_username in config['credentials']['usernames']:
                        st.error("Цей логін вже зайнятий!")
                    elif g_password != g_password_repeat:
                        st.error("Паролі не збігаються!")
                    elif len(g_password) < 6:
                        st.error("Пароль занадто короткий.")
                    else:
                        salt = bcrypt.gensalt()
                        hashed_password = bcrypt.hashpw(g_password.encode('utf-8'), salt).decode('utf-8')
                        
                        config['credentials']['usernames'][g_username] = {
                            'email': g_email,
                            'name': g_name,
                            'password': hashed_password
                        }
                        save_config(config)
                        
                        st.session_state["is_guest"] = False
                        st.session_state["username"] = g_username
                        st.session_state["name"] = g_name
                        st.session_state["authentication_status"] = True
                        
                        target_file = f"chat_history_{g_username}.json"
                        save_all_data(st.session_state.chat_archive, st.session_state.trash_archive, st.session_state.use_llm_api, force_file=target_file)
                        st.success("🎉 Акаунт успішно створено!")
                        time.sleep(1.5)
                        st.rerun()
                        
        if st.button(t["logout"] + " (Стерти чати)", type="primary", use_container_width=True):
            st.session_state.clear()
            st.rerun()
    else:
        authenticator.logout(t["logout"], 'main')
        
        if st.session_state.get("authentication_status") is None:
            st.session_state["is_guest"] = False
            st.session_state["auth_page"] = "login"
            st.session_state["messages"] = []
            st.session_state["current_chat_id"] = "New Chat"
            st.session_state["settings_mode"] = False
            st.rerun()
            
    st.write("---")
    new_lang = st.selectbox(t["lang_label"], options=["UA", "EN"], index=0 if st.session_state.language == "UA" else 1)
    if new_lang != st.session_state.language: 
        st.session_state.language = new_lang
        st.rerun()
    
    old_llm_setting = st.session_state.use_llm_api
    st.session_state.use_llm_api = st.toggle(t["llm_toggle"], value=st.session_state.use_llm_api)
    if old_llm_setting != st.session_state.use_llm_api:
        save_all_data(st.session_state.chat_archive, st.session_state.trash_archive, st.session_state.use_llm_api)
    
    st.write("---")
    st.subheader(t["trash_title"])
    if not st.session_state.trash_archive: 
        st.info(t["trash_empty"])
    else:
        if st.button(t["clear_trash"], type="secondary"):
            st.session_state.trash_archive = {}
            save_all_data(st.session_state.chat_archive, {}, st.session_state.use_llm_api)
            st.rerun()
            
        for t_id in list(st.session_state.trash_archive.keys()):
            t_cols = st.columns([0.7, 0.15, 0.15])
            t_cols[0].text(f"📁 {t_id}")
            if t_cols[1].button(t["restore"], key=f"res_{t_id}", use_container_width=True):
                st.session_state.chat_archive[t_id] = st.session_state.trash_archive.pop(t_id)
                save_all_data(st.session_state.chat_archive, st.session_state.trash_archive, st.session_state.use_llm_api)
                st.rerun()
            if t_cols[2].button(t["delete"], key=f"perm_{t_id}", use_container_width=True):
                st.session_state.trash_archive.pop(t_id)
                save_all_data(st.session_state.chat_archive, st.session_state.trash_archive, st.session_state.use_llm_api)
                st.rerun()
else:
    st.title(t["title"])
    if IS_GUEST:
        st.caption("⚠️ Ви увійшли як гість. Ця історія повідомлень буде стерта після закриття вкладки.")
    
    for idx, message in enumerate(st.session_state.messages):
        with st.chat_message(message["role"]):
            if message["role"] == "user" and st.session_state.editing_msg_idx == idx:
                new_text = st.text_area("Edit", value=message["content"], key=f"area_{idx}", label_visibility="collapsed")
                b_cols = st.columns([0.1, 0.1, 0.8])
                
                if b_cols[0].button(t["save"], key=f"sm_{idx}", type="primary") and new_text.strip() and new_text != message["content"]:
                    st.session_state.messages[idx]["content"] = new_text
                    if idx + 1 < len(st.session_state.messages) and st.session_state.messages[idx + 1]["role"] == "assistant":
                        st.session_state.messages[idx + 1]["content"] = get_bot_response(new_text, collection, model, t, st.session_state.use_llm_api)
                    if st.session_state.current_chat_id != "New Chat":
                        st.session_state.chat_archive[st.session_state.current_chat_id] = st.session_state.messages
                        save_all_data(st.session_state.chat_archive, st.session_state.trash_archive, st.session_state.use_llm_api)
                    st.session_state.editing_msg_idx = None
                    st.rerun()
                if b_cols[1].button(t["cancel"], key=f"cn_{idx}"): 
                    st.session_state.editing_msg_idx = None
                    st.rerun()
            else:
                st.markdown(message["content"])
                if message["role"] == "user" and st.session_state.editing_msg_idx is None:
                    st.markdown('<div class="edit-btn">', unsafe_allow_html=True)
                    if st.button(t["edit_msg"], key=f"trig_{idx}"): 
                        st.session_state.editing_msg_idx = idx
                        st.rerun()
                    st.markdown('</div>', unsafe_allow_html=True)

    if st.session_state.editing_msg_idx is None and (prompt := st.chat_input(t["input_placeholder"])):
        st.session_state.messages.append({"role": "user", "content": prompt})
        st.chat_message("user").markdown(prompt)
        
        with st.chat_message("assistant"):
            full_res = get_bot_response(prompt, collection, model, t, st.session_state.use_llm_api)
            res_box = st.empty()
            
            displayed_text = ""
            words = full_res.split(" ")
            for i, word in enumerate(words):
                displayed_text += word + (" " if i < len(words) - 1 else "")
                res_box.markdown(displayed_text + "▌")
                time.sleep(0.01)
            res_box.markdown(displayed_text)
            
            st.session_state.messages.append({"role": "assistant", "content": full_res})
            
        if st.session_state.current_chat_id == "New Chat":
            clean_prompt = prompt.strip()
            title = clean_prompt[:25] + "..." if len(clean_prompt) > 25 else clean_prompt
            base = title
            c = 1
            while title in st.session_state.chat_archive:
                title = f"{base} ({c})"
                c += 1
            st.session_state.current_chat_id = title
            st.session_state.previous_chat_id = title
            
        st.session_state.chat_archive[st.session_state.current_chat_id] = st.session_state.messages
        save_all_data(st.session_state.chat_archive, st.session_state.trash_archive, st.session_state.use_llm_api)
        st.rerun()
