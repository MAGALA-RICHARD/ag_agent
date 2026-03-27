import os
from pathlib import Path

import pathlib
from apsimNGpy.manager.weathermanager import get_weather, _is_within_USA_mainland
from diskcache import Cache

cache = Cache("./cache_dir")


@cache.memoize()
def _fetch(_bin_path: str, pattern) -> list[str]:
    bp = Path(_bin_path).parent / 'Examples'
    return [p.stem for p in bp.rglob(pattern)]


def fetch_all_apsimx(bin_path: Path) -> list[str]:
    bpp = os.path.realpath(bin_path)
    return _fetch(bpp, pattern="*.apsimx")


def add_simulation(path, loader, name, sim):
    from apsimNGpy.core.model_tools import ModelTools
    model = loader(path)
    sim = model[sim]
    cloned = ModelTools.CLONER(sim)
    cloned.Name = name
    return cloned




@cache.memoize()
def fetch_cultivars(plant, loader, fp=False) -> set[str]:
    with loader(model=plant) as mod:
        out = mod.inspect_model('Models.PMF.Cultivar', fullpath=fp) or []
        return set(out)


def inspect_node(path, loader, node_type, fp=True, scope=None):
    with loader(model=path) as mod:
        if scope:
            return mod.inspect_model(node_type, fullpath=fp, scope=scope)
        else:
            return mod.inspect_model(node_type, fullpath=fp)


def fetch_sim(path, loader, name):
    with loader(path) as mod:
        return name, mod[name]


def inspect_node_params(path, loader, node_path):
    with loader(model=path) as mod:
        out = mod.inspect_model_parameters_by_path(node_path)
        if isinstance(out, dict):
            return out
        elif isinstance(out, (str, pathlib.Path)):
            # it is a weather file
            return {"FileName": out}


@cache.memoize()
def fetch_weather(lonlat, start, end, source='daymet') -> str:
    if not _is_within_USA_mainland(lonlat):
        source = 'nasa'
    pid = os.getpid()
    fileName = f"pid{pid}-{lonlat}{start}-{end}.met"
    return get_weather(lonlat, start=start, end=end, filename=fileName, source=source)


def get_season_dates(lonlat: tuple):
    """
    Return winter and summer start dates based on latitude.

    Parameters
    ----------
    lat : float
        Latitude
    lon : float (optional)
        Longitude (not required but included for interface consistency)
    year : int (optional)
        Year to compute seasons for

    Returns
    -------
    dict
        Winter and summer start dates
    """
    lat = lonlat[1]

    if lat >= 0:
        # Northern Hemisphere
        winter_start = '21-dec'
        summer_start = '21-jun'
    else:
        # Southern Hemisphere
        winter_start = '21-jun'
        summer_start = '21-dec'

    return {
        "winter_date": winter_start,
        "summer_date": summer_start
    }


if __name__ == "__main__":
    from apsimNGpy import get_apsim_bin_path, ApsimModel

    fa = fetch_all_apsimx(get_apsim_bin_path())

    # cache.clear()
    fetch_cultivar(plant='Maize', loader=ApsimModel)
