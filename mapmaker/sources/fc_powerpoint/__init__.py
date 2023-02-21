#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2019 - 2023  David Brooks
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

from pptx.slide import Slide as PptxSlide

import shapely.geometry
import shapely.prepared
import shapely.strtree

#===============================================================================

from mapmaker.annotation import Annotator
from mapmaker.geometry import Transform
from mapmaker.sources.shape import Shape, SHAPE_TYPE
from mapmaker.sources import MapBounds
from mapmaker.utils import log

from ..powerpoint import PowerpointSource, Slide
from ..shapefilter import ShapeFilter
from ..powerpoint.colour import ColourTheme

#===============================================================================

from .components import FCComponent, FC_CLASS, FC_TYPE, HYPERLINK_LABELS
from .connections import Connections

#===============================================================================

MIN_OVERLAP_FRACTION = 0.2  # Smaller geometry and >= 20% common area ==> containment
                            # e.g. `cochlear nuclei` and `pons`

#===============================================================================

class FCPowerpointSource(PowerpointSource):
    def __init__(self, flatmap, id, source_href, source_kind, source_range=None,
                 shape_filter: Optional[ShapeFilter]=None):
        super().__init__(flatmap, id, source_href, source_kind=source_kind,
                         source_range=source_range, shape_filter=shape_filter,
                         SlideClass=FCSlide)

#===============================================================================

# The outer geometry of the slide
SLIDE_LAYER_ID = 'SLIDE-LAYER-ID'

