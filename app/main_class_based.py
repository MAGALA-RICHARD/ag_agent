import os
import re
import uuid
from pathlib import Path
from typing import Union

import apsimNGpy
from apsimNGpy import Apsim, ApsimModel
from dotenv import load_dotenv
from langchain.tools import tool

# current package modules
__package__ = 'app'  # allow for relative imports

from .resources.utils import get_season_dates
from .tools.manager import edit_node, inspect_params, create_param_patch

load_dotenv(Path('.api.env').resolve())
api_key = os.getenv('API_KEY')
apsim = Apsim()

OPENAI_API_KEY = api_key
AUTO = 'AUTO'


@tool
def get_weather_from_web(model_obj: apsim.ApsimModel, lonlat: tuple, start: int, end: int):
    """
    Retrieve weather data from an online source and attach it to an APSIM model.

    This tool downloads meteorological data for a specified geographic location
    and time period, then saves it as a temporary APSIM-compatible `.met` weather
    file. The weather file is automatically linked to the provided APSIM model.

    Parameters
    ----------
    model_obj : ApsimModel
        An initialized APSIM model object managed by apsimNGpy. The weather data
        retrieved by this tool will be attached directly to this model.

    lonlat : tuple[float, float]
        Geographic coordinates representing the location of the weather data
        request. The tuple must be provided as (longitude, latitude).

        Example:
        (-93.62, 42.03)

    start : int
        Start year or start date for the weather data retrieval.

        Examples:
        2000


    end : int or str
        End year or end date for the weather data retrieval.

        Examples:
        2020


    Behavior
    --------
    1. Generates a unique temporary weather file name.
    2. Downloads weather data for the requested location and time range.
    3. Stores the weather data in a `.met` file.
    4. Links the weather file to the APSIM model so it will be used during simulation.

    Notes for AI Agents
    -------------------
    Use this tool when the user requests weather data for a specific location
    or when a simulation requires weather input but no weather file has been provided.

    Examples of user requests that should trigger this tool:
        - "Download weather data for Ames, Iowa from 2000 to 2020."
        - "Use web weather data for latitude 42.03 and longitude -93.62."
        - "Get weather data for the model from 1990 to 2015."

    Returns
    -------
    None
        The weather file is attached directly to the APSIM model object.
    """
    file_name = f"{str(uuid.uuid4())}.met"
    model_obj.get_weather_from_web(
        lonlat=lonlat,
        start=start,
        end=end,
        filename=file_name
    )
    model_obj.save()


@tool
def create_workspace(workspace_name: str) -> None:
    """
    ask the use to provide space directory
    Parameters:
    ------------
    workspace_name : str
         name of the work space directory path
    """
    os.chdir(workspace_name)


@tool
def check_available_columns(model: str, data_table: str | None = None) -> dict:
    """
    Retrieve available report variables from an APSIM model.

    This tool inspects the APSIM model report components and returns the
    variables available in the Report node(s). It should be used when the user
    asks which output variables are available in the model (e.g., Yield,
    Biomass, LAI, etc.).

    Parameters
    ----------
    model : str
        Path to the APSIM model file (.apsimx).

    data_table : str, optional
        Name of the Report component to inspect. If not provided, the function
        automatically discovers all available Report components in the model.

    Returns
    -------
    dict
        Dictionary mapping report table names to the list of variables
        available in each table.

        Example:
        {
            "Report": ["Yield", "Biomass", "LAI"],
            "DailyReport": ["Rain", "Temp", "SoilWater"]
        }

    When to Use
    -----------
    The AI agent should call this tool when:

    - The user asks which outputs are available in the APSIM model.
    - The agent needs to discover variables before extracting results.
    - A tool requiring a variable name fails due to an unknown variable.

    Example User Requests
    ---------------------
    - "What variables are available in this APSIM model?"
    - "List the report outputs."
    - "Which columns can I extract from the simulation results?"
    """

    with apsim.ApsimModel(model) as model:

        if data_table is None:
            data_table = model.inspect_model('Models.Report', fullpath=False)

        report_vars = {}

        for var in data_table:
            params = model.inspect_model_parameters(
                model_type="Models.Report",
                model_name=var
            )

            # report_vars[var] = [re.sub(r"\[|\]", "", s) for s in params['VariableNames']]
            v = [re.sub(r"\[|\]", "", s) for s in params['VariableNames']]
            out = []
            for values in v:
                obj = re.search(r"as\s+(\w+)$", values)
                str_var = obj.group(1) if obj else []
                if str_var:
                    out.append(str_var)
                else:
                    out.append(values)
        report_vars[var] = out

        return report_vars


