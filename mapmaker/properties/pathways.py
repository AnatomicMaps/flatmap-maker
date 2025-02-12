#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2020  David Brooks
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#
#===============================================================================

from collections import defaultdict
from typing import Any, Iterable, Optional, TYPE_CHECKING

#===============================================================================

import networkx as nx
from pyparsing import delimitedList, Group, ParseException, ParseResults, Suppress
import shapely.geometry

#===============================================================================

from mapmaker.flatmap.feature import Feature
from mapmaker.flatmap.layers import PATHWAYS_TILE_LAYER, FeatureLayer
from mapmaker.knowledgebase import get_knowledge
from mapmaker.knowledgebase.sckan import connectivity_graph_from_knowledge
from mapmaker.knowledgebase.sckan import PATH_TYPE
from mapmaker.routing import Network
from mapmaker.settings import settings
from mapmaker.utils import log

from .markup import ID_TEXT

if TYPE_CHECKING:
    from mapmaker.flatmap import FlatMap

#===============================================================================

NERVES = delimitedList(ID_TEXT)

LINE_ID = ID_TEXT
PATH_LINES = delimitedList(LINE_ID)

NODE_ID = ID_TEXT
ROUTE_NODE_GROUP = NODE_ID  | Group(Suppress('(') +  delimitedList(NODE_ID) + Suppress(')'))
ROUTE_NODES = delimitedList(ROUTE_NODE_GROUP)

#===============================================================================

DEFAULT_PATH_PROPERTIES = {
    'layout': 'auto',
    'sckan': True,          #   Auto layout connectivity originates in SCKAN
    'tile-layer': PATHWAYS_TILE_LAYER,
    'completeness': True,   #   Auto layout path completeness
}

#===============================================================================

def parse_path_lines(line_ids):
#==============================
    try:
        if isinstance(line_ids, str):
            path_lines = PATH_LINES.parseString(line_ids, parseAll=True)
        else:
            path_lines = [LINE_ID.parseString(line_id)[0] for line_id in line_ids]
    except ParseException:
        raise ValueError('Syntax error in path lines list: {}'.format(line_ids)) from None
    return path_lines

def parse_route_nodes(node_ids):
#===============================
    try:
        if isinstance(node_ids, str):
            route_nodes = ROUTE_NODES.parseString(node_ids, parseAll=True)
        else:
            route_nodes = []
            if isinstance(node_ids[0], str):
                route_nodes.append(NODE_ID.parseString(node_ids[0]))
            else:
                route_nodes.append([NODE_ID.parseString(id)[0] for id in node_ids[0]])
            for id in node_ids[1:-1]:
                route_nodes.append(NODE_ID.parseString(id)[0])
            if isinstance(node_ids[-1], str):
                route_nodes.append(NODE_ID.parseString(node_ids[-1]))
            else:
                route_nodes.append([NODE_ID.parseString(id)[0] for id in node_ids[-1]])
    except ParseException:
        raise ValueError('Syntax error in route node list: {}'.format(node_ids)) from None
    return list(route_nodes)

def parse_nerves(node_id_string):
#================================
    if node_id_string is None:
        return []
    try:
        nerves = NERVES.parseString(node_id_string, parseAll=True)
    except ParseException:
        raise ValueError('Syntax error in nerve list: {}'.format(node_id_string)) from None
    return nerves

#===============================================================================

class ResolvedPath:
    """
    A path described in terms of numeric feature ids.
    """
    def __init__(self):
        self.__lines = set()
        self.__nerves = set()
        self.__nodes = set()
        self.__models = None
        self.__centrelines = set()

    @property
    def as_dict(self) -> dict[str, Any] :
        """
        The numeric feature ids that make up a path.
        """
        result = {
            'lines': list(self.__lines),
            'nerves': list(self.__nerves),
            'nodes': list(self.__nodes),
            'models': self.__models
        }
        if len(self.__centrelines):
            result['centrelines'] = list(self.__centrelines)
        return result

    def add_centrelines(self, centrelines: list[str]):
        self.__centrelines.update(centrelines)

    def extend_lines(self, geojson_ids: list[int]):
        """
        Associate line segments with the path.

        Arguments:
        ----------
        geojson_ids
            Line segment numeric GeoJSON ids
        """
        self.__lines.update(geojson_ids)

    def extend_nerves(self, geojson_ids: list[int]):
        """
        Associate nerve cuffs with the path.

        Arguments:
        ----------
        geojson_ids
            Nerve cuff numeric GeoJSON ids
        """
        self.__nerves.update(geojson_ids)

    def extend_nodes(self, geojson_ids: list[int]):
        """
        Associate nodes with the path.

        Arguments:
        ----------
        geojson_ids
            Node numeric GeoJSON ids
        """
        self.__nodes.update(geojson_ids)

    def set_model_id(self, model_id: str):
        """
        Set an external indentifier for the path.

        Arguments:
        ----------
        model_id
            The path's external identifier (what it models)
        """
        self.__models = model_id