class FCSlide(Slide):
    def __init__(self, source_id: str, kind: str, index: int, pptx_slide: PptxSlide, theme: ColourTheme,
                 bounds: MapBounds, transform: Transform, shape_filter: Optional[ShapeFilter]=None):
        super().__init__(source_id, kind, index, pptx_slide, theme, bounds, transform)
        self.__shape_filter = shape_filter
        self.__components: dict[str, FCComponent] = {
            SLIDE_LAYER_ID: FCComponent(Shape(SHAPE_TYPE.LAYER, SLIDE_LAYER_ID, self.geometry))
        }
        self.__connections = Connections()
        self.__organs: set[str] = set()
        self.__nerves: set[str] = set()
        self.__systems: set[str] = set()

    def process(self, annotator: Optional[Annotator]=None):
    #======================================================
        super().process(annotator)
        self.__extract_shapes(annotator)
        self.__label_connections()
        return self.shapes

    def __extract_shapes(self, annotator: Optional[Annotator]):
    #==========================================================
        self.__extract_components()

        if annotator is not None:
            self.__add_annotation(annotator)

        for shape in self.shapes.flatten(skip=1):
            # Add the shape to the filter if we are processing a base map,
            # or exclude it from the layer because it is similar to those
            # in the base map
            if self.__shape_filter is not None:
                if self.kind == 'base':
                    self.__shape_filter.add_shape(shape)
                elif self.kind == 'layer':
                    self.__shape_filter.filter(shape)

            if shape.id in self.__systems:
                shape.properties.pop('name', None)   # We don't want System tooltips...
                shape.properties.pop('label', None)  # We don't want System tooltips...

    def __extract_components(self):
    #==============================
        # First extract shape geometries and create a spatial index
        # so we can find their containment hierarchy
        component_ids = {id(self.geometry): SLIDE_LAYER_ID}     # id(geometry) --> shape.id
        geometries = [self.geometry]
        outer_geometry = shapely.prepared.prep(self.geometry)
        for shape in self.shapes.flatten(skip=1):
            geometry = shape.geometry
            if shape.type == SHAPE_TYPE.FEATURE and 'Polygon' in geometry.geom_type:
                # We are only interested in features actually on the slide
                if outer_geometry.contains(geometry):
                    component = FCComponent(shape)
                    self.__components[component.id] = component
                    if component.fc_type == FC_TYPE.SYSTEM:
                        self.__systems.add(component.id)
                        self.__set_relationships(component, SLIDE_LAYER_ID)
                    elif component.fc_type == FC_TYPE.NERVE:
                        self.__nerves.add(component.id)
                    geometries.append(geometry)
                    component_ids[id(geometry)] = component.id
            elif shape.type == SHAPE_TYPE.CONNECTION:
                component = FCComponent(shape)
                self.__components[component.id] = component

        # Spatial index to find component containment hierarchy
        idx = shapely.strtree.STRtree(geometries)

        # We use two passes to find a component's spatial order, first
        # identifying SYSTEMs and then the features within a system.
        non_system_features = {}
        for component_id, component in self.__components.items():
            if (component.fc_type not in [FC_TYPE.LAYER, FC_TYPE.SYSTEM]  # not entire slide nor system
            and component.shape.type == SHAPE_TYPE.FEATURE):
                # Geometries that intersect the component
                intersecting_geometries: list[int] = idx.query(component.geometry)
                # Sort geometries by area, smallest item first
                overlaps = [component_ids[i[0]]
                                for i in sorted([(id(geometries[index]), geometries[index].area)
                                                    for index in intersecting_geometries],
                                                key = lambda x: x[1])
                           ]
                non_system_features[component_id] = overlaps

        # Organs are named components contained in a system
        for component_id, overlaps in non_system_features.items():
            component = self.__components[component_id]
            if component.name and component.fc_type == FC_TYPE.UNKNOWN:
                parent_index = overlaps.index(component_id) + 1
                while (parent_index < len(overlaps)
                   and self.__components[overlaps[parent_index]].label == SLIDE_LAYER_ID):
                    parent_index += 1
                parent = self.__components[overlaps[parent_index]]
                if (parent.fc_type == FC_TYPE.SYSTEM
                and parent.geometry.intersection(component.geometry).area
                        >= MIN_OVERLAP_FRACTION*component.geometry.area):
                    component.fc_type = FC_TYPE.ORGAN
                    self.__organs.add(component_id)
                    self.__set_relationships(component, parent.id)
                    # An organ can be in more than one system so find them all
                    parent_index += 1
                    while parent_index < len(overlaps):
                        parent = self.__components[overlaps[parent_index]]
                        if (parent.fc_type == FC_TYPE.SYSTEM
                        and parent.geometry.intersection(component.geometry).area
                                >= MIN_OVERLAP_FRACTION*component.geometry.area):
                            self.__set_relationships(component, parent.id)
                        parent_index += 1

        # Set geometric parent relationship for remaining components
        for component_id, overlaps in non_system_features.items():
            component = self.__components[component_id]
            if component.fc_type != FC_TYPE.ORGAN:
                parent_index = overlaps.index(component_id) + 1
                while parent_index < len(overlaps):
                    parent_geometry = self.__components[overlaps[parent_index]].geometry
                    if (parent_geometry is not None
                    and component.geometry is not None
                    and parent_geometry.intersection(component.geometry).area
                        >= MIN_OVERLAP_FRACTION*component.geometry.area):
                        break
                    parent_index += 1
                parent_id = overlaps[parent_index]
                self.__set_relationships(component, parent_id)

                # Unknown named components contained in an organ are FTUs
                if (component.name != ''
                and component.fc_type == FC_TYPE.UNKNOWN
                and parent_id in self.__organs):
                    component.fc_type = FC_TYPE.FTU
                    if len(component.parents) != 1:
                        log.error(f'FTU can only be in a single organ: {component}')

        # Find FC parents of CONNECTORs and add them to the Connections object
        for component in self.__components.values():
            if component.fc_type == FC_TYPE.CONNECTOR:
                if component.fc_class == FC_CLASS.PORT:
                    if (len(component.parents) != 1
                     or (parent := self.__components[component.parents[0]]).fc_type != FC_TYPE.FTU):
                        log.error(f'A connector port must be in a single FTU: {component}')
                    else:
                        component.properties['fc-parent'] = parent.id
                elif component.fc_class in [FC_CLASS.NODE, FC_CLASS.THROUGH]:
                    if len(component.parents) != 1:
                        log.error(f'A neuron node must be on a single feature: {component}')
                    else:
                        component.properties['fc-parent'] = component.parents[0]
                elif component.fc_class == FC_CLASS.JOIN:
                    component.properties['exclude'] = True
            self.__connections.add_component(component)

        # We now have added all CONNECTORs so let the Connections object know
        self.__connections.end_components()
        for component in self.__components.values():
            if component.fc_type == FC_TYPE.CONNECTION:
                # Add an actual connection to the set of Connections
                self.__connections.add_connection(component)
            elif component.fc_type == FC_TYPE.HYPERLINK:
                # Set hyperlink labels
                component.properties['label'] = HYPERLINK_LABELS.get(component.fc_class, component.label)

    def __set_relationships(self, component, parent_id):
    #===================================================
        component.parents.append(parent_id)
        self.__components[parent_id].children.append(component.id)

    def __add_annotation(self, annotator: Annotator):
    #================================================
        # Called after shapes have been extracted
        for id in self.__systems:
            if (name := self.__components[id].name) != '':
                annotation = annotator.get_system_annotation(name, self.source_id)
                self.__components[id].properties.update(annotation.properties)
        for id in self.__nerves:
            if (name := self.__components[id].name) != '':
                annotation = annotator.get_nerve_annotation(name, self.source_id)
                self.__components[id].properties.update(annotation.properties)
        for id in self.__organs:
            annotation = annotator.get_organ_annotation(self.__components[id].name, self.source_id,
                tuple(self.__components[system_id].name
                    for system_id in self.__components[id].parents if system_id != '')
                )
            ## It is shape properties that need updating...
            self.__components[id].properties.update(annotation.properties)

        for component in self.__components.values():
            self.__annotate_component(component, annotator)

    def __annotate_component(self, component: FCComponent,  annotator: Annotator):
    #=============================================================================
        if (component.name != ''
        and (annotation := annotator.find_annotation(component.name)) is None):
            organ_id = None
            for parent in component.parents:
                if parent in self.__organs:
                    # Can have multiple parents
                    organ_id = parent
                    break
            if organ_id is not None:
                if len(component.parents) > 1:
                    log.warning(f'FTU {component} in multiple organs')
                else:
                    organ_name = self.__components[organ_id].name
                    annotation = annotator.find_ftu_by_names(organ_name, component.name)
                    if annotation is None:
                        annotation = annotator.get_ftu_annotation(self.__components[organ_id].name,
                                                                  component.name, self.source_id)
                    component.properties.update(annotation.properties)

    def __label_connections(self):
    #=============================
        for connection_dict in self.__connections.as_dict():
            connection = self.__components[connection_dict['id']]
            end_labels = []
            for end_id in connection_dict['ends']:
                if (end_component := self.__components.get(end_id)) is not None:
                    if (parent_id := end_component.properties.get('fc-parent')) is not None:
                        parent = self.__components[parent_id]
                        end_labels.append(f'CN: {parent.label[0:1].capitalize()}{parent.label[1:]}'
                                       + (f' ({parent.models})' if parent.models else ''))
            connection.properties['label'] = '\n'.join(end_labels)

#===============================================================================
