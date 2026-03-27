import datetime
import seaborn as sns
import matplotlib.pyplot as plt

def render_params(st, params, prefix=""):
    updated = {}

    for key, value in params.items():
        widget_key = f"{prefix}_{key}"

        # --- Nested dictionary ---
        if isinstance(value, dict):
            st.markdown(f"### 🔹 {key}")
            updated[key] = render_params(value, prefix=widget_key)

        # --- Datetime ---
        elif isinstance(value, datetime.datetime):
            updated[key] = st.date_input(
                key,
                value=value.date(),
                key=widget_key
            )

        # --- Boolean ---
        elif isinstance(value, bool):
            updated[key] = st.checkbox(
                key,
                value=value,
                key=widget_key
            )

        # --- Integer ---
        elif isinstance(value, int):
            updated[key] = st.number_input(
                key,
                value=value,
                step=1,
                key=widget_key
            )

        # --- Float ---
        elif isinstance(value, float):
            updated[key] = st.number_input(
                key,
                value=value,
                key=widget_key
            )

        # --- List ---
        elif isinstance(value, list):
            text_val = ", ".join(map(str, value))

            user_input = st.text_area(
                key,
                value=text_val,
                key=widget_key
            )

            # Clean + parse list
            updated[key] = [
                v.strip() for v in user_input.split(",") if v.strip()
            ]

        # --- String / fallback ---
        else:
            updated[key] = st.text_input(
                key,
                value=str(value),
                key=widget_key
            )

    return updated





def plot_chart(df, chart_type, x=None, y=None, hue=None,  **kwargs):
    fig, ax = plt.subplots()

    if chart_type == "line":
        sns.lineplot(data=df, x=x, y=y, hue=hue, ax=ax, **kwargs)

    elif chart_type == "bar":
        sns.barplot(data=df, x=x, y=y, hue=hue, ax=ax, **kwargs)

    elif chart_type == "box":
        sns.boxplot(data=df, x=x, y=y, hue=hue, ax=ax, **kwargs)

    elif chart_type == "cat":
        sns.catplot(data=df, x=x, y=y, hue=hue, kind="strip", **kwargs)

    elif chart_type == "scatter":
        sns.scatterplot(data=df, x=x, y=y, hue=hue, ax=ax, **kwargs)

    elif chart_type == "heatmap":
        pivot = df.pivot_table(index=x, columns=y, values=hue, aggfunc="mean",)
        sns.heatmap(pivot, ax=ax)

    return fig
