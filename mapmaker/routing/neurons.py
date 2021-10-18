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

from opencmiss.zinc.status import OK as ZINC_OK

#===============================================================================

from mapmaker.routing.scaffold_1d import Scaffold1dPath
from mapmaker.routing.manager import ChangeManager
from mapmaker.routing.utils.pair_iteration import pairwise
from mapmaker.routing.utils.maths import mult
from mapmaker.routing.utils.maths import add
from mapmaker.routing.utils.maths import sub
from mapmaker.routing.utils.interpolation import smooth_cubic_hermite_derivatives_line as smooth_derivative

#===============================================================================

from beziers.cubicbezier import CubicBezier
from beziers.point import Point

#===============================================================================

hermite2bezier = [[3, 0, 0, 0],
                  [3, 0, 1, 0],
                  [0, 3, 0, -1],
                  [0, 3, 0, 0]]

#===============================================================================

class Connectivity(object):
    def __init__(self, id: str, scaffold, derivatives, location):
        self.__id = id
        self.__scaffold = scaffold
        self.__derivatives = derivatives
        self.__current_offset = None
        self.__region = self.__scaffold.get_region()
        self.__evaluated_coordinates = []
        self.__neuron_description = None
        self.__neuron_line_scaffold = None
        self.__neuron_line_beziers = None
        self.__evaluate(location)

    def __evaluate(self, location):
    #==============================
        field_module = self.__region.getFieldmodule()
        with ChangeManager(field_module):
            field = field_module.findFieldByName("coordinates")
            cache = field_module.createFieldcache()
            mesh = field_module.findMeshByDimension(2)
            xi = location
            element_iter = mesh.createElementiterator()
            element = element_iter.next()
            size = element.getMesh().getSize()
            while element.isValid():
                cache.setMeshLocation(element, [xi, 0.])
                result, evaluated_coordinates = field.evaluateReal(cache, 2)
                assert result == ZINC_OK, f'mapmaker.routing: Could not evaluate neuron {self.__id} location'
                self.__evaluated_coordinates.append(evaluated_coordinates)
                if element.getIdentifier() == size:
                    cache.setMeshLocation(element, [xi, 1.])
                    result, evaluated_coordinates = field.evaluateReal(cache, 2)
                    assert result == ZINC_OK, f'mapmaker.routing: Could not evaluate neuron {self.__id} location'
                    self.__evaluated_coordinates.append(evaluated_coordinates)
                element = element_iter.next()
        self.__generate_neuron_path(size)

    def __generate_neuron_path(self, size):
    #======================================
        self.__neuron_description = {'id': self.__id,
                                     'node coordinates': self.__evaluated_coordinates,
                                     'node derivatives': self.__derivatives,
                                     'number of elements': size}
        neuron = NeuronPath(self.__neuron_description)
        self.__neuron_line_scaffold = neuron.get_scaffold()
        self.__neuron_line_beziers = self.__hermite_to_beziers()

    def __hermite_to_beziers(self):
    #==============================
        beziers = []
        for (p1, p2), (d1, d2) in zip(pairwise(self.__evaluated_coordinates), pairwise(self.__derivatives)):
            b0 = p1
            b1 = mult(add(mult(p1, 3), d1), 1 / 3)
            b2 = mult(sub(mult(p2, 3), d2), 1 / 3)
            b3 = p2
            beziers.append(CubicBezier(Point(*b0), Point(*b1), Point(*b2), Point(*b3)))
        return beziers

    def get_neuron_description(self):
    #================================
        return self.__neuron_description

    def get_neuron_line_beziers(self):
    #=================================
        return self.__neuron_line_beziers

    def get_neuron_line_scaffold(self):
    #==================================
        return self.__neuron_line_scaffold

#===============================================================================

class NeuronPath(object):
    def __init__(self, description):
        self.__scaffold1d = Scaffold1dPath(description)
        self.__settings = description
        self.__scaffold1d.generate()

    def get_scaffold(self):
    #======================
        return self.__scaffold1d

#===============================================================================
