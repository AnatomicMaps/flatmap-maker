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

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mapmaker.flatmap import Feature

#===============================================================================

class FeatureSearch(object):
    def __init__(self, features: list['Feature']):
        self.__min_x = sorted(features, key=lambda f: f.geometry.bounds[0])
        self.__min_y = sorted(features, key=lambda f: f.geometry.bounds[1])
        self.__max_x = sorted(features, key=lambda f: f.geometry.bounds[2])
        self.__max_y = sorted(features, key=lambda f: f.geometry.bounds[3])

    def features_covering(self, feature: 'Feature'):
    #===============================================
        covering = set(self.__features_before(feature, self.__min_x, key=lambda f: f.geometry.bounds[0]))
        covering.intersection_update(self.__features_before(feature, self.__min_y, key=lambda f: f.geometry.bounds[1]),
                                     self.__features_after(feature, self.__max_x, key=lambda f: f.geometry.bounds[2]),
                                     self.__features_after(feature, self.__max_y, key=lambda f: f.geometry.bounds[3]))
        covering.discard(feature)  # A covering of a feature doesn't include the feature
        covering = [f for f in covering if f.geometry.contains(feature.geometry)]
        return sorted(covering, key=lambda f: f.geometry.area)

    def features_inside(self, feature: 'Feature'):
    #=============================================
        interior = set(self.__features_after(feature, self.__min_x, key=lambda f: f.geometry.bounds[0]))
        interior.intersection_update(self.__features_after(feature, self.__min_y, key=lambda f: f.geometry.bounds[1]),
                                     self.__features_before(feature, self.__max_x, key=lambda f: f.geometry.bounds[2]),
                                     self.__features_before(feature, self.__max_y, key=lambda f: f.geometry.bounds[3]))
        interior.discard(feature)  # The interior of a feature doesn't include the feature
        interior = [f for f in interior if feature.geometry.contains(f.geometry)]
        return sorted(interior, key=lambda f: f.geometry.area)

    @staticmethod
    def __features_before(feature: 'Feature', features: list['Feature'], key=lambda f: f):
        start = 0
        end = len(features)
        while (end - start) > 1:
            mid = (start + end) // 2
            if key(feature) >= key(features[mid]):
                start = mid
            else:
                end = mid
        return features[:end]

    @staticmethod
    def __features_after(feature: 'Feature', features: list['Feature'], key=lambda f: f):
        start = 0
        end = len(features)
        while (end - start) > 1:
            mid = (start + end) // 2
            if key(feature) > key(features[mid]):
                start = mid
            else:
                end = mid
        return features[end:]

#===============================================================================
