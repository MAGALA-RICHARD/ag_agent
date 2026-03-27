import os
import tempfile
from contextlib import suppress
from copy import deepcopy
from pathlib import Path
from streamlit_option_menu import option_menu
import streamlit as st
from apsimNGpy import Apsim
from dotenv import load_dotenv
from folium import folium
from streamlit_folium import st_folium

from resources.utils import fetch_weather
from resources.utils import (
    fetch_all_apsimx,
    fetch_weather,
    fetch_cultivars,
    inspect_node,
    inspect_node_params,
    fetch_sim,
)
from tools.geo_tools import GeoPoint
from formater.render import render_params

BASE = Path(__file__).parent
load_dotenv(dotenv_path=BASE / ".api.env")

st.set_page_config(
    page_title="APSIM DST",
    layout="wide",
    initial_sidebar_state="collapsed",
)

WORKSPACE = BASE / ".workspaces"
WORKSPACE.mkdir(exist_ok=True)

BROWSE = "Browse my computer"
DEFAULT_LAT = 42.0308
DEFAULT_LON = -93.6319
DEFAULT_CROP = "Maize"
DEFAULT_START = 1986
DEFAULT_END = 2024

# =========================================================
# SESSION STATE
# =========================================================
if "page" not in st.session_state:
    st.session_state["page"] = "Inputs"

if "results" not in st.session_state:
    st.session_state["results"] = None
selected = option_menu(
    menu_title=None,
    options=["Farm location", "Inputs", "Run", "Results", "Settings"],
    icons=[ 'sliders', "sliders", "play", "bar-chart", 'gear'],
    orientation="horizontal",
    default_index=["Farm location", "Inputs", "Run", "Results", "Settings"].index(
        st.session_state["page"]
    ),
    styles={
        "container": {
            "padding": "0!important",
            "background-color": "green",
        },
        "icon": {"color": "#9ca3af", "font-size": "16px"},
        "nav-link": {
            "color": "#9ca3af",
            "font-size": "15px",
            "text-align": "center",
            "margin": "0px",
            "--hover-color": "#1f2937",
        },
        "nav-link-selected": {
            "background-color": "#2563eb",
            "color": "white",
        },
    },
)
st.session_state["page"] = selected


def get_crop_options():
    apsim_files = fetch_all_apsimx(apsim.bin_path) or []
    options = list(apsim_files)
    if BROWSE not in options:
        options.append(BROWSE)
    return options


def save_uploaded_apsim_file(uploaded_file):
    if uploaded_file is None:
        return None

    with tempfile.NamedTemporaryFile(delete=False, suffix=".apsimx") as tmp:
        tmp.write(uploaded_file.read())
        return tmp.name


def get_active_crop_path(crop_choice):
    if st.session_state['uploaded']:
        return st.session_state.get("uploaded_crop_path")
    return crop_choice


def ensure_crop_edit_bucket(crop_path):
    if not crop_path:
        return
    if crop_path not in st.session_state["node_edits"]:
        st.session_state["node_edits"][crop_path] = {}


def normalize_node_values(node_type, values):
    cleaned = deepcopy(values)

    if node_type == "Clock":
        for k, v in cleaned.items():
            if hasattr(v, "strftime"):
                cleaned[k] = v.strftime("%Y-%m-%d")

    return cleaned


def get_saved_node_values(crop_path, node_path):
    return deepcopy(
        st.session_state["node_edits"]
        .get(crop_path, {})
        .get(node_path)
    )


def save_node_values(crop_path, node_path, values):
    ensure_crop_edit_bucket(crop_path)
    st.session_state["node_edits"][crop_path][node_path] = deepcopy(values)


