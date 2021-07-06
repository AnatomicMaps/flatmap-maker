# ===============================================================================
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
# ===============================================================================

from opencmiss.utils.zinc.field import findOrCreateFieldCoordinates
from opencmiss.zinc.element import Element, Elementbasis
from opencmiss.zinc.field import Field
from opencmiss.zinc.node import Node
from opencmiss.zinc.context import Context

# ===============================================================================


class Scaffold2dPath(object):

    def __init__(self, options: dict):
        self.__context = Context('2D-Path')
        self.__region = self.__context.getDefaultRegion()
        self.__options = options

    def get_context(self):
        return self.__context

    def get_region(self):
        return self.__region

    def generate_mesh(self):
        coordinate_dimensions = 2
        elements_count = self.__options['Number of elements']
        node_coordinates = self.__options['Node coordinates']
        node_derivatives1 = self.__options['Node derivatives1']
        node_derivatives2 = self.__options['Node derivatives2']*2

        fieldmodule = self.__region.getFieldmodule()
        fieldmodule.beginChange()

        fieldmodule.beginChange()
        coordinates = findOrCreateFieldCoordinates(fieldmodule, components_count=coordinate_dimensions)
        cache = fieldmodule.createFieldcache()

        nodes = fieldmodule.findNodesetByFieldDomainType(Field.DOMAIN_TYPE_NODES)
        node_template = nodes.createNodetemplate()
        node_template.defineField(coordinates)
        node_template.setValueNumberOfVersions(coordinates, -1, Node.VALUE_LABEL_VALUE, 1)
        node_template.setValueNumberOfVersions(coordinates, -1, Node.VALUE_LABEL_D_DS1, 1)
        node_template.setValueNumberOfVersions(coordinates, -1, Node.VALUE_LABEL_D_DS2, 1)

        mesh = fieldmodule.findMeshByDimension(2)
        bicubic_hermite_basis = fieldmodule.createElementbasis(2, Elementbasis.FUNCTION_TYPE_CUBIC_HERMITE)
        eft = mesh.createElementfieldtemplate(bicubic_hermite_basis)
        for n in range(4):
            eft.setFunctionNumberOfTerms(n * 4 + 4, 0)
        element_template = mesh.createElementtemplate()
        element_template.setElementShapeType(Element.SHAPE_TYPE_SQUARE)
        result = element_template.defineField(coordinates, -1, eft)

        cache = fieldmodule.createFieldcache()

        #################
        # Create nodes
        #################

        node_identifier = 1

        for n in range(len(node_coordinates)):
            node = nodes.createNode(node_identifier, node_template)
            cache.setNode(node)
            x = node_coordinates[n]
            d2 = node_derivatives2[n]

            if n % 2 == 0:
                d1 = [-i for i in node_derivatives1[n]]
            else:
                d1 = node_derivatives1[n]

            coordinates.setNodeParameters(cache, -1, Node.VALUE_LABEL_VALUE, 1, x)
            coordinates.setNodeParameters(cache, -1, Node.VALUE_LABEL_D_DS1, 1, d1)
            coordinates.setNodeParameters(cache, -1, Node.VALUE_LABEL_D_DS2, 1, d2)
            node_identifier = node_identifier + 1

        #################
        # Create elements
        #################

        element_identifier = 1
        no2 = elements_count - 3
        for e2 in range(1):
            for e1 in range(elements_count):
                element = mesh.createElement(element_identifier, element_template)
                bni = e1 * no2 + e2 + 1
                node_identifiers = [bni, bni + 1, bni + no2, bni + no2 + 1]
                result = element.setNodesByIdentifier(eft, node_identifiers)
                element_identifier = element_identifier + 1

        fieldmodule.defineAllFaces()
        fieldmodule.endChange()

    def write(self, filename: str):
        self.__region.writeFile(filename)
