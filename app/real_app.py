from apsimNGpy import ApsimModel
import re

with ApsimModel('Maize', out='mgb_bean.apsimx') as model:
    model.edit_model(
        model_type="Models.Manager",
        model_name="Fertilise at sowing",
        Amount=0)
    model.run()
    df = model.results
    cs = model.tree(console=False)
    print(model.results.Yield.mean())
    model.edit_model_by_path('.Simulations.Simulation.Field.Sow using a variable rule', StartDate='1-Dec',
                             EndDate='10-may')
    model.run()
    print(model.results.Yield.mean())
