import geopandas as gpd
import networkx as nx
import pytest

from stormcatchments import network

@pytest.fixture
def net_johnson():
  storm_lines = gpd.read_file('tests/test_data/johnson_vt/storm_lines.shp')
  storm_pts = gpd.read_file('tests/test_data/johnson_vt/storm_pts.shp')
  net = network.Network(storm_lines, storm_pts)
  return net


def test_add_upstream_simple_johnson(net_johnson):
  downstream_pt = net_johnson.pts[net_johnson.pts['OBJECTID']==244244]
  net_johnson.add_upstream_pts(downstream_pt)
  assert len(net_johnson.G.nodes()) == 3


def test_add_upstream_complex_johnson(net_johnson):
  downstream_pt = net_johnson.pts[net_johnson.pts['OBJECTID']==21134]
  net_johnson.add_upstream_pts(downstream_pt)

  # Ensure correct number of nodes are present
  assert len(net_johnson.G.nodes()) == 34

  # Ensure all node coordinates are unique
  coords = set()
  for _, pt in nx.get_node_attributes(net_johnson.G, 'geometry').items():
    assert (pt.x, pt.y) not in coords, 'Graph has a duplicate coordinate'
    coords.add((pt.x, pt.y))


def test_add_upstream_twice_johnson(net_johnson):
  # 3 nodes
  downstream_pt = net_johnson.pts[net_johnson.pts['OBJECTID']==244244]
  net_johnson.add_upstream_pts(downstream_pt)

  # 5 nodes, disconnected from previous subgraph
  downstream_pt = net_johnson.pts[net_johnson.pts['OBJECTID']==244153]
  net_johnson.add_upstream_pts(downstream_pt)

  assert len(net_johnson.G.nodes()) == 8


def test_get_outlet_johnson(net_johnson):
  downstream_pt = net_johnson.pts[net_johnson.pts['OBJECTID']==21134]
  net_johnson.add_upstream_pts(downstream_pt)
  assert net_johnson.get_outlet(20847) == 21134


def test_find_downstream_simple_johnson(net_johnson):
  upstream_pt = net_johnson.pts[net_johnson.pts['OBJECTID']==245051]
  downstream_pt = net_johnson.find_downstream_pt(upstream_pt)
  assert downstream_pt.OBJECTID == 244132


def test_generate_catchment_graphs_johnson(net_johnson):
  initial_catchment = gpd.read_file('tests/test_data/johnson_vt/initial_catchment.shp')
  net_johnson.generate_catchment_graphs(initial_catchment['geometry'])
  pt_types = [
    pt_type for _, pt_type in nx.get_node_attributes(net_johnson.G, 'Type').items()
  ]
  # 3 catchbasins
  assert pt_types.count(2) == 3
  # 3 culvert outlets
  assert pt_types.count(9) == 3
