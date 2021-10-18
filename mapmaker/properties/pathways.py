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
from typing import Dict, List

#===============================================================================

from pyparsing import delimitedList, Group, ParseException, ParseResults, Suppress

#===============================================================================

from mapmaker.flatmap.feature import Feature, FeatureMap
from mapmaker.flatmap.layers import FeatureLayer
from mapmaker.sources.markup import ID_TEXT
from mapmaker.utils import log, FilePath

#===============================================================================

NERVES = delimitedList(ID_TEXT)

LINE_ID = ID_TEXT
PATH_LINES = delimitedList(LINE_ID)

NODE_ID = ID_TEXT
ROUTE_NODE_GROUP = NODE_ID  | Group(Suppress('(') +  delimitedList(NODE_ID) + Suppress(')'))
ROUTE_NODES = delimitedList(ROUTE_NODE_GROUP)

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

def parse_nerves(node_ids):
#==========================
    try:
        nerves = NERVES.parseString(node_ids, parseAll=True)
    except ParseException:
        raise ValueError('Syntax error in nerve list: {}'.format(node_ids)) from None
    return nerves

#===============================================================================

class ResolvedPath(object):
    """
    A path described in terms of numeric feature ids.
    """
    def __init__(self):
        self.__lines = set()
        self.__nerves = set()
        self.__nodes = set()
        self.__models = None

    @property
    def as_dict(self) -> Dict[str, List[int]] :
        """
        The numeric feature ids that make up a path.
        """
        path_dict = {
            'lines': list(self.__lines),
            'nerves': list(self.__nerves),
            'nodes': list(self.__nodes)
        }
        if self.__models is not None:
            path_dict['models'] = self.__models
        return path_dict

    def extend_lines(self, feature_ids: List[int]):
        """
        Associate line segments with the path.

        Arguments:
        ----------
        feature_ids
            Line segment numeric feature ids
        """
        self.__lines.update(feature_ids)

    def extend_nerves(self, feature_ids: List[int]):
        """
        Associate nerve cuffs with the path.

        Arguments:
        ----------
        feature_ids
            Nerve cuff numeric feature ids
        """
        self.__nerves.update(feature_ids)

    def extend_nodes(self, feature_ids: List[int]):
        """
        Associate nodes with the path.

        Arguments:
        ----------
        feature_ids
            Node numeric feature ids
        """
        self.__nodes.update(feature_ids)

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

class ResolvedPathways(object):
    """
    A set of :class:`ResolvedPath`\ s.

        Arguments:
        ----------
        feature_map
            A mapping from a feature's id and class attributes to its numeric identifier.
    """
    def __init__(self, feature_map: mapmaker.flatmap.FeatureMap):
        self.__feature_map = feature_map
        self.__paths = defaultdict(ResolvedPath)  #! Paths by :class:`ResolvedPath`\ s
        self.__node_paths = defaultdict(list)     #! Paths by node
        self.__type_paths = defaultdict(list)     #! Paths by path type

    @property
    def node_paths(self):
        return self.__node_paths

    @property
    def paths_dict(self):
        return { path_id: resolved_path.as_dict
                    for path_id, resolved_path in self.__paths.items()
               }

    @property
    def type_paths(self):
        return self.__type_paths

    def add_line_feature(self, path_id, feature):
        resolved_path = self.__paths[path_id]
        resolved_path.extend_lines([feature.feature_id])

    def add_nerves(self, path_id, nerves):
        resolved_path = self.__paths[path_id]
        resolved_path.extend_nerves(self.__feature_map.feature_ids(nerves))

    def add_nodes(self, path_id, nodes):
        resolved_path = self.__paths[path_id]
        resolved_path.extend_nodes(self.__resolve_nodes_for_path(path_id, nodes))

    def add_path_type(self, path_id, path_type):
        self.__type_paths[path_type].append(path_id)

    def __resolve_nodes_for_path(self, path_id, nodes):
        node_ids = []
        for id in nodes:
            node_count = 0
            for feature in self.__feature_map.features(id):
                if not feature.get_property('exclude'):
                    node_id = feature.feature_id
                    feature.set_property('nodeId', node_id)
                    self.__node_paths[node_id].append(path_id)
                    node_ids.append(node_id)
                    node_count += 1
            if node_count == 0:
                log.warn('Cannot find feature for node: {}'.format(id))
        return node_ids

    def resolve_pathway(self, path_id, lines, nerves, route):
        resolved_path = self.__paths[path_id]
        resolved_path.extend_lines(self.__feature_map.feature_ids(lines))
        resolved_path.extend_nerves(self.__feature_map.feature_ids(nerves))
        resolved_path.extend_nodes(
            self.__resolve_nodes_for_path(path_id, route.start_nodes)
          + self.__resolve_nodes_for_path(path_id, route.through_nodes)
          + self.__resolve_nodes_for_path(path_id, route.end_nodes))

    def set_model_id(self, path_id, model_id):
        self.__paths[path_id].set_model_id(model_id)

