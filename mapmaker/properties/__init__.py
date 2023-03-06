#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2019  David Brooks
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

import mapmaker.knowledgebase as knowledgebase
from mapmaker.routing import Network
from mapmaker.settings import settings
from mapmaker.utils import FilePath, log

from .anatomicalmap import AnatomicalMap
from .pathways import ConnectorSet, Pathways

#===============================================================================

class ExternalProperties(object):
    def __init__(self, flatmap, manifest):
        self.__anatomical_map = AnatomicalMap(manifest.anatomical_map)
        self.__properties_by_class = defaultdict(dict)
        self.__properties_by_id = defaultdict(dict)
        self.__nerve_ids_by_model = {}
        self.__nerve_models_by_id = {}
        if manifest.properties is None:
            properties_dict = {}
        else:
            properties_dict = FilePath(manifest.properties).get_json()
        self.__set_class_properties(properties_dict.get('classes'))
        self.__set_feature_properties(properties_dict.get('features'))

        # Load path definitions in properties' file
        self.__pathways = Pathways(flatmap, properties_dict.get('paths', []))

        # Connectivity defined in JSON
        for connectivity_source in manifest.connectivity:
            connectivity = FilePath(connectivity_source).get_json()
            self.__pathways.add_connectivity(connectivity)

        # Connectivity from SciCrunch
        connectivity_models = knowledgebase.connectivity_models()
        for connectivity_model in manifest.neuron_connectivity:
            path_filter = None
            traced_paths = None
            if isinstance(connectivity_model, dict):
                model_uri = connectivity_model['uri']
                if (filter_lists := connectivity_model.get('filter')) is not None:
                    include_ids = filter_lists['include'] if 'include' in filter_lists else None
                    exclude_ids = filter_lists['exclude'] if 'exclude' in filter_lists else None
                    if 'trace' in filter_lists:
                        traced_paths = filter_lists['trace']
                        include_ids = traced_paths if include_ids is None else (include_ids + traced_paths)
                    path_filter = lambda path_id: ((include_ids is None or include_ids is not None and path_id in include_ids)
                                               and (exclude_ids is None or exclude_ids is not None and path_id not in exclude_ids))
            else:
                model_uri = connectivity_model
            if model_uri in connectivity_models:
                self.__pathways.add_connectivity_model(model_uri, self, path_filter=path_filter, traced_paths=traced_paths)
            else:
                log.warning(f'Connectivity for {model_uri} not available in SCKAN')

        # Load network centreline definitions
        self.__networks = { network.get('id'): Network(network, self)
                                for network in properties_dict.get('networks', []) }

    @property
    def connectivity(self):
        return self.__pathways.connectivity

    @property
    def nerve_ids_by_model(self):
        return self.__nerve_ids_by_model

    @property
    def nerve_models_by_id(self):
        return self.__nerve_models_by_id

    @property
    def pathways(self):
        return self.__pathways

    def network_feature(self, feature):
    #==================================
        # Is the ``feature`` included in some network?
        for network in self.__networks.values():
            if network.has_feature(feature):
                return True
        return False

    def __set_class_properties(self, classes):
    #=========================================
        if classes is not None:
            for cls, properties in classes.items():
                self.__properties_by_class[cls].update(properties)

    def __set_feature_properties(self, features):
    #============================================
        if isinstance(features, dict):
            for id, properties in features.items():
                self.__properties_by_id[id].update(properties)
                if (properties.get('type') == 'nerve'
                and (entity := properties.get('models')) is not None):
                    if entity in self.__nerve_ids_by_model:
                        log.error(f'Nerve `{entity}` has already been assigned to a feature')
                    else:
                        self.__nerve_ids_by_model[entity] = id
                    if id in self.__nerve_models_by_id:
                        log.error(f'Feature `{id}` has already been assigned a model')
                    else:
                        self.__nerve_models_by_id[id] = entity
        elif features is not None:
            # ``Old`` style of properties
            for feature in features:
                if 'class' in feature:
                    cls = feature['class']
                    properties = feature.get('properties', {})
                    self.__properties_by_class[cls].update(properties)
                if 'id' in feature:
                    id = feature['id']
                    properties = feature.get('properties', {})
                    self.__properties_by_id[id].update(properties)

    def generate_connectivity(self, feature_map):
    #============================================
        self.__pathways.set_feature_map(feature_map)
        for network in self.__networks.values():
            network.set_feature_map(feature_map)
        self.__pathways.generate_connectivity(self.__networks.values())

    def get_property(self, id, key):
    #===============================
        return self.properties(id).get(key)

    def set_property(self, id, key, value):
    #======================================
        self.__properties_by_id[id][key] = value

    def properties(self, id):
    #========================
        properties = {'id': id}
        properties.update(self.__properties_by_id.get(id, {}))
        self.update_properties(properties)
        return properties

    def update_properties(self, feature_properties):
    #===============================================
        classes = feature_properties.get('class', '').split()
        id = feature_properties.get('id')
        if id is not None:
            classes.extend(self.__properties_by_id.get(id, {}).get('class', '').split())
        for cls in classes:
            feature_properties.update(self.__anatomical_map.properties(cls))
            feature_properties.update(self.__properties_by_class.get(cls, {}))
        if id is not None:         # id overrides class
            feature_properties.update(self.__anatomical_map.properties(id))
            feature_properties.update(self.__properties_by_id.get(id, {}))
        self.__pathways.update_line_or_nerve_properties(feature_properties)

        if 'marker' in feature_properties:
            feature_properties['type'] = 'marker'
            if 'datasets' in feature_properties:
                feature_properties['kind'] = 'dataset'
            elif 'scaffolds' in feature_properties:
                feature_properties['kind'] = 'scaffold'
            elif 'simulations' in feature_properties:
                feature_properties['kind'] = 'simulation'
        if (entity := feature_properties.get('models')) is not None and entity.strip() != '':
            # Make sure our knowledgebase knows about the anatomical object
            knowledge = knowledgebase.get_knowledge(entity)
            if 'label' not in feature_properties:
                feature_properties['label'] = knowledge.get('label')
        elif 'label' not in feature_properties and 'name' in feature_properties:
            feature_properties['label'] = feature_properties.pop('name')

        authoring = settings.get('authoring', False)
        if authoring:
            # Show id and classes in label if authoring
            labels = []
            if (label := feature_properties.get('label', '')):
                labels.append(label)
            if (shape_id := feature_properties.get('shape-id')) is not None:
                labels.append(f'Shape: {shape_id}')
            if (model := feature_properties.get('models')) is not None:
                labels.append(f'Models: {model}')
            if (type := feature_properties.get('type')) is not None:
                labels.append(f'Type: {type}')
            if len(classes):
                labels.append(f'Class: {", ".join(classes)}')
            if id is not None:
                labels.append(f'Id: {id}')
            if len(labels):  # We don't want empty tooltips
                feature_properties['label'] = '\n'.join(labels)
        elif 'label' in feature_properties and feature_properties['label'] in [None, '']:
            del feature_properties['label']   # So empty values doesn't get passed to the viewer

        # Hide network node features when not authoring or not a FC flatmap
        if not (authoring or settings.get('functionalConnectivity', False)):
            if (feature_properties.get('node', False)
            or not settings.get('showCentrelines', False)
               and feature_properties.get('centreline', False)):
                feature_properties['invisible'] = True
                feature_properties['exclude'] = True
        return feature_properties

        return feature_properties

#===============================================================================
