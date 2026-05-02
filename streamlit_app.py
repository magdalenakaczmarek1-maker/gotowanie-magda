"""
Kuchnia — Twój kucharski asystent
Streamlit + Claude API + python-docx + localStorage
"""
import streamlit as st
import anthropic
from docx import Document
import json
import io
import re
import time

# ── Konfiguracja strony ──────────────────────────────────
st.set_page_config(
    page_title="Kuchnia",
    page_icon="🍳",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# ── Klucz API ────────────────────────────────────────────
try:
    ANTHROPIC_API_KEY = st.secrets["ANTHROPIC_API_KEY"]
except (KeyError, FileNotFoundError):
    st.error("⚠️ Brak klucza API")
    st.markdown("""
**Lokalnie:** stwórz plik `.streamlit/secrets.toml` z zawartością:
```toml
ANTHROPIC_API_KEY = "sk-ant-api03-..."
```

**Streamlit Cloud:** w panelu aplikacji **⋯ → Settings → Secrets** wklej:
```
ANTHROPIC_API_KEY = "sk-ant-api03-..."
```

Klucz dostaniesz na [console.anthropic.com](https://console.anthropic.com/settings/keys).
Doładuj konto $5–10 — wystarczy na miesiące używania.
    """)
    st.stop()

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# Model — zmień na 'claude-haiku-4-5' (taniej) lub 'claude-opus-4-5' (mądrzej)
MODEL = "claude-sonnet-4-5"

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

# ── Stan sesji + localStorage ────────────────────────────
# Próbujemy użyć streamlit-local-storage do trwałości między sesjami.
# Jeśli nie działa, dane są tylko w sesji + użytkownik ma backup JSON.
try:
    from streamlit_local_storage import LocalStorage
    localS = LocalStorage()
    LOCAL_STORAGE_OK = True
except Exception:
    localS = None
    LOCAL_STORAGE_OK = False


def ls_get(key, default):
    if not LOCAL_STORAGE_OK:
        return default
    try:
        raw = localS.getItem(key)
        if raw:
            return json.loads(raw)
    except Exception:
        pass
    return default


def ls_set(key, value):
    if not LOCAL_STORAGE_OK:
        return
    try:
        localS.setItem(key, json.dumps(value, ensure_ascii=False), key=f"set_{key}_{time.time()}")
    except Exception:
        pass


def init_state():
    if "_loaded" in st.session_state:
        return
    st.session_state.recipes   = ls_get("kuchnia_recipes",   [])
    st.session_state.fridge    = ls_get("kuchnia_fridge",    list(DEFAULT_FRIDGE))
    st.session_state.equipment = ls_get("kuchnia_equipment", list(DEFAULT_EQUIPMENT))
    st.session_state.shopping  = ls_get("kuchnia_shopping",  [])
    st.session_state._loaded = True


def save_recipes():   ls_set("kuchnia_recipes",   st.session_state.recipes)
def save_fridge():    ls_set("kuchnia_fridge",    st.session_state.fridge)
def save_equipment(): ls_set("kuchnia_equipment", st.session_state.equipment)
def save_shopping():  ls_set("kuchnia_shopping",  st.session_state.shopping)


init_state()


# ── Helpers ──────────────────────────────────────────────
def parse_docx(file_bytes):
    """Wyciągnij tekst z .docx."""
    doc = Document(io.BytesIO(file_bytes))
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


def call_claude(prompt, max_tokens=2048):
    """Zapytaj Claude'a."""
    response = client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip()


def extract_json(text, kind="object"):
    """Wyłuskaj JSON z tekstu (na wypadek gdyby AI dodało markdown)."""
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
            st.session_state.shopping.append({"name": ing, "bought": False})
            existing.add(ing.lower())
            added += 1
    if added:
        save_shopping()
    return added


# ── Nagłówek ─────────────────────────────────────────────
st.markdown("# 🍳 Kuchnia")
st.caption("Twój kucharski asystent — przepisy, lodówka, lista zakupów")

if not LOCAL_STORAGE_OK:
    st.warning(
        "ℹ️ Trwały zapis danych nie działa w tej sesji. Twoje przepisy znikną po odświeżeniu — "
        "ale możesz pobrać i wgrać backup JSON w zakładce Przepisy."
    )

tab_recipes, tab_fridge, tab_ask, tab_shopping = st.tabs([
    "📖 Przepisy",
    "🥬 Lodówka",
    "✨ Zapytaj",
    "🛒 Zakupy",
])

# ─────────────────────────────────────────────────────────
# Zakładka: PRZEPISY
# ─────────────────────────────────────────────────────────
with tab_recipes:
    st.subheader("Moje przepisy")

    n = len(st.session_state.recipes)
    if n:
        st.caption(f"📚 {n} przepisów w bibliotece")
    else:
        st.caption("Wgraj dokument Word — AI przeczyta przepisy i je posegreguje.")

    uploaded = st.file_uploader("Wgraj plik .docx z przepisami", type=["docx"], key="docx_uploader")
    if uploaded is not None:
        with st.spinner("Czytam dokument…"):
            try:
                text = parse_docx(uploaded.read())
                if not text.strip():
                    st.error("Pusty dokument.")
                else:
                    with st.spinner("Analizuję przepisy (to może chwilę potrwać)…"):
                        prompt = f"""Wyodrębnij wszystkie przepisy z tekstu. Zwróć WYŁĄCZNIE czysty JSON, bez markdown, bez ```. Format:
[{{"name":"nazwa","category":"śniadanie|obiad|kolacja|deser|przekąska|inne","time":liczba_minut,"tags":["łatwy","airfryer","mięsne","wege","..."],"ingredients":[{{"name":"składnik","amount":"ilość"}}],"instructions":"kroki","tools":["airfryer","termomix","piekarnik","płyta indukcyjna","..."]}}]

Polski. Czas w minutach (szacuj jeśli brak). Tagi: trudność, typ kuchni, sprzęt, okazja.

TEKST:
{text[:12000]}"""
                        raw = call_claude(prompt, max_tokens=4096)
                        new_recipes = extract_json(raw, kind="array")
                        ts = int(time.time() * 1000)
                        for i, r in enumerate(new_recipes):
                            r["id"] = f"r_{ts}_{i}"
                        st.session_state.recipes.extend(new_recipes)
                        save_recipes()
                        st.success(f"✓ Dodano {len(new_recipes)} przepisów")
                        st.rerun()
            except Exception as e:
                st.error(f"Błąd: {e}")

    # Lista przepisów
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
                if st.button("🗑️ Usuń przepis", key=f"del_{r.get('id','')}"):
                    st.session_state.recipes = [
                        x for x in st.session_state.recipes if x.get("id") != r.get("id")
                    ]
                    save_recipes()
                    st.rerun()

    # Backup
    st.markdown("---")
    with st.expander("💾 Backup / Przywracanie"):
        st.caption("Pobierz JSON jako kopię zapasową albo przywróć przepisy z pliku.")
        col1, col2 = st.columns(2)
        with col1:
            if st.session_state.recipes:
                st.download_button(
                    "📥 Pobierz backup",
                    data=json.dumps(st.session_state.recipes, ensure_ascii=False, indent=2),
                    file_name="kuchnia-przepisy.json",
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
                        st.session_state.recipes = data
                        save_recipes()
                        st.success("✓ Przywrócono")
                        st.rerun()
                    else:
                        st.error("Nieprawidłowy format pliku.")
                except Exception as e:
                    st.error(f"Błąd: {e}")

# ─────────────────────────────────────────────────────────
# Zakładka: LODÓWKA
# ─────────────────────────────────────────────────────────
with tab_fridge:
    st.subheader("Lodówka i sprzęt")
    st.caption("To, co masz pod ręką. AI dobiera przepisy do tych produktów i Twojego sprzętu.")

    # SPRZĘT
    st.markdown("#### 🍳 Sprzęt w kuchni")
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
            new_eq = st.text_input("Dodaj sprzęt", placeholder="np. wok, sous-vide…",
                                    label_visibility="collapsed")
        with c2:
            submit_eq = st.form_submit_button("Dodaj", use_container_width=True)
        if submit_eq and new_eq.strip():
            name = new_eq.strip()
            if name.lower() not in [e.lower() for e in st.session_state.equipment]:
                st.session_state.equipment.append(name)
                save_equipment()
                st.rerun()

    st.markdown("---")

    # DODAJ PRODUKT
    st.markdown("#### Dodaj produkt do lodówki")
    with st.form("add_fridge", clear_on_submit=True):
        c1, c2, c3 = st.columns([3, 2, 1])
        with c1:
            new_item = st.text_input("Produkt", placeholder="np. tofu, koperek…",
                                      label_visibility="collapsed")
        with c2:
            cat_options = {f"{c['emoji']} {c['label']}": c["id"] for c in CATEGORIES}
            sel = st.selectbox("Kategoria", list(cat_options.keys()), label_visibility="collapsed")
        with c3:
            submit_fr = st.form_submit_button("➕", use_container_width=True)
        if submit_fr and new_item.strip():
            name = new_item.strip()
            if name.lower() not in [f["name"].lower() for f in st.session_state.fridge]:
                st.session_state.fridge.append({"name": name, "category": cat_options[sel]})
                save_fridge()
                st.rerun()

    st.markdown("---")

    # PRODUKTY POGRUPOWANE
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

# ─────────────────────────────────────────────────────────
# Zakładka: ZAPYTAJ
# ─────────────────────────────────────────────────────────
with tab_ask:
    st.subheader("Co dziś gotujemy?")
    st.caption("Opisz sytuację, czas, urządzenia, okazję — dostaniesz dopasowany plan.")

    query = st.text_area(
        "Twoje pytanie",
        placeholder="np. Łatwy obiad do pracy, gotuję 7:00, jem 13:00, airfryer…",
        height=100,
        label_visibility="collapsed",
    )

    c1, c2 = st.columns([3, 2])
    with c1:
        st.caption(
            f"📖 {len(st.session_state.recipes)} przep.  ·  "
            f"🥬 {len(st.session_state.fridge)} prod.  ·  "
            f"🍳 {len(st.session_state.equipment)} sprz."
        )
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
                    recipes_summary = "\n".join(
                        f"• {r.get('name','?')} [{r.get('category','')}, ~{r.get('time','?')}min, "
                        f"składniki: {', '.join(i.get('name','') for i in r.get('ingredients', []))}]"
                        for r in st.session_state.recipes
                    )
                else:
                    recipes_summary = "(brak własnych przepisów)"

                fridge_summary = ", ".join(f["name"] for f in st.session_state.fridge) or "(pusto)"
                eq_summary = ", ".join(st.session_state.equipment) or "(brak)"
                valid_cats = "|".join(c["id"] for c in CATEGORIES)

                prompt = f"""Jesteś moim osobistym kucharzem. Pomóż wybrać przepisy i zaplanować gotowanie.

ZAPYTANIE: "{final_query}"

MOJE PRZEPISY:
{recipes_summary}

W LODÓWCE / SPIŻARNI MAM:
{fridge_summary}

MAM SPRZĘT:
{eq_summary}

ZASADY:
- Preferuj moje przepisy. Jeśli kompletnie nie pasują → zaproponuj nowy.
- Wykorzystuj sprzęt który mam (airfryer/termomix/itd.).
- "missing_ingredients" = jednorazowe rzeczy do dokupienia na ten przepis.
- "worth_for_pantry" = produkty które warto trzymać NA STAŁE (zioła, podstawy używane w wielu przepisach), z kategorią z listy: {valid_cats}.

Zwróć WYŁĄCZNIE czysty JSON, bez markdown:
{{
  "summary": "1-2 zdania po polsku",
  "suggestions": [
    {{
      "name": "nazwa",
      "from_my_recipes": true/false,
      "why": "krótko czemu pasuje",
      "time": liczba_minut_lub_null,
      "missing_ingredients": ["jednorazowe"],
      "worth_for_pantry": [{{"name":"produkt","category":"{valid_cats}"}}],
      "when_to_prepare": "kiedy/jak zaplanować lub null"
    }}
  ]
}}"""
                raw = call_claude(prompt, max_tokens=2048)
                resp = extract_json(raw, kind="object")
                st.session_state["_last_response"] = resp
            except Exception as e:
                st.session_state["_last_response"] = {"error": str(e)}

    # Wyświetl ostatnią odpowiedź
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
                        meta.append("📖 z moich przepisów")
                    if meta:
                        st.caption("  ·  ".join(meta))

                    if s.get("why"):
                        st.write(s["why"])

                    if s.get("when_to_prepare"):
                        st.markdown(f"**🗓️ Kiedy:** {s['when_to_prepare']}")

                    # Brakujące składniki
                    missing = s.get("missing_ingredients") or []
                    if missing:
                        st.markdown("**🛒 Do dokupienia (jednorazowo):**")
                        st.write("  ·  ".join(missing))
                        if st.button("Dodaj wszystko do listy zakupów",
                                     key=f"add_shop_{idx}_{s.get('name','')}",
                                     use_container_width=True):
                            n = add_to_shopping(missing)
                            st.success(f"Dodano {n} pozycji do listy zakupów ✓")

                    # Warto na stałe
                    pantry = s.get("worth_for_pantry") or []
                    if pantry:
                        st.markdown("**⭐ Warto trzymać na stałe:**")
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
                                    if st.button("➕ do lodówki",
                                                 key=f"add_pantry_{idx}_{pi}_{p.get('name','')}",
                                                 use_container_width=True):
                                        cat_id = p.get("category") if any(
                                            c["id"] == p.get("category") for c in CATEGORIES
                                        ) else "inne"
                                        st.session_state.fridge.append({
                                            "name": p.get("name", ""),
                                            "category": cat_id,
                                        })
                                        save_fridge()
                                        st.rerun()

# ─────────────────────────────────────────────────────────
# Zakładka: LISTA ZAKUPÓW
# ─────────────────────────────────────────────────────────
with tab_shopping:
    st.subheader("Lista zakupów")

    remaining = [s for s in st.session_state.shopping if not s.get("bought")]
    bought = [s for s in st.session_state.shopping if s.get("bought")]

    if st.session_state.shopping:
        st.caption(f"🛒 {len(remaining)} do kupienia  ·  ✓ {len(bought)} odhaczone")
    else:
        st.caption("Pusto. Sugestie z AI lądują tu automatycznie.")

    with st.form("add_shop", clear_on_submit=True):
        c1, c2 = st.columns([4, 1])
        with c1:
            new_shop = st.text_input("Dodaj produkt", placeholder="dodaj ręcznie…",
                                      label_visibility="collapsed")
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
                st.write(item["name"])
            with cols[2]:
                if st.button("🗑️", key=f"del_shop_{i}_{item['name']}"):
                    del st.session_state.shopping[i]
                    save_shopping()
                    st.rerun()

    if bought:
        st.markdown("#### Już w koszyku")
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
