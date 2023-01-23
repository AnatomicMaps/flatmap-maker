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

from typing import Optional

#===============================================================================

from shapely.geometry.base import BaseGeometry
import shapely.strtree

#===============================================================================

from mapmaker.utils import log

from .shape import Shape

#===============================================================================

class ShapeFilter:
    def __init__(self):
        self.__excluded_shape_attributes = {}
        self.__excluded_shape_geometries = []
        self.__excluded_shape_rtree = None
        self.__warn_create = False
        self.__warn_filter = False

    @staticmethod
    def __attributes(shape: Shape):
        return {
            'label': shape.label,
            'colour': shape.colour,
            'opacity': shape.opacity
        }

    def add_shape(self, shape: Shape):
    #=================================
        geometry = shape.geometry
        if geometry is not None and self.__excluded_shape_rtree is None:
            if 'Polygon' in geometry.geom_type:
                self.__excluded_shape_geometries.append(geometry)
                self.__excluded_shape_attributes[id(geometry)] = self.__attributes(shape)
        elif not self.__warn_create:
            log.warning('Cannot add shapes to filter after it has been created...')
            self.__warn_create = True

    def create_filter(self):
    #=======================
        if self.__excluded_shape_rtree is None:
            self.__excluded_shape_rtree = shapely.strtree.STRtree(self.__excluded_shape_geometries)

    def reset_filter(self):
    #=======================
        if self.__excluded_shape_rtree is not None:
            del self.__excluded_shape_rtree
        self.create_filter()

    def filter(self, shape: Shape) -> bool:
    #======================================
        if self.__excluded_shape_rtree is not None:
            geometry = shape.geometry
            if geometry is not None and 'Polygon' in geometry.geom_type:
                if ((attribs := self.__shape_excluded(geometry)) is not None
                 or (attribs := self.__shape_excluded(geometry, overlap=0.80)) is not None
                 or (attribs := self.__shape_excluded(geometry, attributes=self.__attributes(shape))) is not None):
                    shape.properties['exclude'] = True
                    shape.properties.update(attribs)
                    return True
        elif not self.__warn_filter:
            log.warning('Shape filter has not been created...')
            self.__warn_filter = True
        return False

    def __shape_excluded(self, geometry: BaseGeometry, overlap=0.98, attributes=None, show=False) -> Optional[dict]:
    #===============================================================================================================
        if self.__excluded_shape_rtree is not None:
            intersecting_shapes_indices = self.__excluded_shape_rtree.query(geometry)
            for index in intersecting_shapes_indices:
                g = self.__excluded_shape_geometries[index]
                if g.intersects(geometry):
                    if attributes is None:
                        intersecting_area = g.intersection(geometry).area
                        if (intersecting_area >= overlap*geometry.area
                        and intersecting_area >= overlap*g.area):
                            if show:
                                log.info(f'Excluded by {100*overlap}% overlap')
                            return self.__excluded_shape_attributes[id(g)]
                    elif attributes == self.__excluded_shape_attributes[id(g)]:
                        if show:
                            log.info(f'Excluded by {attributes} match')
                        return attributes
        return None

#===============================================================================
