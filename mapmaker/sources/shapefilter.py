#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2019 - 2022  David Brooks
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

import shapely.strtree

#===============================================================================

from mapmaker.utils import log

#===============================================================================

class ShapeFilter:
    def __init__(self):
        self.__excluded_shape_attributes = {}
        self.__excluded_shape_geometries = []
        self.__excluded_shape_rtree = None

    @staticmethod
    def __shape_attribs(shape):
        return {
            'label': shape.properties.get('label', ''),
            'colour': shape.properties.get('colour'),
            'alpha': shape.properties.get('alpha', 1)   #   -->  opacity ??
        }

    def add_shape(self, shape):
    #==========================
        geometry = shape.geometry
        if 'Polygon' in geometry.geom_type:
            self.__excluded_shape_geometries.append(geometry)
            self.__excluded_shape_attributes[id(geometry)] = self.__shape_attribs(shape)

    def create_filter(self):
    #=======================
        self.__excluded_shape_rtree = shapely.strtree.STRtree(self.__excluded_shape_geometries)

    def filter(self, shape):
    #=======================
        if self.__excluded_shape_rtree is not None:
            geometry = shape.geometry
            if 'Polygon' in geometry.geom_type:
                if (self.__shape_excluded(geometry)
                 or self.__shape_excluded(geometry, overlap=0.80)
                 or self.__shape_excluded(geometry, attributes=self.__shape_attribs(shape))):
                    shape.properties['exclude'] = True

    def __shape_excluded(self, geometry, overlap=0.98, attributes=None, show=False):
    #===============================================================================
        if self.__excluded_shape_rtree is not None:
            intersecting_shapes = self.__excluded_shape_rtree.query(geometry)
            for g in intersecting_shapes:
                if g.intersects(geometry):
                    if attributes is None:
                        intersecting_area = g.intersection(geometry).area
                        if (intersecting_area >= overlap*geometry.area
                        and intersecting_area >= overlap*g.area):
                            if show:
                                attribs = self.__excluded_shape_attributes[id(g)]
                                log.info(f'Excluded at {100*overlap}% by {attribs}')
                            return True
                    elif attributes == self.__excluded_shape_attributes[id(g)]:
                        if show:
                            log.info(f'Excluded by {attributes}')
                        return True
        return False

#===============================================================================

class ShapeFilters:
    def __init__(self):
        self.__map_shape_filter = ShapeFilter()
        self.__svg_shape_filter = ShapeFilter()

    @property
    def map_filter(self):
        return self.__map_shape_filter

    @property
    def svg_filter(self):
        return self.__svg_shape_filter

#===============================================================================
