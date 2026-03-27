import os
import tempfile
from contextlib import suppress
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from streamlit_option_menu import option_menu
from streamlit_folium import st_folium
import folium

from apsimNGpy import Apsim, get_apsim_bin_path
from resources.utils import (
    fetch_all_apsimx,
    fetch_weather,
    fetch_cultivars,
    inspect_node,
    inspect_node_params,
    fetch_sim,
)
from tools.geo_tools import GeoPoint
from formater.render import render_params, plot_chart

# =========================================================
# CONFIG
# =========================================================
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
PAGES = ["Farm location", "Inputs", "Run", "Results", 'Graphics', "Settings"]


# =========================================================
# APP STATE
# =========================================================
@dataclass
class AppSettings:
    bin_path: str = ""


@dataclass
class PlotSettings:
    plots: dict = field(default_factory=dict)
    total_plots: int = None

    def get_plot(self, plot_no):
        return self.plots.setdefault(plot_no, {})

    def get(self, plot_no, key):
        return self.plots.get(plot_no, {}).get(key)

    def set(self, plot_no, key, value):
        self.plots[plot_no][key] = value


@dataclass
class AppState:
    page: str = "Inputs"

    # crop/file state
    crop_choice: str = DEFAULT_CROP
    selected_crop_path: Optional[str] = None
    uploaded_crop_path: Optional[str] = None
    uploaded: bool = False

    # model editing state
    cultivar: Optional[str] = None
    simulation: Optional[str] = None
    node_type: Optional[str] = None
    node_display_name: Optional[str] = None

    # location and run state
    selected_point: Any = None
    year_range: tuple[int, int] = (DEFAULT_START, DEFAULT_END)

    # results and weather
    last_results: Optional[dict] = None
    last_weather_file: Optional[str] = None
    db_tables: tuple = ()

    # per-crop node edits
    # {crop_path: {node_path: {param: value}}}
    node_edits: dict = field(default_factory=dict)

    # settings
    settings: AppSettings = field(default_factory=AppSettings)


def get_state() -> AppState:
    if "app_state" not in st.session_state:
        state = AppState(
            selected_point=GeoPoint.normalize(DEFAULT_LAT, DEFAULT_LON),
            settings=AppSettings(bin_path=get_apsim_bin_path()),
        )
        st.session_state["app_state"] = state
    return st.session_state["app_state"]


def init_plot_config() -> PlotSettings:
    PLOTTER = "plotter"
    if PLOTTER not in st.session_state:
        plotter = PlotSettings()
        st.session_state[PLOTTER] = plotter
    return st.session_state[PLOTTER]


state = get_state()
plot_configs = init_plot_config()


# =========================================================
# APSIM INSTANCE
# =========================================================
def get_apsim(state: AppState) -> Apsim:
    bin_path = state.settings.bin_path.strip()
    return Apsim(bin_path) if bin_path else Apsim()


apsim = get_apsim(state)


# =========================================================
# HELPERS
# =========================================================
def get_crop_options(apsim_obj: Apsim) -> list[str]:
    apsim_files = fetch_all_apsimx(apsim_obj.bin_path) or []
    options = list(apsim_files)
    if BROWSE not in options:
        options.append(BROWSE)
    return options


def save_uploaded_apsim_file(uploaded_file) -> Optional[str]:
    if uploaded_file is None:
        return None
    with tempfile.NamedTemporaryFile(delete=False, suffix=".apsimx") as tmp:
        tmp.write(uploaded_file.read())
        return tmp.name


def get_active_crop_path(state: AppState) -> Optional[str]:
    if state.uploaded and state.uploaded_crop_path:
        return state.uploaded_crop_path
    if state.crop_choice == BROWSE:
        return state.uploaded_crop_path
    return state.crop_choice


def ensure_crop_edit_bucket(state: AppState, crop_path: Optional[str]) -> None:
    if not crop_path:
        return
    if crop_path not in state.node_edits:
        state.node_edits[crop_path] = {}


def normalize_node_values(node_type: Optional[str], values: dict) -> dict:
    cleaned = deepcopy(values)
    if node_type == "Clock":
        for k, v in cleaned.items():
            if hasattr(v, "strftime"):
                cleaned[k] = v.strftime("%Y-%m-%d")
    return cleaned


def get_saved_node_values(state: AppState, crop_path: str, node_path: str) -> Optional[dict]:
    return deepcopy(
        state.node_edits
        .get(crop_path, {})
        .get(node_path)
    )