#===============================================================================

class Route:
    def __init__(self, path_id, route):
        self.__path_id = path_id
        routing = parse_route_nodes(route)
        if len(routing) < 2:
            raise ValueError('Route definition is too short for path {}'.format(path_id))
        self.__start_nodes = Pathways.make_list(routing[0])
        self.__through_nodes = []
        for node in routing[1:-1]:
            self.__through_nodes += Pathways.make_list(node)
        self.__end_nodes = Pathways.make_list(routing[-1])

    @property
    def end_nodes(self):
        return self.__end_nodes

    @property
    def nodes(self):
        return set(self.__start_nodes + self.__through_nodes + self.__end_nodes)

    @property
    def path_id(self):
        return self.__path_id

    @property
    def start_nodes(self):
        return self.__start_nodes

    @property
    def through_nodes(self):
        return self.__through_nodes

#===============================================================================

class ResolvedPathways:
    def __init__(self, flatmap: 'FlatMap'):
        self.__flatmap = flatmap
        self.__paths: dict[str, ResolvedPath] = defaultdict(ResolvedPath)   #! Paths by :class:`ResolvedPath`\ s
        self.__node_paths: dict[int, set[str]] = defaultdict(set)           #! Paths by node geojson_id
        self.__type_paths: dict[PATH_TYPE, set[str]] = defaultdict(set)     #! Paths by path type

    @property
    def node_paths(self) -> dict[int, list[str]]:
        return { node: list(paths) for node, paths in self.__node_paths.items() }

    @property
    def paths_dict(self) -> dict[str, dict]:
        return { path_id: resolved_path.as_dict
                    for path_id, resolved_path in self.__paths.items()
               }

    @property
    def type_paths(self) -> dict[str, list[str]]:
        result: dict[str, list[str]] = defaultdict(list)
        for typ, paths in self.__type_paths.items():
            result[typ.viewer_kind].extend(paths)
        return result

    def __resolve_nodes_for_path(self, path_id, node_feature_ids):
        node_geojson_ids = []
        for feature_id in node_feature_ids:
            if (feature := self.__flatmap.get_feature(feature_id)) is not None:
                if not feature.get_property('exclude'):
                    geojson_id = feature.geojson_id
                    feature.set_property('nodeId', geojson_id)
                    self.__node_paths[geojson_id].add(path_id)
                    node_geojson_ids.append(geojson_id)
            else:
                log.warning(f'Cannot find feature for node: {id}')
        return node_geojson_ids

    def add_connectivity(self, path_id: str, line_geojson_ids: list[int],
                         model: str, path_type: PATH_TYPE,
                         node_feature_ids: set[str], nerve_features: list[Feature],
                         centrelines: Optional[list[str]]=None):
        resolved_path = self.__paths[path_id]
        if model is not None:
            resolved_path.set_model_id(model)
        self.__type_paths[path_type].add(path_id)
        resolved_path.extend_nodes(self.__resolve_nodes_for_path(path_id, node_feature_ids))
        resolved_path.extend_lines(line_geojson_ids)
        resolved_path.extend_nerves([f.geojson_id for f in nerve_features])
        if centrelines is not None:
            resolved_path.add_centrelines(centrelines)

    def add_pathway(self, path_id: str, model: Optional[str], path_type: PATH_TYPE,
                    route: Route, lines: list[str], nerves: list[str]):
        resolved_path = self.__paths[path_id]
        if model is not None:
            resolved_path.set_model_id(model)
        self.__type_paths[path_type].add(path_id)
        resolved_path.extend_nodes(
            self.__resolve_nodes_for_path(path_id, route.start_nodes)
          + self.__resolve_nodes_for_path(path_id, route.through_nodes)
          + self.__resolve_nodes_for_path(path_id, route.end_nodes))
        resolved_path.extend_lines(self.__flatmap.feature_ids_to_geojson_ids(lines))
        resolved_path.extend_nerves(self.__flatmap.feature_ids_to_geojson_ids(nerves))

