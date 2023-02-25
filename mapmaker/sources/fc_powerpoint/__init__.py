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

from .components import FCShape, CD_CLASS, FC_CLASS, FC_KIND
from .components import ORGAN_COLOUR, NERVE_FEATURE_KINDS
from .components import VASCULAR_KINDS, VASCULAR_REGION_COLOUR

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
        self.__shapes_by_id: dict[str, FCShape] = {
            SLIDE_LAYER_ID: FCShape(Shape(SHAPE_TYPE.LAYER, SLIDE_LAYER_ID, self.geometry, {'name': source_id}))
        }
        self.__connections: list[FCShape] = []
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
        self.__classify_shapes()

        if annotator is not None:
            self.__add_annotation(annotator)

        # Add shapes to the filter if we are processing a base map, or
        # exclude them from the layer because they are similar to those
        # in the base map
        for shape in self.shapes.flatten(skip=1):
            if self.__shape_filter is not None:
                if self.kind == 'base':
                    self.__shape_filter.add_shape(shape)
                elif self.kind == 'layer':
                    self.__shape_filter.filter(shape)

            if shape.id in self.__systems:
                shape.properties.pop('name', None)   # We don't want System tooltips...
                shape.properties.pop('label', None)  # We don't want System tooltips...
    def __add_parent(self, fc_shape: FCShape, parent: FCShape):
    #==========================================================
        fc_shape.parents.append(parent)
        parent.children.append(fc_shape)

    def __classify_shapes(self):
    #==============================
        # First extract shape geometries and create a spatial index
        # so we can find their containment hierarchy
        shape_ids = {}     # id(geometry) --> shape.id
        geometries = []
        outer_geometry = shapely.prepared.prep(self.geometry)
        for shape in self.shapes.flatten(skip=1):
            geometry = shape.geometry
            if shape.type == SHAPE_TYPE.FEATURE and 'Polygon' in geometry.geom_type:
                # We are only interested in features actually on the slide that are
                # either components or connectors
                if outer_geometry.contains(geometry):
                    fc_shape = FCShape(shape)
                    if fc_shape.cd_class in [CD_CLASS.COMPONENT, CD_CLASS.CONNECTOR]:
                        self.__shapes_by_id[shape.id] = fc_shape
                        shape_ids[id(geometry)] = shape.id
                        geometries.append(geometry)
            elif shape.type == SHAPE_TYPE.CONNECTION:
                self.__connections.append(FCShape(shape))

        # Spatial index to find component containment hierarchy
        idx = shapely.strtree.STRtree(geometries)

        # We now identify systems and for non-system features (both components and connectors)
        # find features which overlap them
        non_system_overlapping_features = {}
        for shape_id, fc_shape in self.__shapes_by_id.items():
            # Do we need a better way of detecting systems??
            if (fc_shape.cd_class == CD_CLASS.COMPONENT
            and len(fc_shape.name) > 6 and fc_shape.name == fc_shape.name.upper()):
                fc_shape.fc_class = FC_CLASS.SYSTEM
                self.__systems.add(shape_id)
                self.__add_parent(fc_shape, self.__shapes_by_id[SLIDE_LAYER_ID])
            elif fc_shape.cd_class in [CD_CLASS.COMPONENT, CD_CLASS.CONNECTOR]:
                # STRtree query returns geometries whose bounding box intersects the shape's bounding box
                intersecting_geometries: list[int] = [id for id in idx.query(fc_shape.geometry)
                                                        if not fc_shape.geometry.contains(geometries[id])
                                                        and geometries[id].intersection(fc_shape.geometry).area  # type: ignore
                                                            >= MIN_OVERLAP_FRACTION*fc_shape.geometry.area]
                # Sort overlapping geometries by area, smallest item first, which is the immediate  parent of the shape
                overlaps = [shape_ids[i[0]]
                                for i in sorted([(id(geometries[index]), geometries[index].area)
                                                    for index in intersecting_geometries],
                                                key = lambda x: x[1])
                           ]
                non_system_overlapping_features[shape_id] = overlaps

        # Organs are components with ORGAN_COLOUR colour and are contained in at
        # least one system
        for shape_id, overlaps in non_system_overlapping_features.items():
            fc_shape = self.__shapes_by_id[shape_id]
            if (fc_shape.cd_class == CD_CLASS.COMPONENT
            and ORGAN_COLOUR.matches(fc_shape.colour)):
                fc_shape.fc_class = FC_CLASS.ORGAN
                self.__organs.add(shape_id)
                for overlapping_id in overlaps:
                    if (parent := self.__shapes_by_id[overlapping_id]).fc_class == FC_CLASS.SYSTEM:
                        self.__add_parent(fc_shape, parent)
                if len(fc_shape.parents) == 0:
                    log.error(f'An organ must be in at least one system: {fc_shape}')
                if fc_shape.name == '':
                    log.error(f'An organ must have a name: {fc_shape}')

        # Components within an organ are either vascular regions or FTUs
        for shape_id, overlaps in non_system_overlapping_features.items():
            fc_shape = self.__shapes_by_id[shape_id]
            if (fc_shape.cd_class == CD_CLASS.COMPONENT
            and len(overlaps) and (parent := self.__shapes_by_id[overlaps[0]]).id in self.__organs):
                if VASCULAR_REGION_COLOUR.matches(fc_shape.colour):
                    fc_shape.fc_class = FC_CLASS.VASCULAR
                    fc_shape.fc_kind = FC_KIND.VASCULAR_REGION
                    fc_shape.properties['name'] = 'vr...' ## <<<<<<<<<<<<<<<<< TEMP
                    fc_shape.properties['label'] = 'vr...' ## <<<<<<<<<<<<<<<<< TEMP
                    self.__add_parent(fc_shape, parent)
                else:
                    fc_shape.fc_class = FC_CLASS.FTU
                # Vascular  regions and FTUs can only be in the one organ
                index = 1
                while index < len(overlaps):
                    if (parent := self.__shapes_by_id[overlaps[index]]).id in self.__organs:
                        log.error(f'FTUs and regions can only be in a single organ: {fc_shape}')
                        break
                    index += 1

        # Remaining named components should be either neural or vascular
        for shape_id, overlaps in non_system_overlapping_features.items():
            fc_shape = self.__shapes_by_id[shape_id]
            if (fc_shape.cd_class == CD_CLASS.COMPONENT
            and fc_shape.fc_class == FC_CLASS.UNKNOWN
            and fc_shape.name != ''):
                if (kind := NERVE_FEATURE_KINDS.lookup(fc_shape.colour)) is not None:
                    fc_shape.fc_class = FC_CLASS.NEURAL
                    self.__nerves.add(shape_id)
                    fc_shape.description = kind
                elif (kind := VASCULAR_KINDS.lookup(fc_shape.colour)) is not None:
                    if fc_shape.name == 'Basilar':
                        print(fc_shape.shape)
                    fc_shape.fc_class = FC_CLASS.VASCULAR
                    fc_shape.fc_kind = kind

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

    def __add_annotation(self, annotator: Annotator):
    #================================================
        # Called after shapes have been extracted
        for id in self.__systems:
            if (name := self.__shapes_by_id[id].name) != '':
                annotation = annotator.get_system_annotation(name, self.source_id)
                self.__shapes_by_id[id].properties.update(annotation.properties)
        for id in self.__nerves:
            if (name := self.__shapes_by_id[id].name) != '':
                annotation = annotator.get_nerve_annotation(name, self.source_id)
                self.__shapes_by_id[id].properties.update(annotation.properties)
        for id in self.__organs:
            annotation = annotator.get_organ_annotation(self.__shapes_by_id[id].name, self.source_id,
                tuple(parent.name for parent in self.__shapes_by_id[id].parents
                    if parent.fc_class == FC_CLASS.SYSTEM)
                )
            ## It is shape properties that need updating...
            self.__shapes_by_id[id].properties.update(annotation.properties)
        for fc_shape in self.__shapes_by_id.values():
            self.__annotate_component(fc_shape, annotator)

    def __annotate_component(self, fc_shape: FCShape,  annotator: Annotator):
    #=============================================================================
        if (fc_shape.name != ''
        and (annotation := annotator.find_annotation(fc_shape.name)) is None):
            organ = None
            for parent in fc_shape.parents:
                if parent.id in self.__organ_ids:
                    # Could have multiple parents
                    organ = parent
                    break
            if organ is not None:
                if len(fc_shape.parents) > 1:
                    log.warning(f'FTU {fc_shape} in multiple organs')
                else:
                    annotation = annotator.find_ftu_by_names(organ.name, fc_shape.name)
                    if annotation is None:
                        annotation = annotator.get_ftu_annotation(organ.name, fc_shape.name, self.source_id)
                    fc_shape.properties.update(annotation.properties)

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
