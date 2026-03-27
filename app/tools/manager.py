from pathlib import Path
from typing import Union

from langchain.tools import tool
from apsimNGpy import ApsimModel, NodeNotFoundError

workspace = Path(__file__).parent / 'work_space'
workspace.mkdir(exist_ok=True)


@tool
def apply_fertilizer(model: str, amount: float):
    """
    Apply fertilizer to an APSIM model by modifying the fertilizer amount
    in the Manager script named "Sow using a variable rule".

    This tool edits the fertilizer amount parameter and saves the updated
    APSIM model.

    IMPORTANT
    ---------
    The returned value is the path to the updated APSIM model file.
    The AI agent should pass this returned path to subsequent tools that
    run simulations or extract results.

    This tool modifies the model configuration but does NOT run the simulation.

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

    amount : float
        Fertilizer amount to apply (e.g., nitrogen in kg/ha).

    Returns
    -------
       dict
           keys:
           - model: str or Path to the updated APSIM model file. This path should be used as
                the input model for subsequent tools such as run_apsim_model or output
                extraction tools.
            - success: bool
                True or 1 indicates success of fertilizer application
            - error
                If the modification fails, error might be provided.

    Typical Agent Workflow
    ----------------------
    1. out= apply_fertilizer(model=model, amount=amount)
    2. run_apsim_model(model=out['model'], ...)


    Example User Requests
    ---------------------
    - "Apply 50 kg/ha nitrogen to the model"
    - "Increase fertilizer rate to 120"
    - "Set fertilizer amount to 80 kg/ha"
    """

    apsim = ApsimModel(model)

    try:
        fileName = (workspace / f'copy_{amount}_{Path(apsim.path).name}').resolve()
        apsim.edit_model(
            model_type="Models.Manager",
            model_name="Fertilise at sowing",
            Amount=amount)

        apsim.save(fileName, reload=False)

        return {'success': True, 'model': apsim.path}

    except ValueError as e:
        params = apsim.inspect_model_parameters(
            model_type="Models.Manager",
            model_name="Sow using a variable rule"
        )

        return {
            "success": False,
            "error": str(e),
            "suggestion": f"Explain the error and show available parameters: {list(params.keys())}"
        }

    except NodeNotFoundError:
        return {
            "success": False,
            "error": "Node not found",
            "suggestion": "Explain to the user that the model does not qualify."
        }


@tool
def edit_node(model: str, param_patch: dict, file_name=None):
    """
    Edit parameters of an existing APSIM node by its full path.

    Parameters
    ----------
    model : str
        Name or path of the APSIM model.

        - If the value does NOT end with ".apsimx", it is interpreted as
          the name of a built-in APSIM example model (e.g., "Maize", "Wheat", "Soybean").
        - If the value ends with ".apsimx", it is interpreted as a path
          to a local APSIM model file.
    param_patch : dict
        One or more keyword arguments representing parameter names
        and their new values.

        Example:
        {Population=8, path = '.Simulations.Simulation.Field.Sow using a variable rule',
        RowSpacing=0.75}
    file_name:str default is None
         name where to save the filename, should end with .apsimx file extension. The default is None implying an automatically generated file_name
         example e.g., "D:/work-space/edited_maize.apsimx"
    Agent reasoning:
    ------------------
    Inspect the model structure or model param get the path use the create_param_patch tool to generate a param patch data for this tool

    Returns
    -------
    dict
        A dictionary containing:
            - success (bool)
            - model (str): saved model path (if successful)
            - updated_parameters (dict)
            - error (str, optional)

    Typical Usage Guidance for the Tool
    -----------------------------------

    Before calling this tool, first inspect the model to identify the correct node
    and its available parameters.

    Workflow
    --------
    1. Inspect the APSIM model to locate the relevant node.
    2. Examine the available parameter names in that node.
    3. Use the exact parameter name (correct spelling) when calling this tool.
    4. Provide the value specified by the user.

    Important
    ---------
    If the user does not explicitly provide the node path, the agent should
    inspect the model to determine which node contains the requested rule or
    component.

    Example Scenario
    ----------------
    User request:
        "Edit the Population parameter in the 'Sow using a variable rule'."

    Agent reasoning:
    1. Inspect the model to find which node contains "Sow using a variable rule".
    2. Identify the node path and confirm the available parameters.
    3. Locate the parameter named "Population".
    4. Call this tool with:
           node_path = <path_to_sow_using_variable_rule>
           Population = <user_provided_value>

    The tool should only be called after confirming that the parameter exists
    in the identified node.
    """
    print(param_patch)
    try:
        # Load model
        apsim_model = ApsimModel(model)

        # Ensure parameters were provided
        if not param_patch:
            return {
                "success": False,
                "error": "No parameters were provided to update."
            }

        # Edit node
        apsim_model.edit_model_by_path(**param_patch)

        # Save model

        apsim_model.save(file_name=file_name) if file_name else apsim_model.save()

        return {
            "success": True,
            "model": apsim_model.path,
            "updated_parameters": param_patch,
            "message": "Node updated successfully. You may now run the model."
        }

    except Exception as e:
        return {
            "success": False,
            "model": model,
            "parameter_patch": param_patch,
            "error": str(e)
        }


