# stormcatchments
## Stormwater network aware catchment delineation

In development, currently only configured for [Vermont Agency of Natural Resources stormwater infrastructure data](https://gis-vtanr.hub.arcgis.com/maps/VTANR::stormwater-infrastructure/explore?location=43.609172%2C-72.968811%2C14.15).

Various dependencies include:
```
geopandas
networkx
pysheds
```

## Example Usage

### Imports
```python
import geopandas as gpd
from stormcatchments import delineate, network, terrain
```
### Preprocess terrain data
```python
grid, fdir, acc = terrain.preprocess_dem('tests/test_data/johnson_vt/dem.tif')
```
### Read infrastructure data
```python
storm_lines = gpd.read_file('tests/test_data/johnson_vt/storm_lines.shp')
storm_pts = gpd.read_file('tests/test_data/johnson_vt/storm_pts.shp')
```
### Initialize Network and Delineate objects
```python
net = network.Network(storm_lines, storm_pts)
delin = delineate.Delineate(net, grid, fdir, acc, 6589)
```
### Delineate a stormcatchment
```python
# (x, y) coordinates in same CRS as grid
pour_pt = (484636, 237170)
stormcatchment = delin.get_stormcatchment(pour_pt)
```
