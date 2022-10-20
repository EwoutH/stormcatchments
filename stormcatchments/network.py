from collections import namedtuple
import geopandas as gpd
import pandas as pd
import networkx as nx
from typing import Optional
from shapely.geometry import LineString, MultiPoint, Point
import warnings

SINK_TYPES_VT = [   
    2, # Catchbasin
    8, # Culvert inlet
]

SOURCE_TYPES_VT = [
    5, # Outfall
    9, # Culvert outlet
]

def get_point_coords(pt_geom, decimals: int=None) -> tuple:
    '''
    Get and x, y coordinate tuple from a Point or MultiPoint shapely geometry

    Parameters
    ----------
    pt_geom: Point | MultiPoint
        shapely geometry object containing a point coordinate
    decimals: int (default None)
        Number of decimals to round coordinates to
    '''
    if isinstance(pt_geom, Point):
        x = pt_geom.x
        y = pt_geom.y
    elif isinstance(pt_geom, MultiPoint):
        x = pt_geom.geoms[0].x
        y = pt_geom.geoms[0].y
        if len(pt_geom.geoms) > 1:
            warnings.warn(
                f'A point at coordinate ({x}, {y}) has MultiPoint geometry with '
                'multiple point coordinates, only returning the first'
        )
    else:
        raise ValueError(
            f'Failed to get coords for Point with geometry type: {type(pt_geom)}'
        )
    if decimals is not None:
        x = round(x, decimals)
        y = round(y, decimals)
    
    return x, y