@tool
def tree(model):
    """
    A tool that print out or inspect a tree of the model. show how each model is linked to the other.
    returns a dictionary with the node path as the key and node types as the value

    Parameters
    ------------
     model : str
        Name or path of the APSIM model to run.

        If the value does NOT contain at the end ".apsimx", it should be interpreted as the
        name of a built-in APSIM example model (e.g., "Maize", "Wheat", 'Soybean', etc.), otherwise.

        If the value contains ".apsimx" at the end, it is interpreted as a path to a
        local APSIM model file on the user's computer.

        Examples
        --------
        "Maize"
            show the model structure of the built-in APSIM Maize example model.

        "Maize.apsimx"
            show the model structure of Runs a local APSIM model file in the current directory.

        "D:/models/maize.apsimx"
            show the model structure of a local APSIM model file from the specified path.
    Returns
    ---------
    model tree as dict with keys containing path and values the node modely type


    """
    with apsim.ApsimModel(model) as model:
        try:
            tree = model.tree(console=False)
            return {'success': True,
                    'tree': tree,
                    'suggestion': 'summarize the node types'}
        except:
            return {'success': False, 'suggestion': 'printing model to the console failed'}


def fetch_model(model):
    """Get the model path. This method or tool should be called first before any other tool can be called
    Parameters
    ----------
    model : str
        Name or path of the APSIM model to run.

        If the value does NOT contain at the end ".apsimx", it should be interpreted as the
        name of a built-in APSIM example model (e.g., "Maize", "Wheat", 'Soybean', etc.), otherwise.

        If the value contains ".apsimx" at the end, it is interpreted as a path to a
        local APSIM model file on the user's computer.

        Examples
        --------
        "Maize"
            Runs the built-in APSIM Maize example model.

        "Maize.apsimx"
            Runs a local APSIM model file in the current directory.

        "D:/models/maize.apsimx"
            Runs a local APSIM model file from the specified path.
    Returns
    ------------
    model : string
      str path to the model
    """
    if isinstance(model, str) and Path(model).suffix == ".apsimx":
        if not Path(model).exists:
            return{
                'error':f"{str(model)} does not exist"
            }
    apsim = ApsimModel(model)
    return apsim

def run_apsim_model():
   ...



tools = [run_apsim_model, get_weather_from_web, edit_node, create_param_patch,
         create_workspace,
         check_available_columns, inspect_params, tree]
if __name__ == '__main__':
    from langchain.agents import create_agent
    from langchain.chat_models import init_chat_model

    llm = init_chat_model(model='openai:gpt-4o', api_key=api_key)
    from langchain_openai import ChatOpenAI

    openai_agent = ChatOpenAI(
        model="gpt-5-nano",
        api_key=api_key, temperature=0.7),
    agent = create_agent(

        openai_agent,
        tools=tools

    )

    state = {"messages": []}
    while True:

        q = input("You: ")

        if q == "exit":
            break

        state["messages"].append({"role": "user", "content": q})
        try:

            result = agent.invoke(state)

            reply = result["messages"][-1].content

            print("Agent:", reply)

            state["messages"].append(
                {"role": "assistant", "content": reply}
            )
        except Exception as e:
            print(e)
