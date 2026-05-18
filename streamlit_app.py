"""
Kuchnia — kucharski asystent
Stack: Streamlit + Google Gemini + Firebase Firestore (trwała baza)
"""
import streamlit as st
import google.generativeai as genai
from docx import Document
import json
import io
import re
import time

st.set_page_config(page_title="Kuchnia", page_icon="🍳", layout="centered")

# ── Klucz Gemini ─────────────────────────────────────────
try:
    GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"]
except (KeyError, FileNotFoundError):
    st.error("⚠️ Brak klucza GOOGLE_API_KEY w Streamlit Secrets")
    st.stop()

genai.configure(api_key=GOOGLE_API_KEY)
model = genai.GenerativeModel("gemini-2.5-flash")

# ── Firebase Firestore ───────────────────────────────────
COL_RECIPES  = "kuchnia_recipes"
COL_FRIDGE   = "kuchnia_fridge"
COL_SHOPPING = "kuchnia_shopping"
COL_META     = "kuchnia_meta"

def _fb_debug(msg):
    """Dopisuje krok do diagnostyki Firebase."""
    if "_firebase_debug" not in st.session_state:
        st.session_state["_firebase_debug"] = []
    st.session_state["_firebase_debug"].append(msg)

@st.cache_resource(show_spinner=False)
def get_db():
    """Łączy z Firebase. Zwraca None jeśli błąd."""
    debug = []
    try:
        debug.append("KROK 1: Próba importu firebase_admin...")
        import firebase_admin
        from firebase_admin import credentials, firestore
        debug.append("✓ KROK 1 OK — firebase_admin zaimportowany")

        if not firebase_admin._apps:
            debug.append("KROK 2: Pobieram FIREBASE_CREDS z Secrets...")
            raw = st.secrets.get("FIREBASE_CREDS")
            if not raw:
                # Może to sekcja TOML zamiast stringa?
                if "firebase" in st.secrets:
                    debug.append("✓ KROK 2 OK — znaleziono sekcję [firebase] (format TOML)")
                    creds_dict = dict(st.secrets["firebase"])
                else:
                    debug.append("✗ KROK 2 BŁĄD — Secrets nie zawiera ani FIREBASE_CREDS ani [firebase]")
                    st.session_state["_firebase_debug"] = debug
                    return None
            else:
                if isinstance(raw, str):
                    debug.append(f"✓ KROK 2 OK — pobrano string FIREBASE_CREDS ({len(raw)} znaków)")
                    debug.append("KROK 3: Parsuję JSON...")
                    # Wyczyść niewidzialne znaki które psują JSON
                    # \xa0 = twarda spacja (NBSP), \u200b = zero-width space, BOM
                    cleaned = raw.replace("\xa0", " ").replace("\u200b", "").replace("\ufeff", "")
                    if cleaned != raw:
                        debug.append(f"   Wyczyszczono niewidoczne znaki (NBSP itd.)")
                    try:
                        creds_dict = json.loads(cleaned)
                        debug.append(f"✓ KROK 3 OK — JSON sparsowany, klucze: {list(creds_dict.keys())[:5]}...")
                    except json.JSONDecodeError as je:
                        debug.append(f"✗ KROK 3 BŁĄD JSON: {je}")
                        debug.append(f"   Pierwsze 60 znaków raw: {repr(cleaned[:60])}")
                        debug.append(f"   Ostatnie 60 znaków raw: {repr(cleaned[-60:])}")
                        st.session_state["_firebase_debug"] = debug
                        st.session_state["_firebase_error"] = str(je)
                        return None
                else:
                    debug.append(f"✓ KROK 2 OK — pobrano obiekt (typ: {type(raw).__name__})")
                    creds_dict = dict(raw)

            debug.append(f"KROK 4: Sprawdzam wymagane pola...")
            required = ["type", "project_id", "private_key_id", "private_key", "client_email"]
            missing = [f for f in required if f not in creds_dict]
            if missing:
                debug.append(f"✗ KROK 4 BŁĄD — brakuje pól: {missing}")
                debug.append(f"   Pola które są: {list(creds_dict.keys())}")
                st.session_state["_firebase_debug"] = debug
                return None
            debug.append(f"✓ KROK 4 OK — wszystkie wymagane pola są")
            debug.append(f"   project_id = '{creds_dict.get('project_id', '?')}'")
            debug.append(f"   client_email = '{creds_dict.get('client_email', '?')[:40]}...'")
            pk = creds_dict.get("private_key", "")
            debug.append(f"   private_key zaczyna się od: {repr(pk[:30])}")
            debug.append(f"   private_key kończy się na: {repr(pk[-30:])}")
            debug.append(f"   liczba '\\n' w private_key: {pk.count(chr(92)+'n')}")
            debug.append(f"   liczba prawdziwych nowych linii: {pk.count(chr(10))}")

            debug.append("KROK 5: Tworzę credentials.Certificate...")
            cred = credentials.Certificate(creds_dict)
            debug.append("✓ KROK 5 OK — credentials utworzone")

            debug.append("KROK 6: initialize_app...")
            firebase_admin.initialize_app(cred)
            debug.append("✓ KROK 6 OK — Firebase zainicjalizowany")

        debug.append("KROK 7: Tworzę klienta Firestore...")
        client = firestore.client()
        debug.append("✓ KROK 7 OK — Firestore połączony! 🎉")
        st.session_state["_firebase_debug"] = debug
        return client
    except Exception as e:
        debug.append(f"✗ NIEOCZEKIWANY BŁĄD: {type(e).__name__}: {e}")
        st.session_state["_firebase_debug"] = debug
        st.session_state["_firebase_error"] = str(e)
        return None

db = get_db()
USING_FIREBASE = db is not None

# ── Stała baza domyślna ──────────────────────────────────
CATEGORIES = [
    {"id": "warzywa",     "label": "Warzywa i owoce",        "emoji": "🥬"},
    {"id": "mieso",       "label": "Mięso i ryby",           "emoji": "🥩"},
    {"id": "nabial",      "label": "Nabiał",                 "emoji": "🧀"},
    {"id": "polprodukty", "label": "Półprodukty",            "emoji": "📦"},
    {"id": "konserwy",    "label": "Konserwy i słoiki",      "emoji": "🥫"},
    {"id": "suche",       "label": "Suche, kasze, makarony", "emoji": "🍚"},
    {"id": "pieczenie",   "label": "Pieczenie i orzechy",    "emoji": "🥣"},
    {"id": "przyprawy",   "label": "Przyprawy i sosy",       "emoji": "🧂"},
    {"id": "tluszcze",    "label": "Tłuszcze",               "emoji": "🧈"},
    {"id": "inne",        "label": "Inne",                   "emoji": "🌿"},
]