def save_node_values(state: AppState, crop_path: str, node_path: str, values: dict) -> None:
    ensure_crop_edit_bucket(state, crop_path)
    state.node_edits[crop_path][node_path] = deepcopy(values)


def render_location_map(state: AppState):
    point = state.selected_point

    m = folium.Map(
        location=[point.lat, point.lon],
        zoom_start=10,
        control_scale=True,
    )

    folium.Marker(
        [point.lat, point.lon],
        tooltip="Selected location",
        icon=folium.Icon(color="blue"),
    ).add_to(m)

    m.add_child(folium.LatLngPopup())

    map_data = st_folium(m, width=None, height=500, key="farm_location_map")

    if map_data and map_data.get("last_clicked"):
        raw = map_data["last_clicked"]
        try:
            state.selected_point = GeoPoint.normalize(raw["lat"], raw["lng"])
            st.success(
                f"Selected: {state.selected_point.lat:.5f}, {state.selected_point.lon:.5f}"
            )
        except Exception as e:
            st.error(f"Invalid location: {e}")

    return state.selected_point


def run_simulation(
        apsim_obj: Apsim,
        state: AppState,
        crop_path: str,
        lonlat: tuple[float, float],
        start_year: int,
        end_year: int,
        crop_node_edits: dict,
):
    wf = fetch_weather(lonlat, start=start_year, end=end_year)
    state.last_weather_file = wf

    with apsim_obj.ApsimModel(crop_path) as model:
        model.get_weather_from_file(wf)

        for node_path, updated_values in crop_node_edits.items():
            if not node_path or not updated_values:
                continue
            model.edit_model_by_path(path=node_path, **updated_values)

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


def n_simulations(crop_id):
    with apsim.ApsimModel(crop_id) as com:
        return len(com)


# =========================================================
# NAVBAR
# =========================================================
selected = option_menu(
    menu_title=None,
    options=PAGES,
    icons=["geo-alt", "sliders", "play", "bar-chart", "bar-chart", "gear"],
    orientation="horizontal",
    default_index=PAGES.index(state.page),
    styles={
        "container": {
            "padding": "0!important",
            "background-color": "#0f172a",
        },
        "icon": {"color": "#cbd5e1", "font-size": "16px"},
        "nav-link": {
            "color": "#cbd5e1",
            "font-size": "15px",
            "text-align": "center",
            "margin": "0px",
            "--hover-color": "#1e293b",
        },
        "nav-link-selected": {
            "background-color": "#2563eb",
            "color": "white",
        },
    },
)
state.page = selected

# =========================================================
# PAGE: FARM LOCATION
# =========================================================
if selected == "Farm location":
    st.title("Farm Location")
    render_location_map(state)