def render_location_map():
    import folium
    import streamlit as st
    from streamlit_folium import st_folium
    from tools.geo_tools import GeoPoint

    # -------------------------------------------------
    # INIT DEFAULT POINT (IMPORTANT)
    # -------------------------------------------------
    if "selected_point" not in st.session_state:
        st.session_state["selected_point"] = GeoPoint.normalize(42.03, -93.63)

    point = st.session_state["selected_point"]

    # -------------------------------------------------
    # CREATE MAP
    # -------------------------------------------------
    m = folium.Map(
        location=[point.lat, point.lon],
        zoom_start=10,
        control_scale=True,
    )

    # Marker for current point
    folium.Marker(
        [point.lat, point.lon],
        tooltip="Selected location",
        icon=folium.Icon(color="blue")
    ).add_to(m)

    # Click popup
    m.add_child(folium.LatLngPopup())

    # -------------------------------------------------
    # RENDER MAP
    # -------------------------------------------------
    map_data = st_folium(m, width=None, height=500)

    # -------------------------------------------------
    # HANDLE CLICK
    # -------------------------------------------------
    if map_data and map_data.get("last_clicked"):

        raw = map_data["last_clicked"]

        try:
            new_point = GeoPoint.normalize(raw["lat"], raw["lng"])

            st.session_state["selected_point"] = new_point

            st.success(
                f"Selected: {new_point.lat:.5f}, {new_point.lon:.5f}"
            )

        except Exception as e:
            st.error(f"Invalid location: {e}")

    # -------------------------------------------------
    # RETURN CURRENT POINT
    # -------------------------------------------------
    return st.session_state["selected_point"]


def run_simulation(
        crop_path,
        lonlat,
        start_year,
        end_year,
        crop_node_edits,
):
    wf = fetch_weather(lonlat, start=start_year, end=end_year)
    st.session_state["last_weather_file"] = wf

    with apsim.ApsimModel(crop_path) as model:
        model.get_weather_from_file(wf)

        for node_path, updated_values in crop_node_edits.items():
            if not node_path or not updated_values:
                continue
            model.edit_model_by_path(path=node_path, **updated_values)

        # Always force clock to match selected weather range unless user already edited it
        has_clock_edit = any("Clock" in str(k) for k in crop_node_edits.keys())
        if not has_clock_edit:
            model.edit_model(
                "Clock",
                "Clock",
                Start=f"{start_year}-01-01",
                End=f"{end_year}-12-31",
            )

        model.run(verbose=True)
        df = model.results.copy()

    for col in ["CheckpointID", "SimulationID"]:
        if col in df.columns:
            df.drop(columns=[col], inplace=True)

    summary = df.mean(numeric_only=True).to_dict()

    return df, summary


