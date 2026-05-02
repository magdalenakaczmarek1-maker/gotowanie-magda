"""
Kuchnia — kucharski asystent
Stack: Streamlit + Gemini (Vertex AI) + Firebase Firestore
"""
import streamlit as st
import vertexai
from vertexai.generative_models import GenerativeModel
from google.cloud import firestore
from google.oauth2 import service_account
from docx import Document
import json
import io
import re
import time

# ── Konfiguracja strony ──────────────────────────────────
st.set_page_config(page_title="Kuchnia", page_icon="🍳", layout="centered")

# ── Sekrety ──────────────────────────────────────────────
def need(key):
    try:
        return st.secrets[key]
    except (KeyError, FileNotFoundError):
        st.error(f"⚠️ Brak sekretu: `{key}` — ustaw w Streamlit Cloud → Settings → Secrets")
        st.stop()

ADMIN_PASSWORD       = need("ADMIN_PASSWORD")
GCP_PROJECT_ID       = need("GCP_PROJECT_ID")
GCP_LOCATION         = st.secrets.get("GCP_LOCATION", "us-central1")
FIREBASE_CREDS_JSON  = need("FIREBASE_CREDS")
MODEL_NAME           = st.secrets.get("VERTEX_MODEL", "gemini-2.5-flash")

# ── Inicjalizacja Vertex + Firestore ─────────────────────
@st.cache_resource
def get_clients():
    creds_dict = json.loads(FIREBASE_CREDS_JSON)
    creds = service_account.Credentials.from_service_account_info(
        creds_dict,
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
    )
    vertexai.init(project=GCP_PROJECT_ID, location=GCP_LOCATION, credentials=creds)
    model = GenerativeModel(MODEL_NAME)
    db = firestore.Client(project=GCP_PROJECT_ID, credentials=creds)
    return model, db

try:
    gemini, db = get_clients()
except Exception as e:
    st.error(f"❌ Błąd Google Cloud: {e}")
    st.markdown("""
**Sprawdź:**
- `FIREBASE_CREDS` jest poprawnym JSON (otoczony `'''`)
- W projekcie `roboczy-bez-limitu` jest włączony **Vertex AI API** i **Firestore API**
- Service account ma role: **Vertex AI User**, **Cloud Datastore User**
- W `GCP_LOCATION` model `gemini-2.5-flash` jest dostępny (sprawdzone: `us-central1`)
    """)
    st.stop()

# ── Login ────────────────────────────────────────────────
if "auth" not in st.session_state:
    st.session_state.auth = False
if "user" not in st.session_state:
    st.session_state.user = None

if not st.session_state.auth:
    st.markdown("# 🍳 Kuchnia")
    st.caption("Zaloguj się")
    with st.form("login"):
        col1, col2 = st.columns([2, 1])
        with col1:
            who = st.text_input("Imię", placeholder="np. Magda")
        with col2:
            pwd = st.text_input("Hasło", type="password")
        if st.form_submit_button("Wejdź", type="primary", use_container_width=True):
            if pwd == ADMIN_PASSWORD and who.strip():
                st.session_state.auth = True
                st.session_state.user = who.strip()
                st.rerun()
            else:
                st.error("Złe hasło lub puste imię")
    st.stop()

# ── Stała baza ───────────────────────────────────────────
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

# ── Firestore ────────────────────────────────────────────
def _doc(name):
    return db.collection("kuchnia").document(name)

def fs_load(name, default):
    try:
        snap = _doc(name).get()
        if snap.exists:
            return snap.to_dict().get("items", default)
    except Exception as e:
        st.warning(f"Odczyt {name}: {e}")
    return default

def fs_save(name, items):
    try:
        _doc(name).set({
            "items": items,
            "updated_at": firestore.SERVER_TIMESTAMP,
            "updated_by": st.session_state.user,
        })
    except Exception as e:
        st.error(f"Zapis {name}: {e}")

def fs_init(name, default):
    try:
        snap = _doc(name).get()
        if not snap.exists:
            fs_save(name, default)
            return default
        return snap.to_dict().get("items", default)
    except Exception:
        return default

def init_state():
    if st.session_state.get("_loaded"):
        return
    with st.spinner("Wczytuję dane…"):
        st.session_state.recipes   = fs_load("recipes", [])
        st.session_state.fridge    = fs_init("fridge", list(DEFAULT_FRIDGE))
        st.session_state.equipment = fs_init("equipment", list(DEFAULT_EQUIPMENT))
        st.session_state.shopping  = fs_load("shopping", [])
    st.session_state._loaded = True

def save_recipes():   fs_save("recipes",   st.session_state.recipes)
def save_fridge():    fs_save("fridge",    st.session_state.fridge)
def save_equipment(): fs_save("equipment", st.session_state.equipment)
def save_shopping():  fs_save("shopping",  st.session_state.shopping)

init_state()

# ── Helpers ──────────────────────────────────────────────
def parse_docx(file_bytes):
    doc = Document(io.BytesIO(file_bytes))
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())

def call_gemini(prompt):
    response = gemini.generate_content(prompt)
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

def add_to_shopping(items):
    existing = {x["name"].lower() for x in st.session_state.shopping}
    added = 0
    for ing in items:
        if ing and ing.lower() not in existing:
            st.session_state.shopping.append({
                "name": ing, "bought": False, "added_by": st.session_state.user,
            })
            existing.add(ing.lower())
            added += 1
    if added:
        save_shopping()
    return added