# =========================================================
# PAGE: INPUTS
# =========================================================
elif selected == "Inputs":
    st.title("Management Controls")

    col_left, col_middle, col_right = st.columns([1.2, 1.7, 1.2])

    with col_left:
        st.subheader("Management Inputs")

        crop_options = get_crop_options(apsim)
        if state.crop_choice not in crop_options:
            state.crop_choice = DEFAULT_CROP if DEFAULT_CROP in crop_options else crop_options[0]

        state.crop_choice = st.selectbox(
            "Crop",
            crop_options,
            index=crop_options.index(state.crop_choice),
            key="ui_crop_choice",
        )

        if state.crop_choice == BROWSE:
            uploaded_file = st.file_uploader(
                "Upload APSIM file (.apsimx)",
                type=["apsimx"],
                key="ui_uploaded_file",
            )
            if uploaded_file is not None:
                uploaded_path = save_uploaded_apsim_file(uploaded_file)
                state.uploaded_crop_path = uploaded_path
                state.uploaded = True
                st.success(f"Loaded: {uploaded_file.name}")
        else:
            state.uploaded = False

        state.selected_crop_path = get_active_crop_path(state)
        crop_path = state.selected_crop_path

        if not crop_path:
            st.info("Select a built-in crop or upload an APSIM file.")
        else:
            ensure_crop_edit_bucket(state, crop_path)

            with suppress(Exception):
                cultivars = fetch_cultivars(crop_path, loader=apsim.ApsimModel) or []
            if not cultivars:
                cultivars = [None]

            cultivar_options = list(cultivars)
            if state.cultivar not in cultivar_options:
                state.cultivar = cultivar_options[0]
            state.cultivar = st.selectbox(
                "Cultivar",
                cultivar_options,
                index=cultivar_options.index(state.cultivar),
                key="ui_cultivar",
            )

            with suppress(Exception):
                sim_list = inspect_node(
                    path=crop_path,
                    loader=apsim.ApsimModel,
                    node_type="Simulation",
                    fp=False,
                ) or []

            sim_options = [None, *sim_list]
            if state.simulation not in sim_options:
                state.simulation = sim_options[0]
            state.simulation = st.selectbox(
                "Simulation",
                sim_options,
                index=sim_options.index(state.simulation),
                key="ui_simulation",
            )

            tables = inspect_node(
                path=crop_path,
                loader=apsim.ApsimModel,
                node_type="Models.Report",
                fp=False,
            ) or []
            state.db_tables = tuple(tables)

            node_type_options = [None, "Clock", "Weather", "Models.Manager", "Cultivar"]
            if state.node_type not in node_type_options:
                state.node_type = None
            state.node_type = st.selectbox(
                "Select node type to edit",
                node_type_options,
                index=node_type_options.index(state.node_type),
                key="ui_node_type",
            )

            if state.simulation:
                with suppress(Exception):
                    fetch_sim(
                        crop_path,
                        loader=apsim.ApsimModel,
                        name=state.simulation,
                    )

            if state.node_type:
                try:
                    node_list = inspect_node(
                        path=crop_path,
                        node_type=state.node_type,
                        loader=apsim.ApsimModel,
                    ) or []
                except Exception as e:
                    st.error(repr(e))
                    st.stop()

                node_names = [i.split(".")[-1] for i in node_list]
                node_name_options = [None, *node_names]

                if state.node_display_name not in node_name_options:
                    state.node_display_name = None

                state.node_display_name = st.selectbox(
                    "Select node",
                    node_name_options,
                    index=node_name_options.index(state.node_display_name),
                    key="ui_node_display_name",
                )

                node_path = None
                if state.node_display_name:
                    nodes = dict(zip(node_names, node_list))
                    node_path = nodes.get(state.node_display_name)

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
                        saved_params = get_saved_node_values(state, crop_path, node_path)
                        params_to_render = saved_params if saved_params else deepcopy(base_params)

                        st.markdown("### Edit Parameters")
                        with st.form(key=f"form::{crop_path}::{node_path}"):
                            updated_params = render_params(st, params_to_render)
                            submitted = st.form_submit_button("Save changes")

                        if submitted:
                            cleaned = normalize_node_values(state.node_type, updated_params)
                            save_node_values(state, crop_path, node_path, cleaned)
                            st.success(f"Saved changes for {node_path}")

                        current_saved = get_saved_node_values(state, crop_path, node_path)
                        if current_saved:
                            st.markdown("#### Saved values")
                            st.json(current_saved)

            crop_edits = state.node_edits.get(crop_path, {})
            if crop_edits:
                st.markdown("### Pending edits")
                st.json(crop_edits)

    with col_middle:
        st.subheader("Field Location")
        render_location_map(state)

    with col_right:
        st.subheader("Current Session")
        st.write("Crop path:", state.selected_crop_path)
        st.write("Selected Simulation:", state.simulation)
        st.write("Years:", f"{state.year_range[0]} - {state.year_range[1]}")
        st.write('Total simulations:', n_simulations(state.selected_crop_path))
        if state.selected_point:
            st.write(
                "Location:",
                f"{state.selected_point.lat:.4f}, {state.selected_point.lon:.4f}"
            )


# =========================================================
# PAGE: RUN
# =========================================================
elif selected == "Run":
    st.title("Run Simulation")
    col1, col2 = st.columns(2)

    crop_path = state.selected_crop_path
    point = state.selected_point

    with col1:
        state.year_range = st.slider(
            "Simulation period",
            min_value=DEFAULT_START,
            max_value=2025,
            value=state.year_range,
            step=1,
            key="ui_year_range",
        )

    start_year, end_year = state.year_range

    run = st.button("▶ Run Simulation", type="primary", use_container_width=True)

    if run:
        if end_year < start_year:
            st.error("End year must be greater than or equal to start year.")
        elif not crop_path:
            st.warning("Select or upload an APSIM file first.")
        elif point is None or point.lat is None or point.lon is None:
            st.warning("Select a location on the map.")
        else:
            lonlat = (point.lon, point.lat)
            crop_edits = state.node_edits.get(crop_path, {})
            print(crop_edits)

            try:
                with st.spinner(f"Running {Path(crop_path).name}..."):
                    df, summary = run_simulation(
                        apsim_obj=apsim,
                        state=state,
                        crop_path=crop_path,
                        lonlat=lonlat,
                        start_year=start_year,
                        end_year=end_year,
                        crop_node_edits=crop_edits,
                    )
                import sys

                if 'win' in sys.platform:
                    import winsound

                    winsound.Beep(1250, 760)
                state.last_results = {
                    "dataframe": df,
                    "summary": summary,
                }
                st.success("Simulation completed successfully.")

            except Exception as e:
                st.error(f"Simulation failed: {e}")


