#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2020 - 2023  David Brooks
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

import math
from typing import Optional

#===============================================================================

from beziers.point import Point as BezierPoint
import shapely.geometry
from shapely.geometry.base import BaseGeometry

#===============================================================================

from mapmaker.geometry.beziers import point_to_coords

#===============================================================================

class GeometricShape(object):
    def __init__(self, geometry: BaseGeometry, properties: Optional[dict] = None):
        self.__geometry = geometry
        self.__properties = properties if properties is not None else {}

    @property
    def geometry(self) -> BaseGeometry:
        return self.__geometry

    @property
    def properties(self) -> dict:
        return self.__properties

    @classmethod
    def circle(cls, centre: tuple[float, float], radius: float = 2000, properties: Optional[dict] = None):
        return cls(shapely.geometry.Point(centre).buffer(radius), properties)

    @classmethod
    def line(cls, start: tuple[float, float], end: tuple[float, float], properties: Optional[dict] = None):
        return cls(shapely.geometry.LineString([start, end]), properties)

    @classmethod
    def arrow(cls, back: BezierPoint, heading: float, length: float, properties: Optional[dict] = None):
        tip = back + BezierPoint.fromAngle(heading)*length
        offset = BezierPoint.fromAngle(heading + math.pi/2)*length/3
        arrow = shapely.geometry.Polygon([point_to_coords(tip), point_to_coords(back+offset), point_to_coords(back-offset)])
        return cls(arrow, properties)

#===============================================================================