@tool
def inspect_params(model, node_path, parameters: Union[str, list, tuple] = None):
    """
    Inspects the parameters ata given node based on the node path
    Paramters
    -------------
    model : str
        Name or path of the APSIM model to run.

        If the value does NOT contain at the end ".apsimx", it should be interpreted as the
        name of a built-in APSIM example model (e.g., "Maize", "Wheat", 'Soybean', etc.), otherwise.

        If the value contains ".apsimx" at the end, it is interpreted as a path to a
        local APSIM model file on the user's computer.
        Examples:
            Maize.apsimx this means the model resides in the current directory, but Maize without .apsimx
               sufix indicates built-in or defaut maize model ,  "D:/models/maize.apsimx" might imply model at that fullpath
    node_path : str
        full path of the node relative to the root of the simulations tree in the model
        Examples: '.Simulations.Simulation.Field.Sow using a variable rule
    parameters : str | tuple | list
        specific parameters to return values for
    typical work flow
    If the user asks for paramters in the soil Physical node; inspect the model tree or structure and see the full node paths with Models.Soils.Physical types
    Returns
    -----------
       a dict
    """
    with ApsimModel(model) as model:
        try:
            p = model.inspect_model_parameters_by_path(path=node_path)
            return p
        except Exception as e:
            return {'status': 'error', 'message': str(e)}


@tool
def create_param_patch(node_path: str, **parameters):
    """
    Create a JSON-style parameter patch for editing an APSIM model node.

    This tool prepares a dictionary containing the node path and parameter
    values that should be modified in the APSIM model. The returned structure
    can be passed to another tool that performs the actual model edit.

    Parameters
    ----------
    node_path : str
        Full path of the node relative to the root of the simulations tree
        in the APSIM model.

        Example:
            ".Simulations.Simulation.Field.Sow using a variable rule"

    parameters : dict
        One or more parameter names with the values provided by the user.
        The parameter names must match the exact spelling of the parameters
        available in the node.

        Example:
            Population=120
            Amount=50
            Depth=30

    Returns
    -------
    dict
        A dictionary containing the node path and the parameters to update.

        Example:
        {
            "path": ".Simulations.Simulation.Field.Sow using a variable rule",
            "Population": 120
        }

    Typical Workflow
    ----------------
    1. Inspect the model tree to locate the relevant node.
    2. Inspect the node parameters to identify available parameter names.
    3. Use the exact parameter name returned by the inspection tool.
    4. Call this tool to create the parameter patch.
    5. Pass the returned dictionary to a tool that applies the model edits.

    Example
    -------
    User request:
        "Set Population to 120 in the Sow using a variable rule."

    Agent reasoning:

     Call this tool before editing any node use the results

            create_param_patch(
                node_path=".Simulations.Simulation.Field.Sow using a variable rule",
                Population=120
            )

    The returned patch can then be used by another tool that updates the APSIM model.
    """

    return {"path": node_path, **parameters}


@tool
class ApsimModelAgentTools:
    """
    A tool that starts the workflow
    """

    def __init__(self, apsim_model):
        """
        Workflow starts here
        :param apsim_model:
        """
        self.model = apsim_model

    def run(self):
        return self.model.run()

    def inspect(self, node):
        return self.model.inspect(node)

    def set_parameter(self, path, value):
        self.model.set_value(path, value)
