import streamlit as st

st.set_page_config(layout="wide")

st.title("Settings")

st.subheader("Session State")
st.json(st.session_state)

if st.button("Clear Results"):
    st.session_state.pop("last_results", None)
    st.success("Results cleared")

if st.button("Reset All"):
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.success("Session reset")