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

import json

#===============================================================================

try:
    from labels import AnatomicalMap
    from parser import Parser
    from pathways import Pathways
except ImportError:
    from mapmaker.labels import AnatomicalMap
    from mapmaker.parser import Parser
    from mapmaker.pathways import Pathways

#===============================================================================

class Properties(object):
    def __init__(self, settings):
        self.__anatomical_map = AnatomicalMap(settings.label_database,
                                              settings.anatomical_map)
        self.__properties_by_class = {}
        self.__properties_by_id = {}
        self.__pathways = None
        self.__parse_errors = []
        self.__ids_by_external_id = {}    # id: unique_feature_id
        self.__class_counts = {}          # class: count
        self.__ids_by_class = {}          # class: unique_feature_id
        if settings.properties:
            with open(settings.properties) as fp:
                properties_dict = json.loads(fp.read())
                self.__set_properties(properties_dict['features'])
                self.__pathways = Pathways(properties_dict['paths'])

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
    def pathways(self):
        return self.__pathways

    def properties_from_class(self, cls):
    #====================================
        return self.__properties_by_class.get(cls, {})

    def properties_from_id(self, id):
    #================================
        return self.__properties_by_id.get(id, {})

    def set_class_id(self, class_id, feature_id):
    #============================================
        self.__ids_by_class[class_id] = feature_id

    def set_feature_id(self, external_id, feature_id):
    #=================================================
        self.__ids_by_external_id[external_id] = feature_id

    def set_feature_ids(self):
    #=========================
        if self.__pathways is not None:
            self.__pathways.set_feature_ids(
                self.__ids_by_external_id,
                self.__ids_by_class,
                self.__class_counts
            )

    def get_properties(self, shape, group_name='', slide_number=1):
    #==============================================================
        if shape.name.startswith('.'):
            properties = Parser.shape_properties(shape.name)
            properties['shape-name'] = shape.name
            properties['tile-layer'] = 'features'
            if 'error' in properties:
                properties['error'] = 'syntax'
                self.__parse_errors.append('Shape in slide {}, group {}, has annotation syntax error: {}'
                                           .format(slide_number, group_name, shape.name))
            else:
                for (key, value) in properties.items():
                    if key in ['id', 'path']:
                        if value in self.__ids_by_external_id:
                            self.__parse_errors.append('Shape in slide {}, group {}, has a duplicate id: {}'
                                                       .format(slide_number, group_name, shape.name))
                        else:
                            self.__ids_by_external_id[value] = None
                    if key == 'warning':
                        self.__parse_errors.append('Warning, slide {}, group {}: {}'
                                                  .format(slide_number, group_name, value))
                if 'class' in properties:
                    cls = properties['class']
                    if cls in self.__class_counts:
                        self.__class_counts[cls] += 1
                    else:
                        self.__class_counts[cls] = 1
                    self.__ids_by_class[cls] = None

                    properties.update(self.__anatomical_map.properties(cls))
                    properties.update(self.properties_from_class(cls))
                    if self.__pathways is not None:
                        properties.update(self.__pathways.properties(cls))

                if 'external-id' in properties:
                    id = properties['external-id']
                    properties.update(self.properties_from_id(id))
                    if self.__pathways is not None:
                        properties.update(self.__pathways.properties(id))

                if 'marker' in properties:
                    properties['type'] = 'marker'
                    if 'datasets' in properties:
                        properties['kind'] = 'dataset'
                    elif 'scaffolds' in properties:
                        properties['kind'] = 'scaffold'
                    elif 'simulations' in properties:
                        properties['kind'] = 'simulation'
                    if 'models' in properties and 'label' not in properties:
                        if self.__anatomical_map is not None:
                            properties['label'] = self.__anatomical_map.label(properties['models'])

                return properties
        else:
            return {
                'shape-name': shape.name,
                'tile-layer': 'features'
            }

        return None

#===============================================================================