#===============================================================================

'''
##  WIP...
class NodeTypeFinder:
    def __init__(self, axon_nodes, dendrite_nodes, path_id):
        self.__axon_nodes = axon_nodes
        self.__dendrite_nodes = dendrite_nodes
        self.__path_id = path_id

    def node_type(self, node):
        node_type = None
        if node in self.__axon_nodes:
            node_type = 'axon'
        if node in self.__dendrite_nodes:
            if node_type is None:
                node_type = 'dendrite'
            else:
                log.warning(f'SCKAN knowledge error: node {node} in {self.__path_id} is both axon and dendrite')
        return node_type

    ## Keeping this for reference until can clarify meaning of axon/dendrite
    ## lists with TG.
    @staticmethod
    def matched_term(node, region_layer_terms):
        i = 0
        n = len(node[1])
        layer_or_region, regions = node
        if (layer_or_region, None) in region_layer_terms:
            # sometimes it is region, regions when you
            # have internalIn nesting
            return True
        if regions:  # this is regions and parents so have to start with None
            region = regions[i]
            layer = layer_or_region
        else:
            region = layer_or_region
            layer = None
        while True:
            if (region, layer) in region_layer_terms:
                return True
            #elif (region, None) in region_layer_terms:
                # on the very off chance
                #return True
            elif i >= n:
                return False
            else:
                region = regions[i]
                i += 1
# End WIP...
'''

#===============================================================================

class Path:
    def __init__(self, source, path, trace=False):
        self.__source = source
        self.__id = path['id']
        self.__connectivity = None
        self.__path_type = PATH_TYPE.UNKNOWN
        self.__lines = []
        self.__label = None
        self.__models = path.get('models')
        self.__nerves = list(parse_nerves(path.get('nerves')))
        self.__route = None
        self.__trace = trace

        if self.__models is not None:
            knowledge = get_knowledge(self.__models)
            self.__label = knowledge.get('label')
            self.__connectivity = connectivity_graph_from_knowledge(knowledge)

        if self.__connectivity is not None:
            self.__path_type = self.__connectivity.graph['path-type']
        else:
            log.error(f'Path {self.__id} has no known connectivity...')

    @property
    def connectivity(self) -> nx.Graph:
        return nx.Graph(self.__connectivity)

    @property
    def id(self):
        return self.__id

    @property
    def label(self):
        return self.__label

    @property
    def lines(self):
        return self.__lines

    @property
    def models(self):
        return self.__models

    @property
    def nerves(self):
        return self.__nerves

    @property
    def path_type(self):
        return self.__path_type

    @property
    def route(self):
        return self.__route

    @property
    def source(self):
        return self.__source

    @property
    def trace(self):
        return self.__trace

#===============================================================================

class ConnectivityModel:
    def __init__(self, description):
        self.__id = description.get('id')
        self.__network = description.get('network')
        self.__publications = description.get('publications', [])
        self.__source = description.get('source')
        traced_paths = description.get('traced-paths', [])
        self.__paths = { path['id']: Path(self.__source, path, path['id'] in traced_paths)
                            for path in description.get('paths', []) }

    @property
    def id(self):
        return self.__id

    @property
    def network(self):
        return self.__network

    @property
    def path_ids(self):
        return list(self.__paths.keys())

    @property
    def paths(self):
        return self.__paths

    @property
    def publications(self):
        return self.__publications

    @property
    def source(self):
        return self.__source

#===============================================================================

class ConnectionSet:
    def __init__(self, model_id):
        self.__id = model_id
        self.__connections: dict[str, int] = {}
        self.__connections_by_kind: dict[str, list[str]] = defaultdict(list)
        self.__connectors_by_connection: dict[str, list[int]] = defaultdict(list)
        self.__connections_by_connector: dict[int, set[str]] = defaultdict(set)

    def __len__(self):
        return len(self.__connections)

    def add(self, path_id: str, viewer_kind: str, geojson_id: int, connector_ids: list[int]):
    #========================================================================================
        # Need geojson id of shape's feature
        self.__connections[path_id] = geojson_id
        self.__connections_by_kind[viewer_kind].append(path_id)
        self.__connectors_by_connection[path_id] = connector_ids
        for connector_id in connector_ids:
            self.__connections_by_connector[connector_id].add(path_id)

    def as_dict(self):
    #=================
        return {
            'models': [{
                'id': self.__id,
                'paths': list(self.__connections.keys())
            }],
            'paths': {
                path_id: {
                    'lines': [geojson_id],
                    'nodes': self.__connectors_by_connection[path_id],
                    'nerves': []
                } for path_id, geojson_id in self.__connections.items()
            },
            'node-paths': { node: list(path_ids)
                for node, path_ids in self.__connections_by_connector.items()},
            'type-paths': {
                viewer_kind: path_ids for viewer_kind, path_ids in self.__connections_by_kind.items()
            }
        }