DEFAULT_FRIDGE = [
    {"name": "por", "category": "warzywa"},
    {"name": "marchew", "category": "warzywa"},
    {"name": "papryka czerwona", "category": "warzywa"},
    {"name": "cytryna", "category": "warzywa"},
    {"name": "cebula", "category": "warzywa"},
    {"name": "szalotka", "category": "warzywa"},
    {"name": "czosnek", "category": "warzywa"},
    {"name": "seler", "category": "warzywa"},
    {"name": "pietruszka (korzeń)", "category": "warzywa"},
    {"name": "pietruszka (natka)", "category": "warzywa"},
    {"name": "mix sałat / rukola", "category": "warzywa"},
    {"name": "awokado", "category": "warzywa"},
    {"name": "pomidor", "category": "warzywa"},
    {"name": "bazylia", "category": "warzywa"},
    {"name": "grejpfrut", "category": "warzywa"},
    {"name": "banan", "category": "warzywa"},
    {"name": "kiwi", "category": "warzywa"},
    {"name": "mięso mielone", "category": "mieso"},
    {"name": "łosoś (filet)", "category": "mieso"},
    {"name": "mięso gotowane / pieczone (resztki)", "category": "mieso"},
    {"name": "jajka", "category": "nabial"},
    {"name": "mleko", "category": "nabial"},
    {"name": "śmietanka", "category": "nabial"},
    {"name": "jogurt", "category": "nabial"},
    {"name": "ser żółty", "category": "nabial"},
    {"name": "ser pleśniowy (camembert / brie)", "category": "nabial"},
    {"name": "twaróg / serek kanapkowy", "category": "nabial"},
    {"name": "makaron ugotowany", "category": "polprodukty"},
    {"name": "pierogi", "category": "polprodukty"},
    {"name": "Danonki", "category": "polprodukty"},
    {"name": "musztarda", "category": "konserwy"},
    {"name": "majonez", "category": "konserwy"},
    {"name": "ketchup", "category": "konserwy"},
    {"name": "oliwki", "category": "konserwy"},
    {"name": "oliwki czarne (słoik)", "category": "konserwy"},
    {"name": "dżem", "category": "konserwy"},
    {"name": "koncentrat / sos pomidorowy", "category": "konserwy"},
    {"name": "ogórki konserwowe / marynowane", "category": "konserwy"},
    {"name": "ciecierzyca (puszka)", "category": "konserwy"},
    {"name": "groszek konserwowy", "category": "konserwy"},
    {"name": "pomidory w puszce / pulpa", "category": "konserwy"},
    {"name": "mleczko kokosowe", "category": "konserwy"},
    {"name": "makaron", "category": "suche"},
    {"name": "makaron ryżowy", "category": "suche"},
    {"name": "ryż", "category": "suche"},
    {"name": "ryż do risotto", "category": "suche"},
    {"name": "kasza kuskus", "category": "suche"},
    {"name": "kasza pęczak", "category": "suche"},
    {"name": "kasza gryczana", "category": "suche"},
    {"name": "mąka", "category": "pieczenie"},
    {"name": "cukier puder", "category": "pieczenie"},
    {"name": "kakao", "category": "pieczenie"},
    {"name": "migdały / orzechy", "category": "pieczenie"},
    {"name": "pestki dyni", "category": "pieczenie"},
    {"name": "sos sojowy", "category": "przyprawy"},
    {"name": "sos Worcestershire", "category": "przyprawy"},
    {"name": "sos chili", "category": "przyprawy"},
    {"name": "sos BBQ", "category": "przyprawy"},
    {"name": "olej z czarnuszki", "category": "przyprawy"},
    {"name": "przyprawa do kurczaka", "category": "przyprawy"},
    {"name": "przyprawy podstawowe (sól, pieprz, liść laurowy…)", "category": "przyprawy"},
    {"name": "masło klarowane", "category": "tluszcze"},
    {"name": "masło / margaryna", "category": "tluszcze"},
    {"name": "olej", "category": "tluszcze"},
]

DEFAULT_EQUIPMENT = ["airfryer", "termomix", "piekarnik", "płyta indukcyjna"]

QUICK_PROMPTS = [
    "Łatwy obiad do pracy, airfryer, gotuję 7:00, jem 13:00",
    "Niedzielny obiad, mam czas na gotowanie",
    "Coś szybkiego na kolację",
    "Plan jedzenia na cały tydzień",
    "Coś na grilla dla 6 osób",
    "Urodziny dziecka — obiad i przekąski",
]

# ── Operacje na bazie ─────────────────────────────────────
def db_load_recipes():
    if not db:
        return []
    docs = db.collection(COL_RECIPES).stream()
    out = []
    for d in docs:
        r = d.to_dict()
        r["id"] = d.id
        out.append(r)
    return out

def db_save_recipe(recipe):
    if not db:
        return None
    rid = recipe.get("id") or f"r_{int(time.time()*1000)}_{len(recipe.get('name',''))}"
    doc_data = {k: v for k, v in recipe.items() if k != "id"}
    db.collection(COL_RECIPES).document(rid).set(doc_data)
    recipe["id"] = rid
    return rid

def db_delete_recipe(rid):
    if not db or not rid:
        return
    db.collection(COL_RECIPES).document(rid).delete()

def db_delete_all_recipes():
    if not db:
        return
    for d in db.collection(COL_RECIPES).stream():
        d.reference.delete()

def db_load_fridge():
    if not db:
        return None
    docs = list(db.collection(COL_FRIDGE).stream())
    if not docs:
        return None
    return [{**d.to_dict(), "_id": d.id} for d in docs]

def db_save_fridge_full(items):
    if not db:
        return
    for d in db.collection(COL_FRIDGE).stream():
        d.reference.delete()
    for it in items:
        db.collection(COL_FRIDGE).add({
            "name": it.get("name", ""),
            "category": it.get("category", "inne"),
            "amount": float(it.get("amount", 0) or 0),
            "unit": it.get("unit", ""),
        })

def db_load_shopping():
    if not db:
        return None
    docs = list(db.collection(COL_SHOPPING).stream())
    if not docs:
        return []
    return [{**d.to_dict(), "_id": d.id} for d in docs]

def db_save_shopping_full(items):
    if not db:
        return
    for d in db.collection(COL_SHOPPING).stream():
        d.reference.delete()
    for it in items:
        db.collection(COL_SHOPPING).add({
            "name": it.get("name", ""),
            "bought": bool(it.get("bought", False)),
        })

