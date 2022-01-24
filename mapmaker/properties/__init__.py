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

from mapmaker.knowledgebase import get_knowledge, update_publications
from mapmaker.routing import Network
from mapmaker.utils import FilePath

from .anatomicalmap import AnatomicalMap
from .pathways import Pathways

#===============================================================================

class ExternalProperties(object):
    def __init__(self, flatmap, manifest):
        self.__anatomical_map = AnatomicalMap(manifest.anatomical_map)
        self.__properties_by_class = defaultdict(dict)
        self.__properties_by_id = defaultdict(dict)
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
        for connectivity_model in manifest.neuron_connectivity:
            self.__pathways.add_connectivity_model(connectivity_model)

        # Load network centreline definitions
        self.__networks = { network.get('id'): Network(network, self)
                                for network in properties_dict.get('networks', []) }

    @property
    def connectivity(self):
        return self.__pathways.connectivity

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
        elif features is not None:
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
        self.__pathways.generate_connectivity(
            feature_map,
            list(self.__networks.values()))

    def get_property(self, id, key):
    #===============================
        properties = self.__properties_by_id.get(id, {})
        property = properties.get(key)
        if property is None:
            if 'class' in properties:
                for cls in properties['class'].split():
                    property = self.__properties_by_class.get(cls, {}).get(key)
                    if property is not None:
                        break
            else:  # Old way...
                property = self.__properties_by_class.get(id, {}).get(key)
        return property

    def save_knowledge(self):
    #========================
        if self.__pathways is not None:
            # Save publications that have come from JSON connectivity data
            knowledge = self.__pathways.knowledge()
            if 'publications' in knowledge:
                for source, publication in knowledge.get('publications'):
                    update_publications(source, publication)

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
            # Drop network nodes that don't have anatomical meaning
            for network in self.__networks.values():
                if network.contains(id) and 'models' not in feature_properties:
                    feature_properties['exclude'] = True
                    break
        self.__pathways.update_line_or_nerve_properties(feature_properties)

        if 'marker' in feature_properties:
            feature_properties['type'] = 'marker'
            if 'datasets' in feature_properties:
                feature_properties['kind'] = 'dataset'
            elif 'scaffolds' in feature_properties:
                feature_properties['kind'] = 'scaffold'
            elif 'simulations' in feature_properties:
                feature_properties['kind'] = 'simulation'
        if 'models' in feature_properties:
            # Make sure our knowledgebase knows about the anatomical object
            knowledge = get_knowledge(feature_properties['models'])
            if 'label' not in feature_properties:
                feature_properties['label'] = knowledge.get('label')
        return feature_properties

    def update_feature_properties(self, feature):
    #============================================
        self.update_properties(feature.properties)

#===============================================================================
