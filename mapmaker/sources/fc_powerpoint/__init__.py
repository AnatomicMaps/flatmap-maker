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

from .components import Annotation, Component, Connection, Connector, FCShape
from .components import CD_CLASS, FC_CLASS, FC_KIND
from .components import HYPERLINK_KINDS, HYPERLINK_LABELS
from .components import NERVE_FEATURE_KINDS, NEURON_KINDS
from .components import ORGAN_COLOUR, ORGAN_KINDS
from .components import VASCULAR_KINDS, VASCULAR_REGION_COLOUR, VASCULAR_VESSEL_KINDS
from .connections import ConnectionClassifier

from .sckan import SckanNeuronPopulations

#===============================================================================

# Shapes smaller than this are assumed to be connectors or hyperlinks
MAX_CONNECTOR_AREA = 120000000      # metres**2

MIN_OVERLAP_FRACTION = 0.2  # Smaller geometry and >= 20% common area ==> containment
                            # e.g. `cochlear nuclei` and `pons`

MAX_FTU_OUTSIDE = 0.1       # An FTU should mainly be inside its organ

def contained_in(inside_shape, outer_shape, outside_fraction=0.0):
    if outside_fraction== 0.0:
        return outer_shape.geometry.contains(inside_shape.geometry)
    excess = inside_shape.geometry.difference(outer_shape.geometry)
    return excess.area <= outside_fraction*inside_shape.geometry.area

#===============================================================================

class FCPowerpointSource(PowerpointSource):
    def __init__(self, flatmap, id, source_href, source_kind, source_range=None,
                 shape_filter: Optional[ShapeFilter]=None):
        super().__init__(flatmap, id, source_href, source_kind=source_kind,
                         source_range=source_range,
                         SlideClass=FCSlide, slide_options=dict(
                            shape_filter=shape_filter,
                            sckan_neurons=SckanNeuronPopulations()
                        ))

#===============================================================================

# The outer geometry of the slide
SLIDE_LAYER_ID = 'SLIDE-LAYER-ID'