def db_load_equipment():
    if not db:
        return None
    doc = db.collection(COL_META).document("equipment").get()
    if not doc.exists:
        return None
    return doc.to_dict().get("items", DEFAULT_EQUIPMENT)

def db_save_equipment(items):
    if not db:
        return
    db.collection(COL_META).document("equipment").set({"items": items})

# ── Inicjalizacja stanu ───────────────────────────────────
def init_state():
    if st.session_state.get("_loaded"):
        return

    if USING_FIREBASE:
        st.session_state.recipes = db_load_recipes()

        fridge = db_load_fridge()
        if fridge is None:
            db_save_fridge_full(DEFAULT_FRIDGE)
            st.session_state.fridge = list(DEFAULT_FRIDGE)
        else:
            st.session_state.fridge = fridge

        eq = db_load_equipment()
        if eq is None:
            db_save_equipment(DEFAULT_EQUIPMENT)
            st.session_state.equipment = list(DEFAULT_EQUIPMENT)
        else:
            st.session_state.equipment = eq

        sh = db_load_shopping()
        st.session_state.shopping = sh if sh is not None else []
    else:
        st.session_state.recipes   = []
        st.session_state.fridge    = list(DEFAULT_FRIDGE)
        st.session_state.equipment = list(DEFAULT_EQUIPMENT)
        st.session_state.shopping  = []

    st.session_state._processed_files = set()
    st.session_state._loaded = True

init_state()

# ── Helpers ──────────────────────────────────────────────
def parse_docx(file_bytes):
    doc = Document(io.BytesIO(file_bytes))
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())

def call_gemini(prompt):
    response = model.generate_content(prompt)
    return response.text.strip()

def extract_json(text, kind="object"):
    cleaned = re.sub(r"```(?:json)?", "", text).strip()
    if kind == "array":
        s, e = cleaned.find("["), cleaned.rfind("]")
    else:
        s, e = cleaned.find("{"), cleaned.rfind("}")
    if s != -1 and e != -1:
        return json.loads(cleaned[s:e + 1])
    return json.loads(cleaned)

def normalize_name(name):
    return (name or "").strip().lower()

def add_to_shopping(items):
    existing = {x["name"].lower() for x in st.session_state.shopping}
    added = 0
    for ing in items:
        if ing and ing.lower() not in existing:
            st.session_state.shopping.append({"name": ing, "bought": False})
            existing.add(ing.lower())
            added += 1
    if USING_FIREBASE and added:
        db_save_shopping_full(st.session_state.shopping)
    return added

# ── Nagłówek ─────────────────────────────────────────────
st.markdown("# 🍳 Kuchnia")
st.caption("Twój kucharski asystent — Gemini AI")

if USING_FIREBASE:
    st.success("☁️ Połączono z Firebase — przepisy zapisują się automatycznie")
else:
    err = st.session_state.get("_firebase_error", "")
    st.warning(
        "⚠️ Firebase niedostępny — apka działa w trybie sesji "
        "(dane znikają po zamknięciu)."
        + (f"\n\nBłąd: {err}" if err else "")
    )

# 🔍 Okienko diagnostyczne Firebase (zawsze widoczne dopóki Firebase nie działa)
with st.expander("🔍 Firebase debug — kliknij żeby zobaczyć szczegóły", expanded=not USING_FIREBASE):
    debug_lines = st.session_state.get("_firebase_debug", [])
    if debug_lines:
        st.code("\n".join(debug_lines), language="text")
        st.caption("☝️ Skopiuj cały tekst powyżej i wyślij Claudeowi (klikając przycisk kopiowania w prawym górnym rogu okienka)")
    else:
        st.caption("Brak diagnostyki — uruchom apkę ponownie (Reboot app w Streamlit Cloud)")

tab_recipes, tab_fridge, tab_receipt, tab_ask, tab_shopping = st.tabs([
    "📖 Przepisy", "🥬 Lodówka", "🧾 Paragon", "✨ Zapytaj", "🛒 Zakupy",
])

