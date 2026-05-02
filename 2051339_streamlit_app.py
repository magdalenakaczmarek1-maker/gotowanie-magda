import streamlit as st

st.title("🍳 Moje gotowanie")

st.header("Przepisy")

przepis = st.selectbox("Wybierz przepis", ["Makaron", "Kurczak", "Sałatka"])

if przepis == "Makaron":
    st.write("Makaron + sos + ser")

if przepis == "Kurczak":
    st.write("Kurczak pieczony")

if przepis == "Sałatka":
    st.write("Sałata + pomidor")
