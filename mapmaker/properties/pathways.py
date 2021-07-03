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

#===============================================================================

from pyparsing import delimitedList, Group, ParseResults, Suppress

#===============================================================================

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
    try:
        if isinstance(line_ids, str):
            path_lines = PATH_LINES.parseString(line_ids, parseAll=True)
        else:
            path_lines = [LINE_ID.parseString(line_id)[0] for line_id in line_ids]
    except ParseException:
        raise ValueError('Syntax error in path lines list: {}'.format(line_ids))
    return path_lines

def parse_route_nodes(node_ids):
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
        raise ValueError('Syntax error in route node list: {}'.format(node_ids))
    return list(route_nodes)

def parse_nerves(node_ids):
    try:
        nerves = NERVES.parseString(node_ids, parseAll=True)
    except ParseException:
        raise ValueError('Syntax error in nerve list: {}'.format(node_ids))
    return nerves

#===============================================================================

class FeatureMap(object):
    def __init__(self, id_map, class_map):
        self.__id_map = id_map
        self.__class_map = class_map

    def features(self, id):
        feature = self.__id_map.get(id)
        if feature is None:
            return self.__class_map.get(id, [])
        return [feature]

    def feature_ids(self, ids):
        feature_ids = []
        for id in ids:
            feature_ids.extend([f.feature_id for f in self.features(id)])
        return feature_ids

#===============================================================================

class ResolvedPath(object):
    def __init__(self):
        self.__lines = set()
        self.__nerves = set()
        self.__nodes = set()
        self.__models = None

    @property
    def as_dict(self):
        path_dict = {
            'lines': list(self.__lines),
            'nerves': list(self.__nerves),
            'nodes': list(self.__nodes)
        }
        if self.__models is not None:
            path_dict['models'] = self.__models
        return path_dict

    def extend_lines(self, lines):
        self.__lines.update(lines)

    def extend_nerves(self, nerves):
        self.__nerves.update(nerves)

    def extend_nodes(self, nodes):
        self.__nodes.update(nodes)

    def set_model_id(self, model_id):
        self.__models = model_id

#===============================================================================

class ResolvedPathways(object):
    def __init__(self, id_map, class_map):
        self.__feature_map = FeatureMap(id_map, class_map)
        self.__paths = defaultdict(ResolvedPath)  # path_id: ResolvedPath
        self.__node_paths = defaultdict(list)     # node_id: [ path_ids ]
        self.__type_paths = defaultdict(list)     # type: [ path _ids ]

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

    def add_path_type(self, path_id, path_type):
        self.__type_paths[path_type].append(path_id)

    def __resolve_nodes_for_path(self, path_id, nodes):
        node_ids = []
        for id in nodes:
            for feature in self.__feature_map.features(id):
                if not feature.get_property('exclude'):
                    node_id = feature.feature_id
                    self.__node_paths[node_id].append(path_id)
                    node_ids.append(node_id)
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
    def __init__(self, id, source=None):
        self.__id = id
        self.__source = source
        self.__path_ids = []

    @property
    def source(self):
        return self.__source

    @property
    def path_ids(self):
        return self.__path_ids

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
        self.__connectivity_models = [ ConnectivityModel('') ]
        self.__path_models = {}
        self.__extend_pathways(self.__connectivity_models[0], paths_list)

    @staticmethod
    def make_list(lst):
        return (lst if isinstance(lst, list)
           else list(lst) if isinstance(lst, ParseResults)
           else [ lst ])

    @property
    def resolved_pathways(self):
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

    def add_line_or_nerve(self, id_or_class):
    #========================================
        path_id = None
        properties = {}
        # Is the id_or_class that of a line?
        if id_or_class in self.__paths_by_line_id:
            path_id = self.__paths_by_line_id[id_or_class][0]
            if path_id in self.__types_by_path_id:
                properties['kind'] = self.__types_by_path_id[path_id]  ## Can we just put this into `kind`
                                                                       ## and have viewer work out if dashed??
                properties['type'] = 'line-dash' if properties['kind'].endswith('-post') else 'line'
            else:
                properties['type'] = 'line'
            if path_id in self.__path_models:
                properties['models'] = self.__path_models[path_id]
            if path_id in self.__connectivity_by_path:
                source = self.__connectivity_by_path[path_id].source
                if source is not None:
                    properties['source'] = source
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
        connectivity_model = ConnectivityModel(connectivity['id'], connectivity.get('source'))
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

    def __route_paths(self, id_map, class_map, anatomical_map, network_router, connection_models):
    #=============================================================================================
        def get_point_for_anatomy(anatomical_id, error_list):
            if anatomical_id in anatomical_map:
                features_set = anatomical_map[anatomical_id]
                if len(features_set) == 1:
                    return list(features_set)[0].geometry.centroid.coords[0]
                else:
                    error_list.append("Multiple features for {}".format(anatomical_id))
            else:
                error_list.append("Cannot find feature for {}".format(anatomical_id))
            return None

        log('Routing paths...')
        for model, path_connections in connection_models.items():
            layer = FeatureLayer('{}_routes'.format(model), self.__flatmap, exported=True)
            self.__flatmap.add_layer(layer)
            for id, segments in network_router.layout(model, path_connections).items():
                for segment in segments:
                    properties = { 'tile-layer': 'autopaths' }
                    properties.update(segment.properties())
                    layer.add_feature(self.__flatmap.new_feature(segment.geometry(), properties))

    def resolve_pathways(self, id_map, class_map, anatomical_map, network_router, connection_models):
    #================================================================================================
        if self.__resolved_pathways is not None:
            return
        self.__resolved_pathways = ResolvedPathways(id_map, class_map)
        errors = False
        for path_id in self.__layer_paths:
            try:
                self.__resolved_pathways.resolve_pathway(path_id,
                                                         self.__lines_by_path_id.get(path_id, []),
                                                         self.__nerves_by_path_id.get(path_id, []),
                                                         self.__routes_by_path_id.get(path_id)
                                                        )
                self.__resolved_pathways.add_path_type(path_id, self.__types_by_path_id.get(path_id))
                self.__resolved_pathways.set_model_id(path_id, self.__path_models.get(path_id))
            except ValueError as err:
                log.error('Path {}: {}'.format(path_id, str(err)))
                errors = True
        self.__route_paths(id_map, class_map, anatomical_map, network_router, connection_models)
        if errors:
            raise ValueError('Errors in mapping paths and routes')

#===============================================================================
