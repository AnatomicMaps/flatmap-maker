#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2019, 2020  David Brooks
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
from typing import Any

from shapely.geometry.base import BaseGeometry

#===============================================================================

from mapmaker.utils import log
from mapmaker.knowledgebase import get_label

#===============================================================================

def entity_name(entity):
    if entity is None:
        return 'None'
    label = get_label(entity)
    if label == entity:
        return entity
    else:
        return f'{label} ({entity})'

#===============================================================================

class Feature(object):
    def __init__(self, feature_id: int,
                       geometry: BaseGeometry,
                       properties: dict,
                       has_children:bool=False):
        self.__feature__id = feature_id     # Must be numeric for tipeecanoe
        self.__geometry = geometry
        self.__properties = properties.copy()
        self.__properties['featureId'] = feature_id   # Used by flatmap viewer
        self.__properties['geometry'] = geometry.geom_type
        self.__has_children = has_children

    def __str__(self):
        return 'Feature {}: {}'.format(self.__geometry.geom_type,
            { k:v for k, v in self.__properties.items() if k != 'bezier-segments'})

    @property
    def feature_id(self) -> int:
        return self.__feature__id

    @property
    def geom_type(self) -> str:
        return self.__geometry.geom_type if self.__geometry else None

    @property
    def geometry(self) -> BaseGeometry:
        return self.__geometry

    @geometry.setter
    def geometry(self, geometry: BaseGeometry):
        self.__geometry = geometry

    @property
    def has_children(self) -> bool:
        return self.__has_children

    @property
    def id(self) -> str:
        return self.__properties.get('id')

    @property
    def models(self) -> str:
        return self.__properties.get('models')

    @property
    def properties(self) -> dict:
        return self.__properties

    def visible(self) -> bool:
        return not self.property('invisible')

    def del_property(self, key: str) -> Any:
        if key in self.__properties:
            return self.__properties.pop(key)

    def property(self, key: str, default: Any=None) -> Any:
        return self.__properties.get(key, default)

    def has_property(self, key: str) -> bool:
        return self.__properties.get(key, '') != ''

    def set_property(self, key: str, value: Any) -> None:
        if value is None:
            self.del_property(key)
        else:
            self.__properties[key] = value

#===============================================================================

class FeatureMap(object):
    def __init__(self):
        self.__class_to_features = defaultdict(list)
        self.__id_to_feature = {}
        self.__model_to_features = defaultdict(list)
        self.__unknown_anatomy = []

    def add_feature(self, feature):
        if feature.id is not None:
            self.__id_to_feature[feature.id] = feature
        if feature.has_property('class'):
            classes = feature.property('class').split()
            for cls in classes:
                self.__class_to_features[cls].append(feature)
        if feature.models is not None:
            self.__model_to_features[feature.models].append(feature)

    def duplicate_id(self, id):
        return self.__id_to_feature.get(id, None) is not None

    def features(self, id):
        feature = self.__id_to_feature.get(id)
        if feature is None:
            return self.__class_to_features.get(id, [])
        return [feature]

    def feature_ids(self, ids):
        feature_ids = []
        for id in ids:
            feature_ids.extend([f.feature_id for f in self.features(id)])
        return feature_ids

    def find_path_features_by_anatomical_id(self, path_id, anatomical_id, anatomical_layers):
        if len(anatomical_layers) == 0:
            anatomical_features = self.__model_to_features.get(anatomical_id, [])
        else:
            features = self.__model_to_features.get(anatomical_id, [])
            for anatomical_layer in anatomical_layers:
                included_features = []
                layer_features = self.__model_to_features.get(anatomical_layer, [])
                for layer_feature in layer_features:
                    for feature in features:
                        if layer_feature.geometry.contains(feature.geometry.centroid):
                            included_features.append(feature)
                anatomical_features = included_features
                if len(included_features) == 1:
                    break
        if len(anatomical_features) == 0:
            if (anatomical_id, anatomical_layers) not in self.__unknown_anatomy:
                if len(anatomical_layers) == 0:
                    log.warning(f'{path_id}: Cannot find feature: {entity_name(anatomical_id)}')
                else:
                    layer_names = ', '.join([entity_name(entity) for entity in anatomical_layers if entity is not None])
                    log.warning(f'{path_id}: Cannot find feature: {entity_name(anatomical_id)} in layers: {layer_names}')
                self.__unknown_anatomy.append((anatomical_id, anatomical_layers))
        return anatomical_features

    def get_feature(self, id):
        return self.__id_to_feature.get(id)

#===============================================================================