# ── Górny pasek ──────────────────────────────────────────
top_l, top_r = st.columns([4, 1])
with top_l:
    st.markdown("# 🍳 Kuchnia")
    st.caption(f"**{st.session_state.user}** ☁️ Synchronizacja w chmurze")
with top_r:
    st.write("")
    if st.button("🔄 Odśwież", use_container_width=True):
        st.session_state._loaded = False
        st.rerun()
    if st.button("🚪 Wyloguj", use_container_width=True):
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        st.rerun()

tab_recipes, tab_fridge, tab_ask, tab_shopping = st.tabs([
    "📖 Przepisy", "🥬 Lodówka", "✨ Zapytaj", "🛒 Zakupy",
])

# ─── PRZEPISY ────────────────────────────────────────────
with tab_recipes:
    st.subheader("Moje przepisy")
    n = len(st.session_state.recipes)
    st.caption(f"📚 {n} przepisów w bibliotece" if n else "Wgraj dokument Word — AI go odczyta.")

    uploaded = st.file_uploader("Wgraj plik .docx", type=["docx"], key="docx_uploader")
    if uploaded is not None:
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
{text[:12000]}"""
                        raw = call_gemini(prompt)
                        new_recipes = extract_json(raw, kind="array")
                        ts = int(time.time() * 1000)
                        for i, r in enumerate(new_recipes):
                            r["id"] = f"r_{ts}_{i}"
                            r["added_by"] = st.session_state.user
                        st.session_state.recipes.extend(new_recipes)
                        save_recipes()
                        st.success(f"✓ Dodano {len(new_recipes)} przepisów")
                        st.rerun()
            except Exception as e:
                st.error(f"Błąd: {e}")

    if st.session_state.recipes:
        st.markdown("---")
        for r in st.session_state.recipes:
            label = f"**{r.get('name','?')}**  ·  {r.get('category','')}  ·  ~{r.get('time','?')} min"
            with st.expander(label):
                if r.get("added_by"):
                    st.caption(f"Dodał(a): {r['added_by']}")
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
                    st.session_state.recipes = [
                        x for x in st.session_state.recipes if x.get("id") != r.get("id")
                    ]
                    save_recipes()
                    st.rerun()

    with st.expander("💾 Backup"):
        if st.session_state.recipes:
            st.download_button(
                "📥 Pobierz JSON",
                data=json.dumps(st.session_state.recipes, ensure_ascii=False, indent=2),
                file_name=f"kuchnia-{int(time.time())}.json",
                mime="application/json",
                use_container_width=True,
            )

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
                    save_equipment()
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
                save_equipment()
                st.rerun()

    st.markdown("---")
    st.markdown("#### Dodaj produkt")
    with st.form("add_fridge", clear_on_submit=True):
        c1, c2, c3 = st.columns([3, 2, 1])
        with c1:
            new_item = st.text_input("Produkt", placeholder="np. tofu…", label_visibility="collapsed")
        with c2:
            cat_options = {f"{c['emoji']} {c['label']}": c["id"] for c in CATEGORIES}
            sel = st.selectbox("Kat.", list(cat_options.keys()), label_visibility="collapsed")
        with c3:
            submit_fr = st.form_submit_button("➕", use_container_width=True)
        if submit_fr and new_item.strip():
            name = new_item.strip()
            if name.lower() not in [f["name"].lower() for f in st.session_state.fridge]:
                st.session_state.fridge.append({"name": name, "category": cat_options[sel]})
                save_fridge()
                st.rerun()

    st.markdown("---")
    for cat in CATEGORIES:
        items = [f for f in st.session_state.fridge if f.get("category") == cat["id"]]
        if not items:
            continue
        st.markdown(f"##### {cat['emoji']} {cat['label']}  ·  {len(items)}")
        cols = st.columns(3)
        for i, item in enumerate(items):
            with cols[i % 3]:
                if st.button(f"❌ {item['name']}",
                             key=f"fr_{cat['id']}_{i}_{item['name']}",
                             use_container_width=True):
                    st.session_state.fridge = [
                        x for x in st.session_state.fridge if x["name"] != item["name"]
                    ]
                    save_fridge()
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

                fs = ", ".join(f["name"] for f in st.session_state.fridge) or "(pusto)"
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
                                            "name": p.get("name", ""), "category": cat_id,
                                        })
                                        save_fridge()
                                        st.rerun()

# ─── ZAKUPY ──────────────────────────────────────────────
with tab_shopping:
    st.subheader("Lista zakupów")
    remaining = [s for s in st.session_state.shopping if not s.get("bought")]
    bought = [s for s in st.session_state.shopping if s.get("bought")]

    if st.session_state.shopping:
        st.caption(f"🛒 {len(remaining)}  ·  ✓ {len(bought)}")
    else:
        st.caption("Pusto.")

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
                    save_shopping()
                    st.rerun()
            with cols[1]:
                label = item["name"]
                if item.get("added_by"):
                    label += f"  *· {item['added_by']}*"
                st.markdown(label)
            with cols[2]:
                if st.button("🗑️", key=f"del_shop_{i}_{item['name']}"):
                    del st.session_state.shopping[i]
                    save_shopping()
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
                    save_shopping()
                    st.rerun()
            with cols[1]:
                st.markdown(f"~~{item['name']}~~")

        if st.button("🗑️ Wyczyść kupione", use_container_width=True):
            st.session_state.shopping = [
                s for s in st.session_state.shopping if not s.get("bought")
            ]
            save_shopping()
            st.rerun()