# ─── PRZEPISY ────────────────────────────────────────────
with tab_recipes:
    st.subheader("Moje przepisy")
    n = len(st.session_state.recipes)
    st.caption(f"📚 {n} przepisów" if n else "Wgraj dokument Word — AI go odczyta.")

    uploaded = st.file_uploader("Wgraj plik .docx", type=["docx"], key="docx_uploader")
    if uploaded is not None:
        file_signature = f"{uploaded.name}_{uploaded.size}"
        if file_signature in st.session_state._processed_files:
            st.warning(
                f"⚠️ Plik **{uploaded.name}** był już wgrany w tej sesji — pomijam."
            )
        else:
            with st.spinner("Czytam dokument…"):
                try:
                    text = parse_docx(uploaded.read())
                    if not text.strip():
                        st.error("Pusty dokument.")
                    else:
                        with st.spinner("Analizuję przepisy (10–30 sek)…"):
                            prompt = f"""Wyodrębnij wszystkie przepisy z tekstu. Zwróć WYŁĄCZNIE czysty JSON, bez markdown. Format:
[{{"name":"nazwa","category":"śniadanie|obiad|kolacja|deser|przekąska|inne","time":liczba_minut,"tags":["łatwy","airfryer","mięsne","wege"],"ingredients":[{{"name":"składnik","amount":"ilość"}}],"instructions":"kroki","tools":["airfryer","termomix","piekarnik","płyta indukcyjna"]}}]

Polski. Czas w minutach (szacuj jeśli brak).

TEKST:
{text[:25000]}"""
                            raw = call_gemini(prompt)
                            new_recipes = extract_json(raw, kind="array")

                            existing_names = {
                                normalize_name(r.get("name", ""))
                                for r in st.session_state.recipes
                            }
                            added_recipes = []
                            skipped_count = 0
                            for r in new_recipes:
                                nm = normalize_name(r.get("name", ""))
                                if not nm or nm in existing_names:
                                    skipped_count += 1
                                    continue
                                if USING_FIREBASE:
                                    db_save_recipe(r)
                                else:
                                    r["id"] = f"r_{int(time.time()*1000)}_{len(added_recipes)}"
                                added_recipes.append(r)
                                existing_names.add(nm)

                            st.session_state.recipes.extend(added_recipes)
                            st.session_state._processed_files.add(file_signature)

                            if added_recipes and skipped_count:
                                st.success(
                                    f"✓ Dodano {len(added_recipes)} nowych. "
                                    f"Pominięto {skipped_count} duplikatów."
                                )
                            elif added_recipes:
                                st.success(f"✓ Dodano {len(added_recipes)} przepisów")
                            else:
                                st.warning(
                                    f"Nic nie dodano — {skipped_count} przepisów już jest."
                                )
                            st.rerun()
                except Exception as e:
                    st.error(f"Błąd: {e}")

    with st.expander("💾 Backup / Przywracanie / Wyczyść wszystko"):
        col1, col2 = st.columns(2)
        with col1:
            if st.session_state.recipes:
                st.download_button(
                    "📥 Pobierz backup",
                    data=json.dumps(st.session_state.recipes, ensure_ascii=False, indent=2),
                    file_name=f"kuchnia-{int(time.time())}.json",
                    mime="application/json",
                    use_container_width=True,
                )
            else:
                st.caption("Brak przepisów do zapisania.")
        with col2:
            backup = st.file_uploader("Wgraj backup", type=["json"], key="backup_upload",
                                       label_visibility="collapsed")
            if backup is not None:
                try:
                    data = json.loads(backup.read())
                    if isinstance(data, list):
                        if USING_FIREBASE:
                            for r in data:
                                db_save_recipe(r)
                        st.session_state.recipes = data if not USING_FIREBASE else db_load_recipes()
                        st.success("✓ Przywrócono")
                        st.rerun()
                except Exception as e:
                    st.error(f"Błąd: {e}")

        st.markdown("---")
        st.markdown("**🗑️ Strefa niebezpieczna**")
        st.caption("Usuwa wszystkie przepisy. Pobierz backup zanim klikniesz!")
        confirm = st.checkbox("Tak, na pewno", key="confirm_clear")
        if confirm and st.button("🗑️ USUŃ WSZYSTKIE PRZEPISY", use_container_width=True):
            if USING_FIREBASE:
                db_delete_all_recipes()
            st.session_state.recipes = []
            st.session_state._processed_files = set()
            st.session_state["confirm_clear"] = False
            st.success("✓ Wyczyszczono")
            st.rerun()

    if st.session_state.recipes:
        st.markdown("---")
        for r in st.session_state.recipes:
            label = f"**{r.get('name','?')}**  ·  {r.get('category','')}  ·  ~{r.get('time','?')} min"
            with st.expander(label):
                if r.get("tags"):
                    st.caption("🏷️ " + "  ·  ".join(r["tags"]))
                if r.get("tools"):
                    st.caption("🔧 " + "  ·  ".join(r["tools"]))
                if r.get("ingredients"):
                    st.markdown("**Składniki:**")
                    for ing in r["ingredients"]:
                        st.markdown(f"- {ing.get('name','')}  —  *{ing.get('amount','')}*")
                if r.get("instructions"):
                    st.markdown("**Przygotowanie:**")
                    st.markdown(r["instructions"])
                if st.button("🗑️ Usuń", key=f"del_{r.get('id','')}"):
                    if USING_FIREBASE:
                        db_delete_recipe(r.get("id"))
                    st.session_state.recipes = [
                        x for x in st.session_state.recipes if x.get("id") != r.get("id")
                    ]
                    st.rerun()

# ─── LODÓWKA ─────────────────────────────────────────────
with tab_fridge:
    st.subheader("Lodówka i sprzęt")

    st.markdown("#### 🍳 Sprzęt")
    if st.session_state.equipment:
        eq_cols = st.columns(min(4, len(st.session_state.equipment)))
        for i, e in enumerate(st.session_state.equipment):
            with eq_cols[i % len(eq_cols)]:
                if st.button(f"❌ {e}", key=f"eq_{i}_{e}", use_container_width=True):
                    st.session_state.equipment = [x for x in st.session_state.equipment if x != e]
                    if USING_FIREBASE:
                        db_save_equipment(st.session_state.equipment)
                    st.rerun()

    with st.form("add_eq", clear_on_submit=True):
        c1, c2 = st.columns([4, 1])
        with c1:
            new_eq = st.text_input("Sprzęt", placeholder="np. wok…", label_visibility="collapsed")
        with c2:
            submit_eq = st.form_submit_button("Dodaj", use_container_width=True)
        if submit_eq and new_eq.strip():
            name = new_eq.strip()
            if name.lower() not in [e.lower() for e in st.session_state.equipment]:
                st.session_state.equipment.append(name)
                if USING_FIREBASE:
                    db_save_equipment(st.session_state.equipment)
                st.rerun()

    st.markdown("---")
    st.markdown("#### Dodaj produkt ręcznie")
    with st.form("add_fridge", clear_on_submit=True):
        c1, c2, c3, c4, c5 = st.columns([3, 2, 1, 1, 1])
        with c1:
            new_item = st.text_input("Produkt", placeholder="np. tofu…", label_visibility="collapsed")
        with c2:
            cat_options = {f"{c['emoji']} {c['label']}": c["id"] for c in CATEGORIES}
            sel = st.selectbox("Kat.", list(cat_options.keys()), label_visibility="collapsed")
        with c3:
            new_amount = st.number_input("Ilość", min_value=0.0, value=1.0, step=0.5,
                                          label_visibility="collapsed")
        with c4:
            new_unit = st.selectbox("Jedn.", ["szt", "g", "kg", "ml", "l", "opak"],
                                     label_visibility="collapsed")
        with c5:
            submit_fr = st.form_submit_button("➕", use_container_width=True)
        if submit_fr and new_item.strip():
            name = new_item.strip()
            existing = next(
                (f for f in st.session_state.fridge if f["name"].lower() == name.lower()),
                None
            )
            if existing:
                # dodaj do istniejącego
                existing["amount"] = float(existing.get("amount", 0) or 0) + float(new_amount)
                existing["unit"] = new_unit
            else:
                st.session_state.fridge.append({
                    "name": name,
                    "category": cat_options[sel],
                    "amount": float(new_amount),
                    "unit": new_unit,
                })
            if USING_FIREBASE:
                db_save_fridge_full(st.session_state.fridge)
            st.rerun()

    st.markdown("---")
    st.caption("💡 Klikaj **➖** żeby zmniejszyć (np. po przepisie), **❌** żeby usunąć produkt całkiem.")

    for cat in CATEGORIES:
        items = [f for f in st.session_state.fridge if f.get("category") == cat["id"]]
        if not items:
            continue
        st.markdown(f"##### {cat['emoji']} {cat['label']}  ·  {len(items)}")
        for i, item in enumerate(items):
            amount = item.get("amount")
            unit = item.get("unit", "")
            if amount is not None and amount > 0:
                # formatuj ładnie ilość
                amount_str = f"{int(amount)}" if amount == int(amount) else f"{amount:.2f}".rstrip("0").rstrip(".")
                label = f"**{item['name']}** — {amount_str} {unit}"
            else:
                label = f"**{item['name']}** — *(brak ilości)*"
            cols = st.columns([5, 1, 1, 1])
            with cols[0]:
                st.markdown(label)
            with cols[1]:
                if st.button("➖", key=f"fr_minus_{cat['id']}_{i}_{item['name']}",
                             help="Zmniejsz ilość o 1"):
                    if amount and amount > 1:
                        item["amount"] = amount - 1
                    else:
                        item["amount"] = 0
                    if USING_FIREBASE:
                        db_save_fridge_full(st.session_state.fridge)
                    st.rerun()
            with cols[2]:
                if st.button("➕", key=f"fr_plus_{cat['id']}_{i}_{item['name']}",
                             help="Zwiększ ilość o 1"):
                    item["amount"] = float(amount or 0) + 1
                    if not item.get("unit"):
                        item["unit"] = "szt"
                    if USING_FIREBASE:
                        db_save_fridge_full(st.session_state.fridge)
                    st.rerun()
            with cols[3]:
                if st.button("❌", key=f"fr_del_{cat['id']}_{i}_{item['name']}",
                             help="Usuń produkt z lodówki"):
                    st.session_state.fridge = [
                        x for x in st.session_state.fridge if x["name"] != item["name"]
                    ]
                    if USING_FIREBASE:
                        db_save_fridge_full(st.session_state.fridge)
                    st.rerun()

