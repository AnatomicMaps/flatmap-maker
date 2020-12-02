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

from mapmaker.knowledgebase.labels import AnatomicalMap
from mapmaker.utils import read_json

from .pathways import Pathways

#===============================================================================

class JsonProperties(object):
    def __init__(self, manifest):
        self.__anatomical_map = AnatomicalMap(manifest.anatomical_map)
        self.__properties_by_class = {}
        self.__properties_by_id = {}
        properties_dict = {}
        properties_file = manifest.properties
        if properties_file is not None:
            properties_dict = read_json(properties_file)
        self.__set_properties(properties_dict.get('features', []))
        self.__pathways = Pathways(properties_dict.get('paths', []))

    def __set_properties(self, features_list):
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

    @property
    def resolved_pathways(self):
        return self.__pathways.resolved_pathways

    def resolve_pathways(self, id_map, class_map):
    #=============================================
        if self.__pathways is not None:
            self.__pathways.resolve_pathways(id_map, class_map)

    def update_feature_properties(self, feature_properties):
    #=======================================================
        cls = feature_properties.get('class')
        if cls is not None:
            feature_properties.update(self.__anatomical_map.properties(cls))
            feature_properties.update(self.__properties_by_class.get(cls, {}))
            if self.__pathways is not None:
                feature_properties.update(self.__pathways.add_path(cls))
        id = feature_properties.get('id')
        if id is not None:
            feature_properties.update(self.__properties_by_id.get(id, {}))
            if self.__pathways is not None:
                feature_properties.update(self.__pathways.add_path(id))
        if 'marker' in feature_properties:
            feature_properties['type'] = 'marker'
            if 'datasets' in feature_properties:
                feature_properties['kind'] = 'dataset'
            elif 'scaffolds' in feature_properties:
                feature_properties['kind'] = 'scaffold'
            elif 'simulations' in feature_properties:
                feature_properties['kind'] = 'simulation'
        if 'models' in feature_properties and 'label' not in feature_properties:
            feature_properties['label'] = self.__anatomical_map.label(feature_properties['models'])
        return feature_properties

#===============================================================================