# =========================================================
# PAGE: RESULTS
# =========================================================
elif selected == "Results":
    st.title("Results")

    result_block = state.last_results
    data = result_block.get("dataframe") if result_block else None

    if data is None:
        st.info("Run simulation first")
        st.stop()

    table_options = ['Auto', *state.db_tables]
    tb = st.selectbox("Select a table", options=table_options, key="ui_result_table")
    stat = st.selectbox(
        "Key metric statistic",
        options=["mean", "median", "max", "min", "std"],
        key="ui_result_stat",
    )

    if tb != 'Auto':
        df = data[data["source_table"] == tb].copy()
        df.dropna(axis=1, how="all", inplace=True)
    else:
        df = data
    drop_cols = {'longitude', 'latitude', 'OBJECTID', 'Month', 'Year', 'Date'}
    for col in drop_cols:
        if col in df:
            df.drop(col, axis=1, inplace=True)
    summary = getattr(df, stat)(numeric_only=True)

    st.subheader("Key Metrics")
    cols = st.columns(4)
    for i, (k, v) in enumerate(summary.items()):
        if k.startswith('year'):
            ...
        cols[i % 4].metric(k, f"{v:.2f}")

    st.markdown("---")
    t_msg = f"from {tb} table" if tb else ""
    st.subheader(f"Simulation Output {t_msg}")
    st.dataframe(df, use_container_width=True)

    csv = df.to_csv(index=False)
    st.download_button("Download CSV", csv, "apsim_results.csv")