def init_state():
    defaults = {
        "selected_crop_path": None,
        "uploaded_crop_path": None,
        "selected_point": GeoPoint.normalize(DEFAULT_LAT, DEFAULT_LON),
        "node_edits": {},  # {crop_path: {node_path: {param: value}}}
        "last_results": None,
        "last_weather_file": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


init_state()

st.set_page_config(layout="wide", page_title="APSIM Dashboard")
settings = st.session_state.get('settings')
if settings:
    BIN_PATH = settings.get('bin_path')
    print(BIN_PATH)
    apsim = Apsim(BIN_PATH)
else:
    apsim = Apsim()

# =========================================================
# SESSION STATE
# =========================================================
defaults = {
    "page": "Inputs",
    "results": None,
    "crop": "",
    "point": None,
}

for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v


if selected == 'Farm location':
    st.subheader("Pick Field Location")
    #selected_point = render_location_map()

# =========================================================
# PAGE: INPUTS
# =========================================================
if selected == "Inputs":

    st.title("Management controls")
    col_left, col_middle, col_right = st.columns([1.2, 1.7, 1.2])

    # =========================================================
    # LEFT PANEL
    # =========================================================
    with col_left:
        if "uploaded" not in st.session_state:
            st.session_state["uploaded"] = False
        st.subheader("Management Inputs")

        crop_options = get_crop_options()
        default_index = crop_options.index(DEFAULT_CROP) if DEFAULT_CROP in crop_options else 0
        crop_choice = st.selectbox(
            "Crop",
            crop_options,
            index=default_index,
            key="crop_choice"
        )

        if crop_choice == BROWSE:
            uploaded_file = st.file_uploader("Upload APSIM file (.apsimx)", type=["apsimx"])
            if uploaded_file is not None:
                uploaded_path = save_uploaded_apsim_file(uploaded_file)
                st.session_state["uploaded_crop_path"] = uploaded_path
                st.success(f"Loaded: {uploaded_file.name}")
                st.session_state["uploaded"]= True

        crop_path = get_active_crop_path(crop_choice)
        st.session_state["selected_crop_path"] = crop_path

        if not crop_path:
            st.info("Select a built-in crop or upload an APSIM file.")
        else:
            ensure_crop_edit_bucket(crop_path)

            with suppress(Exception):
                cultivars = fetch_cultivars(crop_path, loader=apsim.ApsimModel) or []
            if not cultivars:
                cultivars = [None]

            cultivar = st.selectbox("Cultivar", cultivars)

            with suppress(Exception):
                sim_list = inspect_node(
                    path=crop_path,
                    loader=apsim.ApsimModel,
                    node_type="Simulation",
                    fp=False,
                ) or []
            sim = st.selectbox("Simulation", [None, *sim_list])
            tables  = inspect_node(
                    path=crop_path,
                    loader=apsim.ApsimModel,
                    node_type="Models.Report",
                    fp=False,
                )
            st.session_state['db_tables'] = tuple(tables)

            node_type = st.selectbox(
                "Select node type to edit",
                [None, "Clock", "Weather", "Models.Manager", "Cultivar"],
            )

            if sim:
                with suppress(Exception):
                    _, scoped_simulation = fetch_sim(
                        crop_path,
                        loader=apsim.ApsimModel,
                        name=sim,
                    )

            if node_type:
                try:
                    node_list = inspect_node(
                            path=crop_path,
                            node_type=node_type,
                            loader=apsim.ApsimModel,
                        ) or []
                except Exception as e:
                    st.error(repr(e))
                    st.stop()
                node_names = [i.split('.')[-1] for i in node_list]
                node_path = st.selectbox("Select node", [None, *node_names])
                if node_path:
                    nodes = dict(zip(node_names, node_list))
                    node_path = nodes.get(node_path)

                if node_path:
                    try:
                        base_params = inspect_node_params(
                            crop_path,
                            loader=apsim.ApsimModel,
                            node_path=node_path,
                        )
                    except Exception as e:
                        st.error(f"Could not load node parameters: {e}")
                        base_params = None

                    if base_params:
                        saved_params = get_saved_node_values(crop_path, node_path)
                        params_to_render = saved_params if saved_params else deepcopy(base_params)

                        st.markdown("### Edit Parameters")

                        with st.form(key=f"form::{crop_path}::{node_path}"):
                            updated_params = render_params(st, params_to_render)
                            submitted = st.form_submit_button("Save changes")

                        if submitted:
                            cleaned = normalize_node_values(node_type, updated_params)
                            save_node_values(crop_path, node_path, cleaned)
                            st.success(f"Saved changes for {node_path}")

                        current_saved = get_saved_node_values(crop_path, node_path)
                        if current_saved:
                            st.markdown("#### Saved values")
                            st.json(current_saved)

            crop_edits = st.session_state["node_edits"].get(crop_path, {})
            if crop_edits:
                st.markdown("### Pending edits")
                st.json(crop_edits)
            with col_middle:
                selected_point = render_location_map()





# =========================================================
# PAGE: RUN
# =========================================================
elif selected == "Run":
    col1, col2 = st.columns(2)
    st.title("Run Simulation")

    crop = st.session_state.get("selected_crop_path")
    point = st.session_state.get("point")

    with col1:
        start_year, end_year = st.slider(
            "Simulation period",
            min_value=DEFAULT_START,
            max_value=2025,
            value=st.session_state.get("year_range", (1986, 2024)),
            step=1,
            key="year_range"
        )
    run = st.button("▶ Run Simulation", type="primary", use_container_width=True)

    # ---------------- RUN ----------------
    if run:
        if end_year < start_year:
            st.error("End year must be greater than or equal to start year.")

        # run_clicked = st.button("▶ Run Simulation", type="primary")

       # st.subheader("Results & Insights")

        crop_path = st.session_state.get("selected_crop_path")
        point = st.session_state.get("selected_point")

        if not crop_path:
            st.warning("Select or upload an APSIM file first.")
        elif point is None or point.lat is None or point.lon is None:
            st.warning("Select a location on the map.")
        elif end_year < start_year:
            st.warning("Fix the year range before running.")
        else:
            lonlat = (point.lon, point.lat)
            crop_edits = st.session_state["node_edits"].get(crop_path, {})

            try:
                with st.spinner(f"Running {Path(crop_path).name}.."):
                    df, summary = run_simulation(
                        crop_path=crop_path,
                        lonlat=lonlat,
                        start_year=start_year,
                        end_year=end_year,
                        crop_node_edits=crop_edits,
                    )

                st.session_state["last_results"] = {
                    "dataframe": df,
                    "summary": summary,
                }

                st.success("Simulation completed successfully.")

            except Exception as e:
                st.error(f"Simulation failed: {e}")

        last_results = st.session_state.get("last_results")


# =========================================================
# PAGE: RESULTS
# =========================================================
elif selected == "Results":

    st.title("Results")

    df = st.session_state.get("last_results")
    if df:
        df = df.get('dataframe')

    if df is None:
        st.info("Run simulation first")
        st.stop()
    tables = st.session_state['db_tables']
    tb = st.selectbox(
        "Select a table", options=[None, *tables]
    )
    stat = st.selectbox("key metric statistics", options=['mean', 'median', 'max', 'min', 'std'])

    # ---------------- SUMMARY METRICS ----------------
    if tb:
        df = df[df['source_table']==tb]
        df.dropna(axis=1, how="all", inplace=True)
    summary = getattr(df, stat)(numeric_only=True)

    st.subheader("Key Metrics")

    cols = st.columns(4)
    for i, (k, v) in enumerate(summary.items()):
        cols[i % 4].metric(k, f"{v:.2f}")

    st.markdown("---")

    # ---------------- DATA TABLE ----------------

    t_msg  = f"from {tb} table" if tb else ""
    st.subheader(f"Simulation Output {t_msg}")
    st.dataframe(df, use_container_width=True)

    # ---------------- DOWNLOAD ----------------
    csv = df.to_csv(index=False)
    st.download_button("Download CSV", csv, "apsim_results.csv")

# =========================================================
# PAGE: SETTINGS
# =========================================================
elif selected == "Settings":
    import os
    from apsimNGpy import get_apsim_bin_path

    st.title("Settings")

    # -----------------------------------------------------
    # INIT SETTINGS STATE (DO NOT RESET EACH RUN)
    # -----------------------------------------------------
    if "settings" not in st.session_state:
        st.session_state["settings"] = {
            "bin_path": get_apsim_bin_path()
        }

    settings = st.session_state["settings"]

    # -----------------------------------------------------
    # APSIM CONFIGURATION
    # -----------------------------------------------------
    st.subheader("APSIM Configuration")

    with st.expander("Edit APSIM Binary Path", expanded=True):

        bin_path_input = st.text_input(
            "Path to APSIM bin directory",
            value=settings.get("bin_path", ""),
            placeholder="e.g., C:/APSIM/bin"
        )

        col1, col2 = st.columns(2)

        # -------- VALIDATE --------
        with col1:
            if st.button("Validate Path"):
                if os.path.exists(bin_path_input):
                    st.success("Valid APSIM path")
                else:
                    st.error("Invalid path")

        # -------- SAVE --------
        with col2:
            if st.button("submit Bin path"):
                if os.path.exists(bin_path_input):
                    settings["bin_path"] = bin_path_input
                    st.success("Path saved successfully")
                else:
                    st.error("Cannot submit an invalid path")

    # -----------------------------------------------------
    # CURRENT CONFIG
    # -----------------------------------------------------
    st.markdown("### Current Configuration")

    st.code(settings["bin_path"], language="bash")

    # -----------------------------------------------------
    # SESSION DEBUG
    # -----------------------------------------------------
    st.markdown("---")
    st.subheader("Session State (Debug)")

    with st.expander("View full session state"):
        st.json(st.session_state)

    # -----------------------------------------------------
    # ACTIONS
    # -----------------------------------------------------
    st.markdown("---")
    st.subheader("Actions")

    col1, col2 = st.columns(2)

    with col1:
        if st.button("Clear Results", use_container_width=True):
            st.session_state["results"] = None
            st.success("Results cleared")

    with col2:
        if st.button("Reset App", use_container_width=True):
            for k in list(st.session_state.keys()):
                del st.session_state[k]
            st.success("App reset")