class FCSlide(Slide):
    def __init__(self, source_id: str, kind: str, index: int, pptx_slide: PptxSlide, theme: ColourTheme,
                 bounds: MapBounds, transform: Transform, shape_filter: Optional[ShapeFilter]=None,
                 sckan_neurons: Optional[SckanNeuronPopulations]=None):
        super().__init__(source_id, kind, index, pptx_slide, theme, bounds, transform)
        self.__shape_filter = shape_filter
        self.__sckan_neurons = sckan_neurons
        self.__shapes_by_id: dict[str, FCShape] = {
            SLIDE_LAYER_ID: Component(Shape(SHAPE_TYPE.LAYER, SLIDE_LAYER_ID, self.geometry, {'name': source_id}))
        }
        self.__connection_classifier = ConnectionClassifier()
        self.__connections = []
        self.__organ_ids: set[str] = set()
        self.__nerve_ids: set[str] = set()
        self.__system_ids: set[str] = set()

    def process(self, annotator: Optional[Annotator]=None):
    #======================================================
        super().process(annotator)
        self.__extract_shapes(annotator)
        self.__add_connections()
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

            if shape.id in self.__system_ids:
                shape.properties.pop('name', None)   # We don't want System tooltips...
                shape.properties.pop('label', None)  # We don't want System tooltips...


    def __classify_shapes(self):
    #===========================
        # First extract shape geometries and create a spatial index
        # so we can find their containment hierarchy

        geometry_to_shape = {}
        geometries = []
        def add_shape_geometry(fc_shape):
            geometry_to_shape[id(geometry)] = fc_shape
            geometries.append(geometry)

        outer_geometry = shapely.prepared.prep(self.geometry)
        for shape in self.shapes.flatten(skip=1):
            geometry = shape.geometry
            if shape.type == SHAPE_TYPE.FEATURE and 'Polygon' in geometry.geom_type:
                # We are only interested in features actually on the slide that are
                # either components or connectors
                if outer_geometry.contains(geometry):
                    shape_kind = shape.properties.get('shape-kind', '')
                    if shape.colour is None:
                        if shape.label != '':
                            fc_shape = Annotation(shape, FC_CLASS.DESCRIPTION)
                    elif (geometry.area < MAX_CONNECTOR_AREA):
                        fc_shape = None
                        if shape_kind.startswith('star'):
                            if (kind := HYPERLINK_KINDS.lookup(shape.colour)) is not None:
                                fc_shape = Annotation(shape, FC_CLASS.HYPERLINK)
                                fc_shape.fc_kind = kind
                        else:
                            fc_shape = Connector(shape)
                        if fc_shape is not None:
                            self.__shapes_by_id[shape.id] = fc_shape
                            add_shape_geometry(fc_shape)
                    else:
                        fc_shape = Component(shape)
                        self.__shapes_by_id[shape.id] = fc_shape
                        add_shape_geometry(fc_shape)
            elif shape.type == SHAPE_TYPE.CONNECTION:
                self.__connections.append(Connection(shape))

        # Spatial index to find component containment hierarchy
        idx = shapely.strtree.STRtree(geometries)

        # We now identify systems and for non-system features (both components and connectors)
        # find features which overlap them
        non_system_components = []
        connectors = []
        hyperlinks = []
        for shape_id, fc_shape in self.__shapes_by_id.items():
            # Do we need a better way of detecting systems??
            if (isinstance(fc_shape, Component)
            and len(fc_shape.name) > 6 and fc_shape.name == fc_shape.name.upper()):
                fc_shape.fc_class = FC_CLASS.SYSTEM
                fc_shape.parents.append(self.__shapes_by_id[SLIDE_LAYER_ID])    # type: ignore
                self.__shapes_by_id[SLIDE_LAYER_ID].children.append(fc_shape)   # type: ignore
                self.__system_ids.add(shape_id)
            else:       # Component, Connector, or Annotation (Hyperlink)
                # STRtree query returns geometries whose bounding box intersects the shape's bounding box
                intersecting_geometries: list[int] = [id for id in idx.query(fc_shape.geometry)
                                                        if not fc_shape.geometry.contains(geometries[id])
                                                        and geometries[id].intersection(fc_shape.geometry).area  # type: ignore
                                                            >= MIN_OVERLAP_FRACTION*fc_shape.geometry.area]
                # Set the shape's parents, ordered by the area of its overlapping geometries,
                # with the smallest (immediate) parent first
                containing_ids_area_order = [id_area[0]
                    for id_area in sorted([(id(geometries[index]), geometries[index].area)
                        for index in intersecting_geometries], key = lambda x: x[1])]
                if isinstance(fc_shape, Component):
                    for shape_id in containing_ids_area_order:
                        parent = geometry_to_shape[shape_id]
                        fc_shape.parents.append(parent)
                        parent.children.append(fc_shape)
                    non_system_components.append(fc_shape)
                elif isinstance(fc_shape, Connector):
                    parent = geometry_to_shape[containing_ids_area_order[0]]
                    fc_shape.parent = parent
                    parent.children.append(fc_shape)
                    connectors.append(fc_shape)
                elif isinstance(fc_shape, Annotation):
                    fc_shape.parent = geometry_to_shape[containing_ids_area_order[0]]
                    hyperlinks.append(fc_shape)

        # Classify connectors that are unambigously neural connectors
        for connector in connectors:
            if (connector.shape_kind == 'rect'
            and (neuron_kind := NEURON_KINDS.lookup(connector.colour)) is not None):
                connector.fc_class = FC_CLASS.NEURAL
                connector.fc_kind = FC_KIND.CONNECTOR_PORT
                connector.description = neuron_kind

        # Classify as FTUs those components that have a neural connector port
        # which has the component as their immediate parent
        for fc_shape in non_system_components:
            for child in fc_shape.children:
                if isinstance(child, Connector) and child.fc_kind == FC_KIND.CONNECTOR_PORT:
                    fc_shape.fc_class = FC_CLASS.FTU

        # Organs are components that are contained in at least one system and
        # have ORGAN_COLOUR colour or contain FTUs
        for fc_shape in non_system_components:
            if fc_shape.fc_class == FC_CLASS.UNKNOWN:
                have_organ = False
                organ_kind = FC_KIND.UNKNOWN
                if (ORGAN_COLOUR.matches(fc_shape.colour)
                 or (organ_kind := ORGAN_KINDS.lookup(fc_shape.colour)) is not None):
                    have_organ = True
                else:
                    for child in fc_shape.children:
                        if (child.fc_class == FC_CLASS.FTU
                        and contained_in(child, fc_shape, MAX_FTU_OUTSIDE)):
                            have_organ = True
                            break
                if have_organ:
                    fc_shape.fc_class = FC_CLASS.ORGAN
                    fc_shape.fc_kind = organ_kind
                    self.__organ_ids.add(fc_shape.id)
                    if fc_shape.name == '':
                        log.error(f'An organ must have a name: {fc_shape}')
                    have_system = False
                    for parent in fc_shape.parents:
                        if parent.fc_class == FC_CLASS.SYSTEM:
                            have_system = True
                            break
                    if not have_system:
                        log.error(f'An organ must be in at least one system: {fc_shape}')

        # Components within an organ are either vascular regions or FTUs
        for fc_shape in non_system_components:
            if (fc_shape.fc_class == FC_CLASS.UNKNOWN
            and len(fc_shape.parents) and (parent := fc_shape.parents[0]).id in self.__organ_ids):
                if VASCULAR_REGION_COLOUR.matches(fc_shape.colour):
                    fc_shape.fc_class = FC_CLASS.VASCULAR
                    fc_shape.fc_kind = FC_KIND.VASCULAR_REGION
                    #fc_shape.properties['name'] = 'vr...' ## <<<<<<<<<<<<<<<<< TEMP
                    #fc_shape.properties['label'] = 'vr...' ## <<<<<<<<<<<<<<<<< TEMP
                else:
                    fc_shape.fc_class = FC_CLASS.FTU
            # Check vascular  regions and FTUs are only in a single organ
            if fc_shape.fc_class in [FC_CLASS.FTU, FC_CLASS.VASCULAR]:
                for parent in fc_shape.parents[1:]:
                    if parent.id in self.__organ_ids:
                        log.error(f'FTUs and regions can only be in a single organ: {fc_shape}')
                        break

        # Remaining named components should be either neural or vascular
        for fc_shape in non_system_components:
            if (fc_shape.fc_class == FC_CLASS.UNKNOWN
            and fc_shape.name != ''):
                if (kind := NERVE_FEATURE_KINDS.lookup(fc_shape.colour)) is not None:
                    fc_shape.fc_class = FC_CLASS.NEURAL
                    self.__nerve_ids.add(fc_shape.id)
                    fc_shape.description = kind
                elif (kind := VASCULAR_VESSEL_KINDS.lookup(fc_shape.colour)) is not None:
                    fc_shape.fc_class = FC_CLASS.VASCULAR
                    fc_shape.fc_kind = kind

            if fc_shape.fc_class == FC_CLASS.UNKNOWN:
                self.__connection_classifier.add_component(fc_shape)

        # Hyperlinks become properties of the feature they are on
        for hyperlink in hyperlinks:
            if (parent := hyperlink.parent) is not None:
                kind = HYPERLINK_LABELS[hyperlink.fc_kind]
                parent.properties[kind] = hyperlink.properties['hyperlink']
                hyperlink.properties['exclude'] = True

        # Classify remaining connectors
        for connector in connectors:
            if connector.fc_class == FC_CLASS.UNKNOWN:
                if connector.shape_kind == 'leftRightArrow':
                    connector.fc_class = FC_CLASS.NEURAL
                    connector.fc_kind = FC_KIND.CONNECTOR_JOINER
                elif connector.parent is not None and connector.parent.fc_class == FC_CLASS.NEURAL:
                    if connector.shape_kind == 'ellipse':
                        if (kind := NEURON_KINDS.lookup(connector.colour)) is not None:
                            connector.fc_class = FC_CLASS.NEURAL
                            connector.fc_kind = FC_KIND.CONNECTOR_NODE
                            connector.description = kind
                    elif connector.shape_kind == 'plus':
                        connector.fc_class = FC_CLASS.NEURAL
                        connector.fc_kind = FC_KIND.CONNECTOR_THROUGH
                elif connector.shape_kind == 'ellipse':
                    if (kind := VASCULAR_KINDS.lookup(connector.colour)) is not None:
                        connector.fc_class = FC_CLASS.VASCULAR
                        connector.fc_kind = FC_KIND.CONNECTOR_NODE
                        connector.description = kind
                    elif (kind := NEURON_KINDS.lookup(connector.colour)) is not None:
                        connector.fc_class = FC_CLASS.NEURAL
                        connector.fc_kind = FC_KIND.CONNECTOR_NODE
                        connector.description = kind
            if connector.fc_class != FC_CLASS.UNKNOWN:
                self.__connection_classifier.add_connector(connector)
            if connector.parent is None:
                log.error(f"Connector doesn't have a parent: {connector}")
                connector.properties['error'] = True

    def __add_annotation(self, annotator: Annotator):
    #================================================
        # Called after shapes have been extracted
        for id in self.__system_ids:
            name = self.__shapes_by_id[id].name
            annotation = annotator.get_system_annotation(name, self.source_id)
            self.__shapes_by_id[id].properties.update(annotation.properties)
        for id in self.__nerve_ids:
            if (name := self.__shapes_by_id[id].name) != '':
                annotation = annotator.get_nerve_annotation(name, self.source_id)
                self.__shapes_by_id[id].properties.update(annotation.properties)
        for id in self.__organ_ids:
            annotation = annotator.get_organ_annotation(self.__shapes_by_id[id].name, self.source_id,
                tuple(parent.name for parent in self.__shapes_by_id[id].parents
                    if parent.fc_class == FC_CLASS.SYSTEM)
                )
            self.__shapes_by_id[id].properties.update(annotation.properties)

        for fc_shape in self.__shapes_by_id.values():
            if (isinstance(fc_shape, Component)
            and fc_shape.id not in self.__system_ids
            and fc_shape.id not in self.__nerve_ids
            and fc_shape.id not in self.__system_ids):
                self.__annotate_component(fc_shape, annotator)

        # go through all connectors and set FTU/organ for them
        for fc_shape in self.__shapes_by_id.values():
            if fc_shape.cd_class == CD_CLASS.CONNECTOR:
                self.__annotate_connector(fc_shape)

    def __annotate_component(self, fc_shape: FCShape, annotator: Annotator):
    #=======================================================================
        if (fc_shape.name != ''
        and (annotation := annotator.find_annotation(fc_shape.name)) is None):
            organs = [parent for parent in fc_shape.parents if parent.fc_class == FC_CLASS.ORGAN]
            if len(organs):
                organ = organs[0]
                annotation = annotator.find_ftu_by_names(organ.name, fc_shape.name)
                if annotation is None:
                    annotation = annotator.get_ftu_annotation(organ.name, fc_shape.name, self.source_id)
                fc_shape.properties.update(annotation.properties)

    def __annotate_connector(self, connector: Connector):
    #====================================================
        labels = []
        models = []
        def set_label(parent):
            label = f'{parent.label[0:1].capitalize()}{parent.label[1:]}'
            if parent.models:
                label += f' ({parent.models})'
                models.append(parent.models)
            labels.append(label)

        if connector.parent is not None:
            set_label(connector.parent)
            if connector.parent.parents:
                set_label(connector.parent.parents[0])
            connector.properties['label'] = '/'.join(labels)
            if len(models):
                connector.properties['parent_models'] = tuple(models)

    def __add_connections(self):
    #===========================
        for connection in self.__connections:
            self.__connection_classifier.add_connection(connection)
            end_labels = []
            end_nodes = []
            for connector_id in connection.connector_ids:
                if (connector := self.__shapes_by_id.get(connector_id)) is not None:
                    if label := connector.properties.get('label', ''):
                        end_labels.append(f'CN: {label[0:1].capitalize()}{label[1:]}')
                    models = connector.properties['component_models'].split('/')
                    if len(models):
                        if len(models) == 1:
                            models.append(None)
                        end_nodes.append(models)
            connection.properties['label'] = '\n'.join(end_labels)

            if self.__sckan_neurons is not None and len(end_nodes) > 1:
                if path_ids := self.__sckan_neurons.find_connection_paths(end_nodes):
                    connection.properties['sckan'] = tuple(path_ids)
                    end_labels.extend(path_ids)
            connection.properties['label'] = '\n'.join(end_labels)

#===============================================================================