# ─── PARAGON ─────────────────────────────────────────────
with tab_receipt:
    st.subheader("🧾 Wgraj paragon Biedronki")
    st.caption(
        "Wgraj plik **JSON** z e-paragonu Biedronki. "
        "AI rozpozna produkty, kategorie i ilości — Ty wybierzesz, które mają trafić do lodówki."
    )

    receipt_file = st.file_uploader(
        "Wgraj plik JSON z paragonu",
        type=["json", "txt"],
        key="receipt_uploader",
    )

    # Analiza paragonu
    if receipt_file is not None and "_receipt_analyzed" not in st.session_state:
        with st.spinner("Analizuję paragon (Gemini, ~20 sek)…"):
            try:
                raw_content = receipt_file.read().decode("utf-8", errors="ignore")

                # Wyciągnij pozycje z JSON-a Biedronki
                # Struktura: data.dokument.paragon.pozycja[].towar lub body[].sellLine
                items_extracted = []
                try:
                    # Spróbuj kilku formatów
                    parsed = json.loads(raw_content)

                    def find_items(obj, found):
                        if isinstance(obj, dict):
                            # sellLine ma name, price, total, quantity
                            if "name" in obj and "price" in obj and ("quantity" in obj or "total" in obj):
                                found.append(obj)
                            # towar ma nazwa, cena, ilosc, brutto
                            elif "nazwa" in obj and ("cena" in obj or "brutto" in obj):
                                found.append({
                                    "name": obj.get("nazwa", ""),
                                    "price": obj.get("cena", 0),
                                    "total": obj.get("brutto", obj.get("cena", 0)),
                                    "quantity": obj.get("ilosc", "1"),
                                })
                            else:
                                for v in obj.values():
                                    find_items(v, found)
                        elif isinstance(obj, list):
                            for v in obj:
                                find_items(v, found)
                    find_items(parsed, items_extracted)
                except Exception:
                    pass

                # Jeśli nie znalazł w JSON, spróbuj wyciągnąć z raw text przez Gemini
                if not items_extracted:
                    # Wyślij całość do Gemini do interpretacji
                    extract_prompt = f"""Z tego paragonu wyciągnij wszystkie pozycje (sprzedane produkty).
Zwróć WYŁĄCZNIE czysty JSON, bez markdown. Format:
[{{"name":"oryginalna nazwa z paragonu","quantity":"ilość","total_groszy":liczba}}]

PARAGON:
{raw_content[:15000]}"""
                    raw_out = call_gemini(extract_prompt)
                    items_extracted = extract_json(raw_out, kind="array")

                if not items_extracted:
                    st.error("Nie znalazłam żadnych pozycji w tym pliku.")
                    st.stop()

                # Teraz Gemini analizuje całą listę i klasyfikuje produkty
                items_text = "\n".join(
                    f"- {it.get('name', '?')}  ilosc:{it.get('quantity', '?')}"
                    for it in items_extracted
                )
                cat_list = "|".join(c["id"] for c in CATEGORIES)

                analyze_prompt = f"""Jestem klientem Biedronki. Mam listę pozycji z paragonu z bardzo skróconymi nazwami.
Twoje zadanie:
1. Rozszyfrować każdą nazwę (pełna nazwa po polsku)
2. Oznaczyć typ:
   - "food" = jedzenie do lodówki/spiżarni (chleb, jajka, mięso, warzywa, jogurty, ser, makaron itd.)
   - "snack" = drobne przekąski/słodycze które się zje w 1-2 dni (batoniki, herbatniki, ciastka, lizaki)
   - "non_food" = nie jedzenie (lampki, zabawki, kosmetyki, kaucja za butelkę)
3. Przypisać kategorię z listy: {cat_list}
4. Wyciągnąć ilość i jednostkę. Dla wagi (np "0,620") jednostka = "kg" (lub "g" jak <1).
   Dla sztuk (np "2") jednostka = "szt".

Zwróć WYŁĄCZNIE czysty JSON bez markdown, w tej samej kolejności co pozycje:
[
  {{
    "original_name": "BorówkaDriscolls125g",
    "full_name": "Borówki Driscoll's 125g",
    "type": "food",
    "category": "warzywa",
    "amount": 125,
    "unit": "g"
  }}
]

POZYCJE:
{items_text[:12000]}"""

                raw_analysis = call_gemini(analyze_prompt)
                analyzed = extract_json(raw_analysis, kind="array")

                # Połącz oryginał z analizą
                receipt_items = []
                for i, orig in enumerate(items_extracted):
                    if i < len(analyzed):
                        a = analyzed[i]
                        receipt_items.append({
                            "original_name": orig.get("name", a.get("original_name", "?")),
                            "full_name": a.get("full_name", orig.get("name", "?")),
                            "type": a.get("type", "food"),
                            "category": a.get("category", "inne"),
                            "amount": a.get("amount", 1),
                            "unit": a.get("unit", "szt"),
                            "selected": a.get("type", "food") == "food",  # domyślnie food zaznaczone
                        })

                st.session_state["_receipt_items"] = receipt_items
                st.session_state["_receipt_analyzed"] = True
                st.rerun()
            except Exception as e:
                st.error(f"Błąd analizy paragonu: {e}")

    # Reset
    if "_receipt_items" in st.session_state:
        if st.button("🔄 Wgraj inny paragon", use_container_width=False):
            st.session_state.pop("_receipt_items", None)
            st.session_state.pop("_receipt_analyzed", None)
            st.rerun()

    # Wyświetl wyniki analizy
    receipt_items = st.session_state.get("_receipt_items", [])
    if receipt_items:
        food_count = sum(1 for r in receipt_items if r["type"] == "food")
        snack_count = sum(1 for r in receipt_items if r["type"] == "snack")
        nonfood_count = sum(1 for r in receipt_items if r["type"] == "non_food")
        st.success(
            f"✓ Znalazłam **{len(receipt_items)}** pozycji: "
            f"🥕 {food_count} jedzenia, 🍪 {snack_count} przekąsek, 🚫 {nonfood_count} innych"
        )
        st.caption("Zaznacz co chcesz dodać do lodówki. Możesz edytować nazwę i ilość przed dodaniem.")

        st.markdown("---")
        for idx, r in enumerate(receipt_items):
            type_emoji = {"food": "🥕", "snack": "🍪", "non_food": "🚫"}.get(r["type"], "❓")
            cat = next((c for c in CATEGORIES if c["id"] == r.get("category")), CATEGORIES[-1])

            cols = st.columns([1, 4, 2, 2])
            with cols[0]:
                r["selected"] = st.checkbox(
                    "✓",
                    value=r.get("selected", False),
                    key=f"rcp_sel_{idx}",
                    label_visibility="collapsed"
                )
            with cols[1]:
                st.markdown(f"{type_emoji} **{r['full_name']}**")
                st.caption(f"({r['original_name']}) · {cat['emoji']} {cat['label']}")
            with cols[2]:
                r["amount"] = st.number_input(
                    "Ilość",
                    min_value=0.0,
                    value=float(r.get("amount", 1)),
                    step=0.1,
                    key=f"rcp_amt_{idx}",
                    label_visibility="collapsed"
                )
            with cols[3]:
                units = ["szt", "g", "kg", "ml", "l", "opak"]
                cur_unit = r.get("unit", "szt")
                r["unit"] = st.selectbox(
                    "Jedn.",
                    units,
                    index=units.index(cur_unit) if cur_unit in units else 0,
                    key=f"rcp_unit_{idx}",
                    label_visibility="collapsed"
                )

        st.markdown("---")
        selected_count = sum(1 for r in receipt_items if r.get("selected"))
        if st.button(
            f"💾 Dodaj {selected_count} zaznaczonych produktów do lodówki",
            type="primary",
            use_container_width=True,
            disabled=selected_count == 0,
        ):
            added = 0
            updated = 0
            for r in receipt_items:
                if not r.get("selected"):
                    continue
                # Sprawdź czy taki produkt już jest
                existing = next(
                    (f for f in st.session_state.fridge
                     if f["name"].lower() == r["full_name"].lower()),
                    None
                )
                if existing:
                    existing["amount"] = float(existing.get("amount", 0) or 0) + float(r["amount"])
                    existing["unit"] = r["unit"]
                    existing["category"] = r.get("category", existing.get("category", "inne"))
                    updated += 1
                else:
                    st.session_state.fridge.append({
                        "name": r["full_name"],
                        "category": r.get("category", "inne"),
                        "amount": float(r["amount"]),
                        "unit": r["unit"],
                    })
                    added += 1
            if USING_FIREBASE:
                db_save_fridge_full(st.session_state.fridge)
            st.session_state.pop("_receipt_items", None)
            st.session_state.pop("_receipt_analyzed", None)
            st.success(f"✓ Dodano {added} nowych, zaktualizowano {updated} istniejących")
            time.sleep(1)
            st.rerun()