#===============================================================================

class Pathways:
    def __init__(self, flatmap, paths_list):
        self.__flatmap = flatmap
        self.__layer_paths = set()
        self.__lines_by_path_id = defaultdict(list)
        self.__nerves_by_path_id = {}
        self.__paths_by_line_id = defaultdict(list)
        self.__paths_by_nerve_id = defaultdict(list)
        self.__resolved_pathways = None
        self.__routes_by_path_id = {}
        self.__type_by_path_id: dict[str, PATH_TYPE] = {}
        self.__path_models_by_id: dict[str, str] = {}
        self.__connectivity_by_path_id = {}
        self.__connectivity_models = []
        self.__active_nerve_ids: set[str] = set()   ### Manual layout only???
        self.__connection_sets: list[ConnectionSet] = []
        if len(paths_list):
            self.add_connectivity({'paths': paths_list})

    @staticmethod
    def make_list(lst):
        return (lst if isinstance(lst, list)
           else list(lst) if isinstance(lst, ParseResults)
           else [ lst ])

    @property
    def connectivity(self):
        connectivity: dict[str, Any] = {
            'models': [],
            'paths': {},
            'node-paths': defaultdict(list),
            'type-paths': defaultdict(list)
        }
        for model in self.__connectivity_models:
            if model.source is not None:
                connectivity['models'].append({
                    'id': model.source,
                    'paths': model.path_ids
                })
        if self.__resolved_pathways is not None:
            connectivity['paths'] = self.__resolved_pathways.paths_dict
            connectivity['node-paths'] = defaultdict(list, self.__resolved_pathways.node_paths)
            connectivity['type-paths'] = defaultdict(list, self.__resolved_pathways.type_paths)
        for connection_set in self.__connection_sets:
            connection_set_dict = connection_set.as_dict()
            connectivity['models'].extend(connection_set_dict['models'])
            connectivity['paths'].update(connection_set_dict['paths'])
            for node, paths in connection_set_dict['node-paths'].items():
                connectivity['node-paths'][node].extend(paths)
            for path_type, paths in connection_set_dict['type-paths'].items():
                connectivity['type-paths'][path_type].extend(paths)
        return connectivity

    def add_connection_set(self, connection_set):
    #============================================
        if len(connection_set):
            self.__connection_sets.append(connection_set)

    def __line_properties(self, path_id):
    #====================================
        properties = {}
        if path_id in self.__type_by_path_id:
            kind = self.__type_by_path_id[path_id].viewer_kind
            properties.update({
                'kind': kind,
                 ## Can we just put this into `kind` and have viewer work out if dashed??
                'type': 'line-dash' if kind.endswith('-post') else 'line'
                # this is were we could set flags to specify the line-end style.
                # --->   <---    |---   ---|    o---   ---o    etc...
                # See https://github.com/alantgeo/dataset-to-tileset/blob/master/index.js
                # and https://github.com/mapbox/mapbox-gl-js/issues/4096#issuecomment-303367657
            })
        else:
            properties['type'] = 'line'
        if path_id in self.__path_models_by_id:
            properties['models'] = self.__path_models_by_id[path_id]
        if path_id in self.__connectivity_by_path_id:
            source = self.__connectivity_by_path_id[path_id].source
            if source is not None:
                properties['source'] = source
        return properties

    def update_line_or_nerve_properties(self, properties):
    #=====================================================
        for id_or_class in [properties.get('class'), properties.get('id')]:
            path_id = None
            # Is the id_or_class that of a line?
            if id_or_class in self.__paths_by_line_id:
                path_id = self.__paths_by_line_id[id_or_class][0]
                properties.update(self.__line_properties(path_id))
            # Is the id_or_class that of a nerve cuff?
            elif id_or_class in self.__paths_by_nerve_id:
                path_id = self.__paths_by_nerve_id[id_or_class][0]
                properties['type'] = 'nerve'
            # Have we found a path?
            if path_id is not None:
                properties['tile-layer'] = PATHWAYS_TILE_LAYER
                self.__layer_paths.add(path_id)

    def add_connectivity_model(self, model_uri, properties_data, path_filter=None, traced_paths=None):
    #=================================================================================================
        connectivity = {
            'id': model_uri.rsplit('/', 1)[-1],
            'source': model_uri,
            'network': 'neural',
            'paths': []
        }
        connectivity.update(get_knowledge(model_uri))
        self.__add_connectivity_paths(connectivity, properties_data, path_filter, traced_paths)

    def add_connectivity_path(self, path_uri, properties_data, path_filter=None, traced_paths=None):
    #===============================================================================================
        connectivity = {
            'id': path_uri,
            'source': path_uri,
            'network': 'neural',
            'paths': [{
                'id': path_uri,
                'models': path_uri
            }]
        }
        self.__add_connectivity_paths(connectivity, properties_data, path_filter, traced_paths)

    def __add_connectivity_paths(self, connectivity, properties_data, path_filter, traced_paths):
    #============================================================================================
        if path_filter is not None:
            connectivity['paths'] = list(filter(lambda path: path_filter(path['id']), connectivity['paths']))
        if traced_paths is not None:
            connectivity['traced-paths'] = traced_paths
        # External properties overrides knowledge base
        for path in connectivity['paths']:
            path.update(properties_data.properties(path.get('models')))
        self.add_connectivity(connectivity)

    def add_connectivity(self, connectivity):
    #========================================
        connectivity_model = ConnectivityModel(connectivity)
        self.__connectivity_models.append(connectivity_model)

        lines_by_path_id = {}
        nerves_by_path_id = {}
        for path in connectivity_model.paths.values():
            self.__connectivity_by_path_id[path.id] = connectivity_model
            lines_by_path_id[path.id] = path.lines
            nerves_by_path_id[path.id] = path.nerves
            if path.models is not None:
                self.__path_models_by_id[path.id] = path.models
            self.__type_by_path_id[path.id] = path.path_type
            if path.route is not None:
                self.__routes_by_path_id[path.id] = path.route

        # Update reverse maps
        self.__lines_by_path_id.update(lines_by_path_id)
        for path_id, lines in lines_by_path_id.items():
            for line_id in lines:
                self.__paths_by_line_id[line_id].append(path_id)
        # Following is for manual layout... ????
        self.__nerves_by_path_id.update(nerves_by_path_id)
        for path_id, nerves in nerves_by_path_id.items():
            self.__active_nerve_ids.update(nerves)
            for nerve_id in nerves:
                self.__paths_by_nerve_id[nerve_id].append(path_id)

    def __route_network_connectivity(self, network: Network):
    #========================================================
        if self.__resolved_pathways is None:
            log.error('Cannot route network when no pathways')
            return
        log.info(f'Routing {network.id} paths...')

        active_nerve_features: set[Feature] = set()
        paths_by_id = {}
        route_graphs: dict[str, nx.Graph] = {}
        network.create_geometry()

        # Find route graphs for each path in each connectivity model
        for connectivity_model in self.__connectivity_models:
            if connectivity_model.network == network.id:
                for path in connectivity_model.paths.values():
                    paths_by_id[path.id] = path
                    route_graphs[path.id] = network.route_graph_from_path(path)

        # Now order them across shared centrelines
        routed_paths = network.layout(route_graphs)

        # Add features to the map for the geometric objects that make up each path
        layer = FeatureLayer(f'{network.id}-routes', self.__flatmap, exported=True)
        self.__flatmap.add_layer(layer)
        for route_number, routed_path in routed_paths.items():
            for path_id, geometric_shapes in routed_path.path_geometry().items():
                path = paths_by_id[path_id]
                path_geojson_ids = []
                path_taxons = None
                added_properties = {
                    key: value for key, value in [
                        ('missing-nodes', path.connectivity.graph.get('missing_nodes')),
                        ('alert', path.connectivity.graph.get('alert')),
                        ('biological-sex', path.connectivity.graph.get('biological-sex')),
                        ('completeness', path.connectivity.graph.get('completeness')),
                    ] if value is not None
                }
                
                for geometric_shape in geometric_shapes:
                    if geometric_shape.properties.get('type') not in ['arrow', 'junction']:
                        properties = DEFAULT_PATH_PROPERTIES.copy() | added_properties
                        if routed_path.centrelines is not None:
                            # The list of nerve models that the path is associated with
                            properties['nerves'] = routed_path.centrelines_model

                        properties.update(self.__line_properties(path_id))
                        path_model = path.models
                        if settings.get('authoring', False):
                            labels = []
                            if path_model is not None:
                                labels.append(f'Models: {path_model}')
                                labels.append(f'Label: {path.label}')
                            labels.append(f'Number: {route_number}')
                            properties['label'] = '\n'.join(labels)
                        elif path_model is not None:
                            properties['label'] = path.label
                        if 'id' not in properties and path_model is not None:
                            properties['id'] = path_model.replace(':', '_').replace('/', '_')
                        feature = self.__flatmap.new_feature('pathways', geometric_shape.geometry, properties)
                        path_geojson_ids.append(feature.geojson_id)
                        layer.add_feature(feature)
                        if path_taxons is None:
                            path_taxons = feature.get_property('taxons')

                for geometric_shape in geometric_shapes:
                    properties = DEFAULT_PATH_PROPERTIES.copy() | added_properties
                    properties.update(geometric_shape.properties)
                    if properties.get('type') in ['arrow', 'junction']:
                        properties['kind'] = path.path_type.viewer_kind
                        if routed_path.centrelines is not None:
                            # The list of nerve models that the path is associated with
                            properties['nerves'] = routed_path.centrelines_model
                        if path_taxons is not None:
                            properties['taxons'] = path_taxons
                        feature = self.__flatmap.new_feature('pathways', geometric_shape.geometry, properties)
                        path_geojson_ids.append(feature.geojson_id)
                        layer.add_feature(feature)

                nerve_feature_ids = routed_path.nerve_feature_ids
                nerve_features = [self.__flatmap.get_feature(nerve_id) for nerve_id in nerve_feature_ids]
                active_nerve_features.update(nerve_features)
                self.__resolved_pathways.add_connectivity(path_id,
                                                          path_geojson_ids,
                                                          path.models,
                                                          path.path_type,
                                                          routed_path.node_feature_ids,
                                                          nerve_features,
                                                          centrelines=routed_path.centrelines)
        for feature in active_nerve_features:
            if feature.get_property('type') == 'nerve' and feature.geom_type == 'LineString':
                feature.pop_property('exclude')
                feature.set_property('nerveId', feature.geojson_id)  # Used in map viewer
                feature.set_property('tile-layer', PATHWAYS_TILE_LAYER)
                # Add a polygon feature for a nerve cuff
                properties = feature.properties.copy()
                feature.properties.pop('models', None)  # Otherwise we can two markers on the feature
                properties.pop('id', None)   # Otherwise we will have a duplicate id...
                nerve_polygon_feature = self.__flatmap.new_feature(
                    'pathways',
                    shapely.geometry.Polygon(feature.geometry.coords).buffer(0), properties)
                layer.features.append(nerve_polygon_feature)

    def generate_connectivity(self, networks: Iterable[Network]):
    #============================================================
        if self.__resolved_pathways is not None:
            return
        self.__resolved_pathways = ResolvedPathways(self.__flatmap)
        errors = False
        for path_id in self.__layer_paths:
            try:
                if path_id in self.__routes_by_path_id:
                    self.__resolved_pathways.add_pathway(path_id,
                                                         self.__path_models_by_id.get(path_id),
                                                         self.__type_by_path_id.get(path_id, PATH_TYPE.UNKNOWN),
                                                         self.__routes_by_path_id[path_id],
                                                         self.__lines_by_path_id.get(path_id, []),
                                                         self.__nerves_by_path_id.get(path_id, []))
            except ValueError as err:
                log.error('Path {}: {}'.format(path_id, str(err)))
                errors = True
        for network in networks:
            if network.id is not None:
                self.__route_network_connectivity(network)
        if errors:
            raise ValueError('Errors in mapping paths and routes')

    def knowledge(self):
    #===================
        knowledge = defaultdict(list)
        for model in self.__connectivity_models:
            if model.source is not None:
                knowledge['publications'].append((model.source, model.publications))
        return knowledge

#===============================================================================