# change to the graphics tab
elif selected == "Graphics":

    # --------------------------------------------------
    # INIT STATE (CRITICAL)
    # --------------------------------------------------
    if "plots" not in st.session_state:
        st.session_state.plots = 1

    if "plot_configs" not in st.session_state:
        st.session_state.plot_configs = {}

    # --------------------------------------------------
    # NUMBER OF PLOTS (PERSISTENT)
    # --------------------------------------------------
    nop = plot_configs.total_plots if plot_configs.total_plots is not None else 1
    n_plots = st.number_input(
        "Number of plots",
        value=nop,
        max_value=6,
        key="No_of_plots"
    )
    plot_configs.total_plots = n_plots


    # GRAPHIC COMPONENT

    def graphic(prefix):
        graph_df = pd.DataFrame()
        if prefix not in plot_configs.plots:
            plot_configs.plots[prefix] = {}
        config = plot_configs.plots[prefix]
        result_block = state.last_results
        data = result_block.get("dataframe") if result_block else None

        if data is None:
            st.info("Run simulation first")
            return
        DEFAULT_TABLE = 'AUTO'
        table_options = [DEFAULT_TABLE, *state.db_tables]
        table = config.get('table', DEFAULT_TABLE)
        if table not in table_options:
            table_index = table_options.index(DEFAULT_TABLE)
        else:
            table_index = table_options.index(table)
        tb = st.selectbox(
            "Select a table",
            options=table_options,
            key=f"ui_{prefix}_table", index=table_index

        )
        config['table'] = tb
        # DATA set up
        if tb != DEFAULT_TABLE and tb in data.source_table.unique():
            graph_df = data[data["source_table"] == tb].copy()
            graph_df.dropna(axis=1, how="all", inplace=True)
        elif tb != DEFAULT_TABLE and tb not in set(data.source_table):
            graph_df = data
        elif tb == DEFAULT_TABLE:
            graph_df = data.copy()
        elif tb == DEFAULT_TABLE and tb in set(data.source_table):
            st.warning('Reserved Auto table name detected in dataframe')
            graph_df = data[data["source_table"] == tb].copy()
        else:
            st.error('something wrong occured with table selection')

        if graph_df.empty:
            st.warning("No data available")
            return
        graph_df =graph_df.reset_index(drop=True)

        # --------------------------------------------
        # FILTER (FIXED KEY BUG HERE 🔥)
        # --------------------------------------------
        from streamlit_ace import st_ace

        # code = st.text_area(
        #     "Expression",
        #     placeholder="e.g. ratio = x / y", key=f'ui_{prefix}_test_area'
        # )
        #
        # if code:
        #     try:
        #         df = df.copy()  # avoid mutating original
        #
        #         df.eval(code, inplace=True)
        #
        #         st.success("Expression applied successfully")
        #
        #
        #     except Exception as e:
        #         st.error(f"Invalid expression: {e}")
        numeric_cols = graph_df.select_dtypes(include="number").columns.tolist()
        all_cols = graph_df.columns.tolist()
        fb = config.get("filter_data_by")
        if fb:
            ft_index = all_cols.index(fb)
            print(ft_index)
        else:
            ft_index = 0
        if fb:
            filter_by = st.selectbox(
                "Filter by column",
                [fb, *all_cols],
                key=f"ui_u{prefix}_filter_by",

            )
        else:
            filter_by = st.selectbox(
                "Filter by column",
                [None, *all_cols],
                key=f"ui_u{prefix}_filter_by", index=ft_index,

            )

        config["filter_data_by"] = filter_by

        if filter_by:
            values = graph_df[filter_by].dropna().unique().tolist()
            vas = config.get('filter_vals') or []
            saved_vals = [v for v in vas if v in values]
            selected_values = st.multiselect(
                "Select values",
                options=values,
                key=f"uii_{prefix}_filter_vals",
                default=saved_vals
            )
            config["filter_vals"] = selected_values
            if selected_values:
                graph_df = graph_df[graph_df[filter_by].isin(selected_values)]

        col1, col2 = st.columns(2)

        # --------------------------------------------
        # LEFT PANEL
        # --------------------------------------------
        with col1:
            sub_col1, sub_col2 = st.columns(2)

            with sub_col1:
                sc1, sc2 = st.columns(2)
                with sc1:
                    chart_options = ["line", "bar", "box", "cat", "scatter", "heatmap"]
                    chart = config.get('chart')
                    if chart is not None:
                        chart_index = chart_options.index(chart)
                    else:
                        chart_index = 0
                    chart_type = st.selectbox(
                        "Chart Type",
                        chart_options,
                        key=f"ui_{prefix}_chart", index=chart_index
                    )
                    # plot_configs.set(prefix, key=chart, value=chart_type)
                    config["chart"] = chart_type
                    x, y = config.get('x'), config.get('y')
                    if x and y and y in graph_df.columns:
                        x_col = st.selectbox("X-axis", options=[x, *all_cols], key=f"{prefix}_x")
                        y_col = st.selectbox("Y-axis", options=[y, *numeric_cols], key=f"{prefix}_y")
                    else:
                        x_col = st.selectbox("X-axis", options=all_cols, key=f"{prefix}_x")
                        y_col = st.selectbox("Y-axis", options=numeric_cols, key=f"{prefix}_y")

                    config["x"] = x_col
                    config["y"] = y_col
                    hue = config.get('hue')
                    if hue:
                        hue_col = st.selectbox(
                            "Hue / Group (optional)",
                            options=[hue, None, *all_cols],
                            key=f"ui_{prefix}_hue"
                        )
                    else:
                        hue_col = st.selectbox(
                            "Hue / Group (optional)",
                            options=[None, *all_cols],
                            key=f"ui_{prefix}_hue"
                        )

                    config["hue"] = hue_col
                    stati = config.get('stat')
                    if stati:
                        stat = st.selectbox(
                            "Statistic",
                            [stati, 'none', "mean", "median", "max", "min", "std"],
                            key=f"ui_{prefix}_stat"
                        )
                    else:
                        stat = st.selectbox(
                            "Statistic",
                            ['none', "mean", "median", "max", "min", "std"],
                            key=f"ui_{prefix}_stat"
                        )
                    config["stat"] = stat
                    sort_type = config.get('sort_type', 'Ascending')
                    if sort_type == 'Ascending':
                        sort_options = [sort_type, 'Descending']
                    else:
                        sort_options = [sort_type, 'Ascending']
                    sort = st.selectbox('Sort', sort_options, key=f"{prefix}_sortv")
                    config['sort_type'] = sort

                    sort_ascending = {'Ascending': True, 'Descending': False}[sort]

                    if stat != "none" and x_col and y_col:
                        graph_df = graph_df.groupby(x_col)[y_col].agg(stat).reset_index()
                with sc2:
                    # plot aspect
                    chart_aspect = st.slider(
                        "Plot aspect size",
                        value=config.get("aspect", 1.0),
                        max_value=4.0,
                        min_value=0.8,
                        key=f"ui_{prefix}_aspect"
                    )
                    # plot_configs.set(prefix, key=chart, value=chart_type)
                    config["aspect"] = chart_aspect
                    xt, yt = config.get('xt'), config.get('yt')
                    dt_options = ['auto', "string", "int", "float", "datetime", 'cats']
                    if x and y and y in graph_df.columns:
                        x_dtype = st.selectbox("X-dtype", options=[xt, *dt_options], key=f"{prefix}_xt")
                        y_dtype = st.selectbox("Y-dtype", options=[yt, *dt_options], key=f"{prefix}_yt")
                    else:
                        x_dtype = st.selectbox("X-dtype", options=dt_options, key=f"{prefix}_xt")
                        y_dtype = st.selectbox("Y-dtype", options=dt_options, key=f"{prefix}_yt")
                    if x_dtype != 'auto' and x_dtype != 'cats':
                        if x_dtype == 'datetime':
                            graph_df[x_col] = pd.to_datetime(graph_df[x_col], format="%d-%b", errors='coerce')
                        else:
                            graph_df[x_col] = graph_df[x_col].astype(x_dtype)
                    if x_dtype == 'cats':
                        graph_df[x_col] = pd.Categorical(
                            graph_df[x_col],
                            categories=graph_df[x_col].unique(),
                            ordered=True
                        )
                    if y_dtype != 'auto' and y_dtype != 'cats':
                        graph_df[y_col] = graph_df[y_col].astype(x_dtype)

                    config["xt"] = x_dtype
                    config["yt"] = y_dtype
                    hue = config.get('hue-cats')

                    hue_cat = st.selectbox(
                        "Hue categories",
                        options=[hue],
                        key=f"ui_{prefix}_hue-cat"
                    )
                    config["hue-cats"] = hue_cat
                    fliers = config.get('show_fliers', True)
                    if fliers:
                        box_flyers = st.selectbox(
                            "Turn off flyers (box only)",
                            [fliers, False],
                            key=f"ui_{prefix}_box_flyers"
                        )
                    else:
                        box_flyers = st.selectbox(
                            "Turn off flyers (box only)",
                            [fliers, True],
                            key=f"ui_{prefix}_box_flyers"
                        )
                    config['show_fliers'] = box_flyers
                    cmaps = ["viridis", "plasma", "inferno", "magma", "cividis", 'auto']
                    cmp = config.get('cmap')

                    cmpa_index = cmaps.index(cmp) if cmp in cmaps else 0
                    cmap = st.selectbox("Colormap", cmaps, key=f"ui_{prefix}-cmaps", index=cmpa_index)
                    config['cmap'] = cmap

                    lt = st.selectbox("Select line type", ['continuous', 'dotted'], key=f"ui_{prefix}lt")
                    plot_width = st.slider("Pick width of the plot", min_value=4, max_value=20, value=8,
                                           key=f"ui_{prefix}_pw")

            with sub_col2:
                order = config.get("ordered_cats", [])

                all_values = graph_df[x_col].dropna().unique().tolist()

                sv = st.multiselect(
                    "Select values in your order",
                    options=all_values,  # 🔥 always full list
                    default=order,  # 🔥 preserves selection
                    key=f"uii_{prefix}_filter_ordered",
                )

                config["ordered_cats"] = sv
                if len(sv) != len(graph_df[x_col].unique()) and sv:
                    pass
                    st.warning('selected values are less than expected')
                cat_x = set(graph_df[x_col])
                sv= set(sv)
                if len(sv.intersection(cat_x)) == len(sv):
                    graph_df[x_col] = pd.Categorical(
                        graph_df[x_col],
                        categories=sv,
                        ordered=True
                    )
                    graph_df.reset_index(drop=True, inplace=True)
                else:
                    st.warning('selected values do not match')

                    # df = df.sort_values(x_col)
                # store order explicitly

                xlabel = st.text_input(
                    "X-axis label",
                    value=config.get("xlabel", x_col),
                    key=f"{prefix}_x_axis_label"
                )
                ylabel = st.text_input(
                    "Y-axis label",
                    value=config.get("ylabel", y_col),
                    key=f"ui_{prefix}_y_axis_label"
                )

                xlabel_size = st.number_input(
                    "X label font size",
                    value=config.get("xlabel_size", 16),
                    key=f"ui_{prefix}_xlabel_size"
                )

                ylabel_size = st.number_input(
                    "Y label font size",
                    value=config.get("ylabel_size", 16),
                    key=f"ui_{prefix}_ylabel_size"
                )

                xtick_angle = st.slider(
                    "X ticks angle",
                    value=config.get("xtick_angle", 90),
                    max_value=360,
                    min_value=0,
                    key=f"ui_{prefix}_xtick_angle"
                )
                saved_error_bar = config.get('error_bars_on_of', None)
                if saved_error_bar:
                    options = [saved_error_bar, None, 'sd', 'se']
                else:
                    options = [saved_error_bar, 'sd', 'se']
                error_bar = st.selectbox('Turn of error bars', options, key=f"ui_{prefix}_error_bar_switch")
                config['error_bars_on_of'] = error_bar

                config["xlabel"] = xlabel
                config["ylabel"] = ylabel
                config["xlabel_size"] = xlabel_size
                config["ylabel_size"] = ylabel_size
                config["xtick_angle"] = xtick_angle

        # --------------------------------------------
        # PLOT
        # --------------------------------------------
        with col2:
            st.selectbox('legend position', ['Left', 'right'],
                         key=f"ui_{prefix}_legend_position")
            try:
                data = graph_df.sort_values(by=x_col, ascending=sort_ascending)
                data_ans = data.copy()
                if hue_col:
                    data_ans[hue_col] = data_ans[hue_col].astype('str')
                kwargs = {}
                if chart_type != 'box':
                    kwargs.setdefault('errorbar', error_bar)
                if cmap and cmap != 'auto':
                    kwargs.setdefault('palette', cmap)
                fig = plot_chart(
                    data_ans,
                    chart_type=chart_type,
                    x=x_col,
                    y=y_col,
                    hue=hue_col,
                    **kwargs
                )

                plt.tight_layout()
                plt.xlabel(xlabel, fontsize=xlabel_size)
                plt.ylabel(ylabel, fontsize=ylabel_size)
                plt.xticks(rotation=xtick_angle)

                st.pyplot(fig)

            except Exception as e:
                st.error(f"Plot failed: {e}")


    # RENDER ALL PLOTs
    for i in range(plot_configs.total_plots):
        st.markdown(f"### Plot {i + 1}")
        graphic(i)