# ─── ZAPYTAJ ─────────────────────────────────────────────
with tab_ask:
    st.subheader("Co dziś gotujemy?")
    query = st.text_area(
        "Pytanie",
        placeholder="np. Łatwy obiad do pracy, airfryer, gotuję 7:00, jem 13:00…",
        height=100,
        label_visibility="collapsed",
    )

    c1, c2 = st.columns([3, 2])
    with c1:
        st.caption(f"📖 {len(st.session_state.recipes)}  ·  🥬 {len(st.session_state.fridge)}  ·  🍳 {len(st.session_state.equipment)}")
    with c2:
        ask_clicked = st.button("✨ Zapytaj", type="primary", use_container_width=True)

    st.markdown("**Szybkie pomysły:**")
    qcols = st.columns(2)
    for i, p in enumerate(QUICK_PROMPTS):
        with qcols[i % 2]:
            if st.button(p, key=f"qp_{i}", use_container_width=True):
                st.session_state["_auto_query"] = p
                st.rerun()

    final_query = None
    if "_auto_query" in st.session_state:
        final_query = st.session_state.pop("_auto_query")
    elif ask_clicked and query.strip():
        final_query = query.strip()

    if final_query:
        with st.spinner("Myślę…"):
            try:
                if st.session_state.recipes:
                    rs = "\n".join(
                        f"• {r.get('name','?')} [{r.get('category','')}, ~{r.get('time','?')}min, "
                        f"składniki: {', '.join(i.get('name','') for i in r.get('ingredients', []))}]"
                        for r in st.session_state.recipes
                    )
                else:
                    rs = "(brak własnych przepisów)"

                # Lista z ilościami jeśli są
                fridge_items = []
                for f in st.session_state.fridge:
                    amt = f.get("amount")
                    unit = f.get("unit", "")
                    if amt and amt > 0:
                        amt_str = f"{int(amt)}" if amt == int(amt) else f"{amt:.2f}".rstrip("0").rstrip(".")
                        fridge_items.append(f"{f['name']} ({amt_str} {unit})")
                    else:
                        fridge_items.append(f["name"])
                fs = ", ".join(fridge_items) or "(pusto)"
                es = ", ".join(st.session_state.equipment) or "(brak)"
                vc = "|".join(c["id"] for c in CATEGORIES)

                prompt = f"""Jesteś moim osobistym kucharzem.

ZAPYTANIE: "{final_query}"

MOJE PRZEPISY:
{rs}

W LODÓWCE / SPIŻARNI:
{fs}

SPRZĘT:
{es}

ZASADY:
- Preferuj moje przepisy. Jeśli nie pasują → zaproponuj nowy.
- Wykorzystuj sprzęt który mam.
- "missing_ingredients" = jednorazowe rzeczy do dokupienia.
- "worth_for_pantry" = produkty warto trzymać NA STAŁE, z kategorią z: {vc}.

Zwróć WYŁĄCZNIE czysty JSON, bez markdown:
{{
  "summary": "1-2 zdania",
  "suggestions": [
    {{
      "name": "nazwa",
      "from_my_recipes": true/false,
      "why": "krótko czemu",
      "time": liczba_minut_lub_null,
      "missing_ingredients": ["..."],
      "worth_for_pantry": [{{"name":"...","category":"{vc}"}}],
      "when_to_prepare": "..."
    }}
  ]
}}"""
                raw = call_gemini(prompt)
                resp = extract_json(raw, kind="object")
                st.session_state["_last_response"] = resp
            except Exception as e:
                st.session_state["_last_response"] = {"error": str(e)}

    resp = st.session_state.get("_last_response")
    if resp:
        st.markdown("---")
        if "error" in resp:
            st.error(f"Błąd: {resp['error']}")
        else:
            if resp.get("summary"):
                st.info(resp["summary"])

            for idx, s in enumerate(resp.get("suggestions", [])):
                with st.container(border=True):
                    title = s.get("name", "?")
                    if s.get("from_my_recipes"):
                        title = f"⭐ {title}"
                    st.markdown(f"### {title}")

                    meta = []
                    if s.get("time"):
                        meta.append(f"⏱️ {s['time']} min")
                    if s.get("from_my_recipes"):
                        meta.append("📖 z moich")
                    if meta:
                        st.caption("  ·  ".join(meta))

                    if s.get("why"):
                        st.write(s["why"])
                    if s.get("when_to_prepare"):
                        st.markdown(f"**🗓️ Kiedy:** {s['when_to_prepare']}")

                    missing = s.get("missing_ingredients") or []
                    if missing:
                        st.markdown("**🛒 Do dokupienia:**")
                        st.write("  ·  ".join(missing))
                        if st.button("Dodaj do listy zakupów",
                                     key=f"add_shop_{idx}_{s.get('name','')}",
                                     use_container_width=True):
                            n = add_to_shopping(missing)
                            st.success(f"Dodano {n} ✓")

                    pantry = s.get("worth_for_pantry") or []
                    if pantry:
                        st.markdown("**⭐ Warto na stałe:**")
                        for pi, p in enumerate(pantry):
                            cat = next(
                                (c for c in CATEGORIES if c["id"] == p.get("category")),
                                CATEGORIES[-1]
                            )
                            in_fridge = any(
                                f["name"].lower() == p.get("name", "").lower()
                                for f in st.session_state.fridge
                            )
                            cols = st.columns([5, 2])
                            with cols[0]:
                                st.markdown(f"{cat['emoji']} **{p.get('name','')}** *· {cat['label']}*")
                            with cols[1]:
                                if in_fridge:
                                    st.caption("✓ już mam")
                                else:
                                    if st.button("➕",
                                                 key=f"add_pantry_{idx}_{pi}_{p.get('name','')}",
                                                 use_container_width=True):
                                        cat_id = p.get("category") if any(
                                            c["id"] == p.get("category") for c in CATEGORIES
                                        ) else "inne"
                                        st.session_state.fridge.append({
                                            "name": p.get("name", ""),
                                            "category": cat_id,
                                            "amount": 0,
                                            "unit": "",
                                        })
                                        if USING_FIREBASE:
                                            db_save_fridge_full(st.session_state.fridge)
                                        st.rerun()