#===============================================================================

class Route(object):
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

class ConnectivityModel(object):
    def __init__(self, description):
        if description is None:
            self.__id = None
            self.__network = None
            self.__source = None
            self.__publications = []
        else:
            self.__id = description['id']
            self.__network = description.get('network')
            self.__publications = description.get('publications', [])
            self.__source = description.get('source')
        self.__path_ids = []
        self.__connections = {}

    @property
    def connections(self):
        return self.__connections

    @property
    def id(self):
        return self.__id

    @property
    def network(self):
        return self.__network
    @property
    def publications(self):
        return self.__publications

    @property
    def source(self):
        return self.__source

    @property
    def path_ids(self):
        return self.__path_ids

    def add_connection(self, path_id, connection):
        self.__connections[path_id] = connection

    def add_path_id(self, path_id):
        self.__path_ids.append(path_id)

#===============================================================================

class Pathways(object):
    def __init__(self, flatmap, paths_list):
        self.__flatmap = flatmap
        self.__layer_paths = set()
        self.__lines_by_path_id = defaultdict(list)
        self.__nerves_by_path_id = {}
        self.__paths_by_line_id = defaultdict(list)
        self.__paths_by_nerve_id = defaultdict(list)
        self.__resolved_pathways = None
        self.__routes_by_path_id = {}
        self.__types_by_path_id = {}
        self.__connectivity_by_path = {}
        self.__connectivity_models = [ ConnectivityModel(None) ]
        self.__path_models = {}
        self.__extend_pathways(self.__connectivity_models[0], paths_list)

    @staticmethod
    def make_list(lst):
        return (lst if isinstance(lst, list)
           else list(lst) if isinstance(lst, ParseResults)
           else [ lst ])

    @property
    def connectivity(self):
        return {
            'models': [
                { 'id': model.source,
                  'paths': model.path_ids
                } for model in self.__connectivity_models
                    if model.source is not None
            ],
            'paths': self.__resolved_pathways.paths_dict,
            'node-paths': self.__resolved_pathways.node_paths,
            'type-paths': self.__resolved_pathways.type_paths,
        }

    def __line_properties(self, path_id):
    #====================================
        properties = {}
        if path_id in self.__types_by_path_id:
            kind = self.__types_by_path_id[path_id]
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
        if path_id in self.__path_models:
            properties['models'] = self.__path_models[path_id]
        if path_id in self.__connectivity_by_path:
            source = self.__connectivity_by_path[path_id].source
            if source is not None:
                properties['source'] = source
        return properties

    def add_line_or_nerve(self, id_or_class):
    #========================================
        path_id = None
        properties = {}
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
            properties['tile-layer'] = 'pathways'
            self.__layer_paths.add(path_id)
        return properties

    def add_connectivity(self, connectivity):
    #========================================
        connectivity_model = ConnectivityModel(connectivity)
        self.__connectivity_models.append(connectivity_model)
        self.__extend_pathways(connectivity_model, connectivity.get('paths', []))

    def __extend_pathways(self, connectivity_model, paths_list):
    #===========================================================
        lines_by_path_id = defaultdict(list)
        nerves_by_path_id = {}
        for path in paths_list:
            path_id = path['id']
            connectivity_model.add_path_id(path_id)
            self.__connectivity_by_path[path_id] = connectivity_model
            if 'path' in path:
                for line_group in parse_path_lines(path['path']):
                    lines_by_path_id[path_id] += Pathways.make_list(line_group)
                if 'route' not in path:
                    raise ValueError("Path '{}' doesn't have a route".format(path_id))
                self.__routes_by_path_id[path_id] = Route(path_id, path['route'])
            elif 'connects' in path:
                connectivity_model.add_connection(path_id, path['connects'])
            if 'nerves' in path:
                nerves_by_path_id[path_id] = list(parse_nerves(path['nerves']))
            if 'type' in path:
                self.__types_by_path_id[path_id] = path['type']
            if 'models' in path:
                self.__path_models[path_id] = path['models']
        self.__lines_by_path_id.update(lines_by_path_id)
        for path_id, lines in lines_by_path_id.items():
            for line_id in lines:
                self.__paths_by_line_id[line_id].append(path_id)
        self.__nerves_by_path_id.update(nerves_by_path_id)
        for path_id, nerves in nerves_by_path_id.items():
            for nerve_id in nerves:
                self.__paths_by_nerve_id[nerve_id].append(path_id)

    def __route_paths(self, network, model_to_features):
    #===================================================
        def get_point_for_anatomy(anatomical_id, error_list):
            if anatomical_id in model_to_features:
                features_set = model_to_features[anatomical_id]
                if len(features_set) == 1:
                    return list(features_set)[0].geometry.centroid.coords[0]
                else:
                    error_list.append("Multiple features for {}".format(anatomical_id))
            else:
                error_list.append("Cannot find feature for {}".format(anatomical_id))
            return None

        log('Routing paths...')
        for connectivity_model in self.__connectivity_models:
            if connectivity_model.network == network.id:
                layer = FeatureLayer('{}_routes'.format(connectivity_model.id), self.__flatmap, exported=True)
                self.__flatmap.add_layer(layer)
                for path_id, routed_path in network.layout(connectivity_model.connections).items():
                    properties = { 'tile-layer': 'autopaths' }
                    properties.update(self.__line_properties(path_id))
                    for n, geometric_shape in enumerate(routed_path.geometry()):
                        properties.update(geometric_shape.properties)
                        feature = self.__flatmap.new_feature(geometric_shape.geometry, properties)
                        layer.add_feature(feature)
                        id = f'{path_id}__F_{n}'
                        self.__resolved_pathways.add_line_feature(path_id, feature)
                        self.__resolved_pathways.add_nerves(path_id, self.__nerves_by_path_id.get(path_id, []))
                        self.__resolved_pathways.add_nodes(path_id, routed_path.node_set)
                        self.__resolved_pathways.add_path_type(id, properties.get('type'))
                        self.__resolved_pathways.set_model_id(id, self.__path_models.get(path_id))

    def generate_connectivity(self, network, feature_map, model_to_features):
    #========================================================================
        if self.__resolved_pathways is not None:
            return
        self.__resolved_pathways = ResolvedPathways(feature_map)
        errors = False
        for path_id in self.__layer_paths:
            try:
                if path_id in self.__routes_by_path_id:
                    self.__resolved_pathways.resolve_pathway(path_id,
                                                             self.__lines_by_path_id.get(path_id, []),
                                                             self.__nerves_by_path_id.get(path_id, []),
                                                             self.__routes_by_path_id[path_id]
                                                            )
                    self.__resolved_pathways.add_path_type(path_id, self.__types_by_path_id.get(path_id))
                    self.__resolved_pathways.set_model_id(path_id, self.__path_models.get(path_id))
            except ValueError as err:
                log.error('Path {}: {}'.format(path_id, str(err)))
                errors = True
        self.__route_paths(network, model_to_features)
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