# =========================================================
# PAGE: SETTINGS
# =========================================================
elif selected == "Settings":
    st.title("Settings")
    st.subheader("APSIM Configuration")

    with st.expander("Edit APSIM Binary Path", expanded=True):
        bin_path_input = st.text_input(
            "Path to APSIM bin directory",
            value=state.settings.bin_path,
            placeholder="e.g., C:/APSIM/bin",
            key="ui_bin_path_input",
        )

        col1, col2 = st.columns(2)

        with col1:
            if st.button("Validate Path", key="btn_validate_path"):
                if os.path.exists(bin_path_input):
                    st.success("Valid APSIM path")
                else:
                    st.error("Invalid path")

        with col2:
            if st.button("Submit Bin Path", key="btn_submit_bin_path"):
                if os.path.exists(bin_path_input):
                    state.settings.bin_path = bin_path_input
                    st.success("Path saved successfully. Reload the app to recreate APSIM with the new path.")
                else:
                    st.error("Cannot submit an invalid path")

    st.markdown("### Current Configuration")
    st.code(state.settings.bin_path, language="bash")

    st.markdown("---")
    st.subheader("Session State (Debug)")
    with st.expander("View full app state"):
        st.write(state)

    st.markdown("---")
    st.subheader("Actions")
    col1, col2 = st.columns(2)

    with col1:
        if st.button("Clear Results", use_container_width=True, key="btn_clear_results"):
            state.last_results = None
            st.success("Results cleared")

    with col2:
        if st.button("Reset App", use_container_width=True, key="btn_reset_app"):
            del st.session_state["app_state"]
            st.success("App reset")