# ─── ZAKUPY ──────────────────────────────────────────────
with tab_shopping:
    st.subheader("Lista zakupów")

    # ─── ✨ Inteligentna lista zakupów ─────────────────
    with st.expander("✨ Wygeneruj inteligentną listę zakupów", expanded=False):
        st.caption(
            "Napisz co planujesz gotować — AI sprawdzi co masz w lodówce, "
            "wybierze przepisy i powie czego brakuje."
        )

        plan = st.text_area(
            "Twój plan",
            placeholder="np. Obiady na 5 dni dla 4 osób. Coś szybkiego, dużo warzyw.",
            height=80,
            key="shop_plan_input",
            label_visibility="collapsed",
        )

        QUICK_SHOP_PROMPTS = [
            "Obiady na 5 dni dla 2 osób",
            "Zakupy na cały tydzień (śniadania, obiady, kolacje)",
            "Coś na weekend — gości będzie 6",
            "Lunchbox do pracy na 5 dni",
        ]
        st.caption("Szybkie pomysły:")
        scols = st.columns(2)
        for i, qp in enumerate(QUICK_SHOP_PROMPTS):
            with scols[i % 2]:
                if st.button(qp, key=f"shopqp_{i}", use_container_width=True):
                    st.session_state["_auto_shop_plan"] = qp
                    st.rerun()

        gen_clicked = st.button(
            "✨ Wygeneruj listę zakupów",
            type="primary",
            use_container_width=True,
        )

        final_plan = None
        if "_auto_shop_plan" in st.session_state:
            final_plan = st.session_state.pop("_auto_shop_plan")
        elif gen_clicked and plan.strip():
            final_plan = plan.strip()

        if final_plan:
            with st.spinner("Myślę — analizuję lodówkę i przepisy…"):
                try:
                    # Lista przepisów do wyboru
                    if st.session_state.recipes:
                        rs_lines = []
                        for r in st.session_state.recipes:
                            ings = ", ".join(
                                i.get("name", "") for i in r.get("ingredients", [])
                            )
                            rs_lines.append(
                                f"• {r.get('name','?')} [{r.get('category','')}, "
                                f"~{r.get('time','?')}min] — składniki: {ings}"
                            )
                        rs = "\n".join(rs_lines)
                    else:
                        rs = "(brak własnych przepisów)"

                    # Lodówka z ilościami
                    fridge_lines = []
                    for f in st.session_state.fridge:
                        amt = f.get("amount")
                        unit = f.get("unit", "")
                        if amt and amt > 0:
                            amt_str = (f"{int(amt)}" if amt == int(amt)
                                       else f"{amt:.2f}".rstrip("0").rstrip("."))
                            fridge_lines.append(f"{f['name']} ({amt_str} {unit})")
                        else:
                            fridge_lines.append(f["name"])
                    fs = ", ".join(fridge_lines) or "(pusto)"
                    es = ", ".join(st.session_state.equipment) or "(brak)"

                    shop_prompt = f"""Jesteś moim osobistym kucharzem-asystentem.

MÓJ PLAN: "{final_plan}"

MOJE PRZEPISY:
{rs}

W LODÓWCE / SPIŻARNI (z ilościami):
{fs}

SPRZĘT: {es}

ZADANIE:
1. Wybierz 3–7 konkretnych przepisów z moich, które pasują do mojego planu
   (lub zaproponuj nowe jeśli moje nie pasują).
2. Dla każdego sprawdź, których składników mi brakuje lub kończy się.
3. Wygeneruj listę zakupów: nazwa, szacowana ilość, do którego przepisu.
4. Pomiń to co już mam w wystarczającej ilości.
5. Dodatkowo: jeśli widzisz że produkty się kończą (mało w lodówce) — dopisz do listy.

Zwróć WYŁĄCZNIE czysty JSON, bez markdown:
{{
  "summary": "1-2 zdania jakie posiłki planujesz",
  "recipes_planned": [
    {{"name": "Nazwa przepisu", "from_my_recipes": true/false, "day": "Pn/Wt/..."}}
  ],
  "shopping_list": [
    {{
      "name": "Nazwa produktu",
      "amount": "ilość np. 500g lub 2 szt",
      "category": "warzywa|mieso|nabial|polprodukty|konserwy|suche|pieczenie|przyprawy|tluszcze|inne",
      "reason": "do czego: np. Pad Thai + Risotto",
      "running_low": true/false
    }}
  ],
  "tips": "1-2 zdania jeśli masz dobrą radę (np. 'sezam się kończy, kup zapas')"
}}"""

                    raw_shop = call_gemini(shop_prompt)
                    shop_resp = extract_json(raw_shop, kind="object")
                    st.session_state["_last_shop_response"] = shop_resp
                except Exception as e:
                    st.session_state["_last_shop_response"] = {"error": str(e)}

        # Wyświetl wynik inteligentnej listy
        shop_resp = st.session_state.get("_last_shop_response")
        if shop_resp:
            if "error" in shop_resp:
                st.error(f"Błąd: {shop_resp['error']}")
            else:
                if shop_resp.get("summary"):
                    st.info(shop_resp["summary"])

                # Plan posiłków
                if shop_resp.get("recipes_planned"):
                    st.markdown("**📅 Planowane przepisy:**")
                    for rp in shop_resp["recipes_planned"]:
                        day = rp.get("day", "")
                        star = "⭐" if rp.get("from_my_recipes") else "✨"
                        day_str = f"**{day}:** " if day else ""
                        st.markdown(f"- {day_str}{star} {rp.get('name', '?')}")

                # Lista zakupów
                shop_list = shop_resp.get("shopping_list", [])
                if shop_list:
                    st.markdown("---")
                    st.markdown(f"**🛒 Lista zakupów ({len(shop_list)} pozycji):**")

                    # Pogrupuj po kategorii
                    by_cat = {}
                    for item in shop_list:
                        cat = item.get("category", "inne")
                        by_cat.setdefault(cat, []).append(item)

                    for cat_id, items in by_cat.items():
                        cat_info = next(
                            (c for c in CATEGORIES if c["id"] == cat_id),
                            CATEGORIES[-1]
                        )
                        st.markdown(f"##### {cat_info['emoji']} {cat_info['label']}")
                        for item in items:
                            low_marker = " ⚠️" if item.get("running_low") else ""
                            st.markdown(
                                f"- **{item.get('name', '?')}** — "
                                f"{item.get('amount', '')}{low_marker}"
                            )
                            if item.get("reason"):
                                st.caption(f"  → {item['reason']}")

                    if shop_resp.get("tips"):
                        st.markdown(f"💡 *{shop_resp['tips']}*")

                    st.markdown("---")
                    if st.button(
                        f"➕ Dodaj wszystkie {len(shop_list)} pozycji do listy zakupów",
                        type="primary",
                        use_container_width=True,
                    ):
                        names = [
                            f"{it.get('name', '')} ({it.get('amount', '')})".strip()
                            for it in shop_list
                            if it.get("name")
                        ]
                        n = add_to_shopping(names)
                        st.session_state.pop("_last_shop_response", None)
                        st.success(f"✓ Dodano {n} pozycji do listy zakupów")
                        time.sleep(1)
                        st.rerun()

    st.markdown("---")
    remaining = [s for s in st.session_state.shopping if not s.get("bought")]
    bought = [s for s in st.session_state.shopping if s.get("bought")]

    if st.session_state.shopping:
        st.caption(f"🛒 {len(remaining)}  ·  ✓ {len(bought)}")
    else:
        st.caption("Pusto. Dodaj produkt ręcznie poniżej lub kliknij ✨ Wygeneruj listę powyżej.")

    with st.form("add_shop", clear_on_submit=True):
        c1, c2 = st.columns([4, 1])
        with c1:
            new_shop = st.text_input("Produkt", placeholder="dodaj…", label_visibility="collapsed")
        with c2:
            submit_shop = st.form_submit_button("➕", use_container_width=True)
        if submit_shop and new_shop.strip():
            add_to_shopping([new_shop.strip()])
            st.rerun()

    if remaining:
        st.markdown("#### Do kupienia")
        for i, item in enumerate(st.session_state.shopping):
            if item.get("bought"):
                continue
            cols = st.columns([1, 8, 1])
            with cols[0]:
                if st.button("☐", key=f"chk_{i}_{item['name']}"):
                    st.session_state.shopping[i]["bought"] = True
                    if USING_FIREBASE:
                        db_save_shopping_full(st.session_state.shopping)
                    st.rerun()
            with cols[1]:
                st.markdown(item["name"])
            with cols[2]:
                if st.button("🗑️", key=f"del_shop_{i}_{item['name']}"):
                    del st.session_state.shopping[i]
                    if USING_FIREBASE:
                        db_save_shopping_full(st.session_state.shopping)
                    st.rerun()

    if bought:
        st.markdown("#### W koszyku")
        for i, item in enumerate(st.session_state.shopping):
            if not item.get("bought"):
                continue
            cols = st.columns([1, 8])
            with cols[0]:
                if st.button("✓", key=f"unchk_{i}_{item['name']}"):
                    st.session_state.shopping[i]["bought"] = False
                    if USING_FIREBASE:
                        db_save_shopping_full(st.session_state.shopping)
                    st.rerun()
            with cols[1]:
                st.markdown(f"~~{item['name']}~~")

        if st.button("🗑️ Wyczyść kupione", use_container_width=True):
            st.session_state.shopping = [
                s for s in st.session_state.shopping if not s.get("bought")
            ]
            if USING_FIREBASE:
                db_save_shopping_full(st.session_state.shopping)
            st.rerun()