class Network:
    '''
    Parses through stormwater infrastructure point and line data to generate directional
    graphs represeting the connectivity of the infrastructure network.
    
    Attributes:
    -----------
    lines : gpd.GeoDataFrame
        All the stormwater infrastructure line features within the area of interest
    segments : gpd.GeoDataFrame
        All the stormwater infrastructure line geometry split into segments
    pts : gpd.GeoDataFrame
        All the stormwater infrastructure point features within the area of interest
    G : nx.DiGraph
        A list of all the graphs generated within the area of interest
    crs : pyproj.crs.crs.CRS
        The PyProj Coordinate Reference System of infrastructure data
    '''
    def __init__(
        self,
        storm_lines: gpd.GeoDataFrame,
        storm_pts: gpd.GeoDataFrame,
        coord_decimals: int=3,
        index_column: str='OBJECTID',
        type_column: Optional[str]='Type',
        sink_types: list=SINK_TYPES_VT,
        source_types: list=SOURCE_TYPES_VT,
    ):
        '''
        Parameters:
        ----------
        storm_lines: gpd.GeoDataFrame
            All the stormwater infrastructure line features within the area of interest
        storm_pts: gpd.GeoDataFrame
            All the stormwater infrastructure points features within the area of interest
        coord_decimals: int (default 3)
            Decimal to round line coordinates too, prevents problems with improper snapping
        index_column: str (default 'OBJECTID')
            Column name in storm_pts 
        type_column: str | None (default 'Type')
            Column in storm_pts GeoDataFrame that represents the type of each point
            (e.g., catchbasins, outfalls, culverts), set to None if IS_SOURCE and
            IS_SINK are preconfigured in the storm_pts GeoDataFrame
        sink_types: list (default SINK_TYPES_VT)
            List of type values that correspond to flow sinks, where flow enters at
            these points, such as a catchbasin
        source_types: list (default SOURCE_TYPES_VT)
            List of type values that correspond to flow sources, where flow exits at
            these points, such as an outfall 
        '''
        if storm_pts.crs != storm_lines.crs:
            raise ValueError(
                'Coordinate reference systems of point and line datasets must match'
            )
        self.crs = storm_pts.crs

        if index_column not in storm_lines:
            raise ValueError(
                'storm_lines does not contain the specified index column named: '
                f'{index_column}'
            )
        self.lines = storm_lines
        storm_lines = storm_lines.set_index(index_column)

        # Explode all lines into 2-vertex segments, add these as edges in a directional
        # graph with coordinate tuples as nodes. The DiGraph will initialize with two
        # edges connecting each node pair, one in each direction. Direction will be
        # revised later
        self.G = nx.DiGraph()
        self.directions_resolved = False
        all_segments = {}
        for line in storm_lines.itertuples(name='StormLine'):
            u_coords = line.geometry.coords[:-1]
            v_coords = line.geometry.coords[1:]
            # Round all coordinate values
            u_coords = [
                tuple(
                    [round(x, coord_decimals), round(y, coord_decimals)]
                ) for x, y in u_coords
            ]
            v_coords = [
                tuple(
                    [round(x, coord_decimals), round(y, coord_decimals)]
                ) for x, y in v_coords
            ]

            # TODO: Only need to add both edges if resolve direction with from_sources
            # method? Wait to do this?
            # Add edges in both directions between each vertex pair
            for u, v in zip(u_coords, v_coords):
                self.G.add_edge(u, v)
                self.G.add_edge(v, u)

            segments = list(map(LineString, zip(u_coords, v_coords)))
            all_segments[line.Index] = segments

        # Retain all segment data with the segment's source index stored in a column
        self.segments = gpd.GeoDataFrame()
        for src_index, segments in all_segments.items():
            segments = gpd.GeoDataFrame(geometry=gpd.GeoSeries(segments), crs=self.crs)
            segments[index_column] = src_index
            self.segments = self.segments.append(segments, ignore_index=True)

        if index_column not in storm_pts.columns:
            raise ValueError(
                'storm_pts does not contain a column with provided index column '
                f'name: {index_column}'
            )
        self.pts = storm_pts
        self.pts.set_index(index_column, inplace=True)

        # Deal with mapping of IS_SOURCE and IS_SINK in point data
        if type_column is not None and type_column not in storm_pts.columns:
            raise ValueError(
                'storm_pts does not contain a column with the provided type column '
                f'name: {type_column}'
            )
        if 'IS_SINK' in storm_pts.columns:
            if storm_pts.dtypes['IS_SINK'] != bool:
                raise ValueError('storm_pts column "IS_SINK" must be bool dtype')
        else:
            self.pts['IS_SINK'] = self.pts[type_column].apply(
                lambda x: True if x in sink_types else False
            )

        if 'IS_SOURCE' in storm_pts.columns:
            if storm_pts.dtypes['IS_SOURCE'] != bool:
                raise ValueError('storm_pts column "IS_SOURCE" must be bool dtype')
        else:
            self.pts['IS_SOURCE'] = self.pts[type_column].apply(
                lambda x: True if x in source_types else False
            )

        # Round all point coordinate values, also converting any MultiPoints to Points
        self.pts['geometry'] = self.pts['geometry'].apply(
            lambda geom: Point([get_point_coords(geom, coord_decimals)])
        )


    def to_StormPoint(self, pt) -> 'StormPoint':
        if isinstance(pt, gpd.GeoDataFrame):
            if len(pt) > 1:
                warnings.warn(
                    '_init_traverse() got multiple points, only keeping the first'
                )
            pt_iter = pt.itertuples(name='StormPoint')
            pt = next(pt_iter)
        elif isinstance(pt, pd.Series):
            # convert to StormPoint namedtuple
            field_names = self.pts.columns.to_list()
            field_names.insert(0, 'Index')
            pt = namedtuple('StormPoint', field_names)(pt.name, *pt)
        else:
            assert pt.__class__.__name__ == 'StormPoint', f'Expected pt to be a ' \
                'gpd.GeoDataFrame, pd.Series, or a StormPoint namedtuple, but got a ' \
                f'{pt.__class__.__name__}'
        return pt


    def has_StormPoint(self, pt) -> bool:
        '''Check if self.G contains a given StormPoint'''
        pt = self.to_StormPoint(pt)
        pt_x = pt.geometry.x
        pt_y = pt.geometry.y
        return self.G.has_node((pt_x, pt_y))


    def find_downstream_pt(self, pt) -> Optional['StormPoint']:
        '''Get a StormPoint containing the downstream/outlet point for a given point'''
        pt = self.to_StormPoint(pt)
        pt_x = pt.geometry.x
        pt_y = pt.geometry.y

        visited = set()
        downstream_pt = self.traverse_downstream((pt_x, pt_y), visited)
        return downstream_pt


    def traverse_downstream(self, coords: tuple, visited: set) -> Optional['StormPoint']:
        '''Utilize depth-first search to find an outfall/outlet point, '''
        x, y = coords
        visited.add((x, y))

        for n in self.G.neighbors((x, y)):
            n_pt = self.pts.cx[n[0], n[1]]
            if not n_pt.empty:
                n_pt = self.to_StormPoint(n_pt)
                if n_pt.IS_SOURCE:
                    # search complete
                    return n_pt
            if n not in visited:
                downstream_pt = self.traverse_downstream(n, visited)
                if downstream_pt is not None:
                    return downstream_pt


    def resolve_upstream(self, source_pt) -> None:
        source_pt = self.to_StormPoint(source_pt)
        if not source_pt.IS_SOURCE:
            raise ValueError(
                f'Cannot resolve direction from point with Index {source_pt.Index} as '
                f'it is not marked as a flow source, see "IS_SOURCE": {source_pt}'
            )
        v_x = source_pt.geometry.x
        v_y = source_pt.geometry.y

        visited = set()
        self.traverse_upstream((v_x, v_y), visited)


    def traverse_upstream(self, coords: tuple, visited: set) -> None:
        '''
        Revise direction of edges via depth-first search, starting from an outlet
        '''
        v = coords
        visited.add(v)
        for u in self.G.predecessors(v):
            if u not in visited:
                # Only retain edge from u -> v
                if self.G.has_edge(v, u):
                    assert self.G.has_edge(u, v)
                    self.G.remove_edge(v, u)
                self.traverse_upstream(u, visited)


    def resolve_from_sources(self) -> None:
        '''
        Resolve directions of all edges within the graph by traversing subgraphs
        upstream from each flow source
        '''
        source_pts = self.pts[self.pts['IS_SOURCE']]
        missing_pts = []

        for pt in source_pts.itertuples(name='StormPoint'):
            if not self.has_StormPoint(pt):
                missing_pts.append(pt.Index)
                continue

            self.resolve_upstream(pt)

        self.directions_resolved = True


    def resolve_by_vertex_order(self, reverse=False) -> None:
        '''
        Resolve directions of all edges within the graph by using the order of verticies
        within each StormLine

        Parameters
        ----------
        reverse: bool (default False)
            Set to True to set edge directions in the opposite direction of their vertex
            order
        '''
        pass


    def resolve_directions(self, method: str='from_sources') -> None:
        '''
        Attempt to resolve directions for all edges within the graph
        '''
        if method == 'from_sources':
            self.resolve_from_sources()
        elif method == 'vertex_order':
            self.resolve_by_vertex_order()
        elif method == 'vertex_order_r':
            self.resolve_by_vertex_order(reverse=True)
        else:
            raise ValueError(
                f'Method "{method}" is not a valid edge resolution method, must be '
                '"from_sources", "vertex_order", or "vertex_order_r".'
            )


    def get_outlet(self, pt_idx: int) -> Optional[int]:
        '''
        Get Index of the outlet for a given storm_pt whose coordinates exist in the
        graph

        Parameters
        ----------
        pt_idx: int
            Index of point, note that OBJECTID is the default index column
        '''
        if not self.directions_resolved:
            raise ValueError(
                f'Cannot get outlet as the graph directions are not resolved'
            )

        pt_x, pt_y = get_point_coords(self.pts.loc[pt_idx].geometry)
        if (pt_x, pt_y) not in self.G:
            print(
                f'The point with index {pt_idx} does not have its coordinates as a '
                'node in the graph'
            )
            return None

        subG = nx.dfs_tree(self.G, (pt_x, pt_y))
        outlet_coords = [coords for coords, deg in subG.out_degree() if deg == 0]
        if len(outlet_coords) == 0:
            raise ValueError(f'Subgraph of point with index {pt_idx} has no outlet')
        elif len(outlet_coords) > 1:
            warnings.warn(
                f'Multiple outlet coordinates found for point with index {pt_idx}, '
                'only returning the first'
            )

        outlet_x, outlet_y = outlet_coords[0]
        outlet_pts = self.pts.cx[outlet_x, outlet_y] # gpd.GeoDataFrame
        if len(outlet_pts) == 0:
            raise ValueError(
                'No point present at the outlet coordinate for point with index '
                '{pt_idx}'
            )
        elif len(outlet_pts) > 1:
            warnings.warn(
                f'Multiple outlet coordinates found for point with index {pt_idx}, '
                'only returning the first'
            )

        return outlet_pts.iloc[0].name


    def get_outlet_points(self, catchment: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        '''
        Get GeoDataFrame of all the infrastructure points within the catchment that
        bring flow out of the current catchment. The catchments for these points will
        need to be removed from current catchment.

        Parameters
        ----------
        catchment: gpd.GeoDataFrame
            GeoDataFrame containing the current catchment polygon

        Returns
        -------
        outlet_pts: gpd.GeoDataFrame
            GeoDataFrame containing all the points that bring flow out of the current
            catchment
        '''
        if catchment.crs != self.pts.crs:
            catchment = catchment.to_crs(crs=self.pts.crs)

        catchment_pts = gpd.clip(self.pts, catchment)
        sink_pts = catchment_pts[catchment_pts['IS_SINK']==True]

        indicies_to_remove = []
        sink_pt_inidicies = sink_pts.index.to_list()
        for idx in sink_pt_inidicies:
            outlet_idx = self.get_outlet(idx)
            if outlet_idx is not None and outlet_idx not in catchment_pts.index:
                indicies_to_remove.append(outlet_idx)
        
        return self.pts.loc[indicies_to_remove]


    def get_inlet_points(self, catchment: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        '''
        Get GeoDataFrame of all the infrastructure points outside the catchment that
        bring flow into the catchment.

        Parameters
        ----------
        catchment: gpd.GeoDataFrame
            GeoDataFrame containing the current catchment polygon

        Returns
        -------
        inlet_pts: gpd.GeoDataFrame
            GeoDataFrame containing all the points outside the catchment that bring flow
            into the catchment
        '''
        if not self.directions_resolved:
            raise ValueError(
                f'Cannot get inlet points as the graph directions are not resolved'
            )

        if catchment.crs != self.pts.crs:
            catchment = catchment.to_crs(crs=self.pts.crs)

        catchment_pts = gpd.clip(self.pts, catchment)
        source_pts = catchment_pts[catchment_pts['IS_SOURCE']==True]
        source_pt_geoms = source_pts.geometry.tolist()
        source_pt_coords = [get_point_coords(geom) for geom in source_pt_geoms]

        contrib_sink_inidices = set()
        for coords in source_pt_coords:
            tree = nx.bfs_tree(self.G, coords, reverse=True)

            for node in tree.nodes():
                if catchment.contains(Point(node)).any():
                    continue
                
                # Look for StormPoints at these coordinates
                pt = self.pts.cx[node[0], node[1]]
                if not pt.empty:
                    pt = self.to_StormPoint(pt)
                    contrib_sink_inidices.add(pt.Index)
        
        return self.pts.loc[contrib_sink_inidices]


    def draw(self, extent: gpd.GeoDataFrame=None, ax=None, add_basemap: bool=True) -> 'plt.axes':
        '''
        Draw the Graph using the geographic coordinates of each node

        Parameters
        ----------
        extent: gpd.GeoDataFrame (default None)
            GeoDataFrame whose extent will be used to trim the infrastructure data
        
        ax: plt.axes | None (default None)
        
        add_basemap: bool (deafult True)
            Option to add a contextily basemap to the plot
        '''
        import matplotlib.pyplot as plt
        from matplotlib.collections import LineCollection
        import numpy as np
        if add_basemap:
            import contextily as cx

        if ax is None:
            ax = plt.gca()
            ax.axis('equal')

        # Extent geometry
        if extent is not None:
            if extent.crs != self.crs:
                extent = extent.to_crs(self.crs)
            envelope = extent['geometry'].envelope.iloc[0]

        # bidirectional_edges = [edge for edge in self.G.edges() if ]

        bidirectional_edges = []
        directional_edges = []
        for edge in self.G.edges():
            if extent is not None:
                # Exclude edges with no verticies within extent
                if not envelope.contains(Point(edge[0][0], edge[0][1])) and \
                    not envelope.contains(Point(edge[1][0], edge[1][1])):
                    continue
            if self.G.has_edge(edge[1], edge[0]):
                bidirectional_edges.append(edge)
            else:
                directional_edges.append(edge)

        # Plot directional edges as arrows
        for edge in directional_edges:
            u_x, u_y = edge[0]
            v_x, v_y = edge[1]
            ax.arrow(
                u_x,
                u_y,
                v_x - u_x,
                v_y - u_y,
                shape='left',
                width=0.1,
                head_width=2,
                length_includes_head=True,
                ec='darkblue',
                fc='cyan',
                zorder=1
            )

        # Plot bidirectional edges as segments
        lc = LineCollection([edge for edge in bidirectional_edges], color='darkblue')
        ax.add_collection(lc)

        if extent is not None:
            pts = gpd.clip(self.pts, extent['geometry'].envelope)
        else:
            pts = self.pts
        
        # Plot points
        sink_pts = pts[pts['IS_SINK']==True]
        source_pts = pts[pts['IS_SOURCE']==True]
        other_pts = pts[
            (pts['IS_SINK']==False) & (pts['IS_SOURCE']==False)
        ]
        sink_pts.plot(
            ax=ax, color='white', marker='s', edgecolor='black', markersize=10, zorder=2
        )
        source_pts.plot(
            ax=ax, color='white', marker='o', edgecolor='black', markersize=10, zorder=2
        )
        other_pts.plot(
            ax=ax, color='gray', marker='o', edgecolor='black', markersize=10, zorder=2
        )

        if add_basemap:
            try:
                cx.add_basemap(
                    ax, source=cx.providers.Esri.WorldImagery, crs=self.crs.to_string()
                )
            except Exception as e:
                warnings.warn(
                    'The following exception was raised while trying to add the'
                    'contextily basemap:', e
                )

        return ax
