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

from mapmaker.routing import Network
from mapmaker.utils import FilePath

from .anatomicalmap import AnatomicalMap
from .pathways import Pathways

#===============================================================================

class ExternalProperties(object):
    def __init__(self, flatmap, manifest, knowledgebase):
        self.__anatomical_map = AnatomicalMap(manifest.anatomical_map)
        self.__knowledgebase = knowledgebase

        self.__properties_by_class = {}
        self.__properties_by_id = {}
        if manifest.properties is None:
            properties_dict = {}
        else:
            properties_dict = FilePath(manifest.properties).get_json()
        self.__set_properties(properties_dict.get('features', []))
        self.__model_to_features = defaultdict(set)

        # Load path definitions
        self.__pathways = Pathways(flatmap, properties_dict.get('paths', []))
        for connectivity_source in manifest.connectivity:
            connectivity = FilePath(connectivity_source).get_json()
            self.__pathways.add_connectivity(connectivity)

        # Load network definitions
        self.__networks = { network.get('id'): Network(network)
                                for network in properties_dict.get('networks', []) }

    @property
    def resolved_pathways(self):
        return self.__pathways.resolved_pathways

    def __set_properties(self, features_list):
    #=========================================
        for feature in features_list:
            if 'class' in feature:
                cls = feature['class']
                properties = feature.get('properties', {})
                if cls in self.__properties_by_class:
                    self.__properties_by_class[cls].update(properties)
                else:
                    self.__properties_by_class[cls] = properties
            if 'id' in feature:
                id = feature['id']
                properties = feature.get('properties', {})
                if id in self.__properties_by_id:
                    self.__properties_by_id[id].update(properties)
                else:
                    self.__properties_by_id[id] = properties

    def generate_networks(self, feature_map):
    #========================================
        for network in self.__networks.values():
            if network.id is not None:
                network.create_geometry(feature_map)
                self.__pathways.resolve_pathways(network, feature_map, self.__model_to_features)

    def update_properties(self, properties):
    #=======================================
        cls = properties.get('class')
        if cls is not None:
            properties.update(self.__anatomical_map.properties(cls))
            properties.update(self.__properties_by_class.get(cls, {}))
            properties.update(self.__pathways.add_line_or_nerve(cls))
        id = properties.get('id')
        if id is not None:
            properties.update(self.__properties_by_id.get(id, {}))
            # Drop network nodes that don't have anatomical meaning
            for network in self.__networks.values():
                if network.has_node(id) and 'models' not in properties:
                    properties['exclude'] = True
                    break
            properties.update(self.__pathways.add_line_or_nerve(id))
        if 'marker' in properties:
            properties['type'] = 'marker'
            if 'datasets' in properties:
                properties['kind'] = 'dataset'
            elif 'scaffolds' in properties:
                properties['kind'] = 'scaffold'
            elif 'simulations' in properties:
                properties['kind'] = 'simulation'
        if 'models' in properties:
            # Make sure our knowledgebase knows about the anatomical object
            knowledge = self.__knowledgebase.entity_knowledge(properties['models'])
            if 'label' not in properties:
                properties['label'] = knowledge.get('label')
        return properties

    def update_feature_properties(self, feature):
    #============================================
        self.update_properties(feature.properties)
        if feature.models is not None:
            self.__model_to_features[feature.models].add(feature)

#===============================================================================
