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

from __future__ import annotations
from io import BytesIO, StringIO

#===============================================================================

from mapmaker.flatmap.feature import Feature
from mapmaker.flatmap.layers import FEATURES_TILE_LAYER, MapLayer
from mapmaker.sources import PATHWAYS_TILE_LAYER
from mapmaker.settings import settings
from mapmaker.utils import log, pathlib_path, TreeList

from .. import MapSource, RasterSource
from ..fc_powerpoint.components import CD_CLASS

from .powerpoint import Powerpoint, Slide
from .svgutils import SvgFromShapes

# Exports
from .powerpoint import Slide

#===============================================================================

def set_relationship_property(feature, property, relatives):
    geojson_ids = set(s.global_shape.geojson_id for s in relatives if s.global_shape.geojson_id)
    if feature.has_property(property):
        feature.get_property(property).update(geojson_ids)
    else:
        feature.set_property(property, geojson_ids)

#===============================================================================

class PowerpointLayer(MapLayer):
    def __init__(self, source: PowerpointSource, id: str, slide: Slide, slide_number: int):
        if source.source_range is None:
            exported = slide_number == 1
        else:
            exported = slide_number == source.source_range[0]
        super().__init__(id, source, exported=exported)
        self.__slide = slide
        self.__slide_number = slide_number

    @property
    def slide(self):
        return self.__slide

    @property
    def slide_number(self):
        return self.__slide_number

    def process(self):
    #=================
        shapes = self.__slide.process(self.flatmap.annotator)

        features = self.__process_shape_list(shapes)
        self.add_features('Slide', features, outermost=True)

        if settings.get('functionalConnectivity', False):
            for feature in self.features:
                if feature.get_property('cd-class') == CD_CLASS.CONNECTION:
                    # Map neuron path class to viewer path kind/type
                    feature.set_property('tile-layer', PATHWAYS_TILE_LAYER)
                    for system_id in feature.get_property('system-ids', []):
                        if (system_feature := self.flatmap.get_feature(system_id)) is not None:
                            if (path_ids := system_feature.get_property('path-ids')) is not None:
                                if feature.id not in path_ids:
                                    path_ids.append(feature.id)
                            else:
                                system_feature.set_property('path-ids', [feature.id])

                    if (settings.get('authoring', False)
                    and (feature.has_property('error')
                      or feature.has_property('warning'))):
                        feature.set_property('kind', 'error')
                    node_ids = [node.geojson_id for node in
                                    [self.flatmap.get_feature(node_id)
                                        for node_id in feature.get_property('node-ids', [])]
                                    if node is not None]
                    self.source.flatmap.connection_set.add(
                        feature.id,                             # type:ignore (all FC features have an id)
                        feature.get_property('kind'),
                        feature.geojson_id,
                        node_ids)
            # Pass parent/child containment to the viewer
            for shape in shapes.flatten(skip=1):
                feature = shape.global_shape.get_property('feature') if shape.filtered else shape.get_property('feature')
                if feature is not None:
                    set_relationship_property(feature, 'children', shape.children)
                    set_relationship_property(feature, 'parents', shape.parents)

    def __process_shape_list(self, shapes: TreeList) -> list[Feature]:
    #=================================================================
        features = []
        for shape in shapes[1:]:
            if isinstance(shape, TreeList):
                group_features = self.__process_shape_list(shape)
                grouped_feature = self.add_features('Group', group_features)
                if grouped_feature is not None:
                    features.append(grouped_feature)
            else:
                properties = shape.properties
                self.source.check_markup_errors(properties)
                if 'tile-layer' not in properties:
                    properties['tile-layer'] = FEATURES_TILE_LAYER   # Passed through to map viewer
                if 'invisible' in properties:
                    pass
                elif 'path' in properties:
                    pass
                elif not properties.get('exclude', False):
                    feature = self.flatmap.new_feature(shape.geometry, properties)
                    features.append(feature)
                    shape.geojson_id = feature.geojson_id
                    shape.set_property('feature', feature)
        return features

#===============================================================================

class PowerpointSource(MapSource):
    def __init__(self, flatmap, id, href, kind='slides', source_range=None,
                 SlideClass=Slide, slide_options=None):
        super().__init__(flatmap, id, href, kind, source_range=source_range)
        self.__powerpoint = Powerpoint(flatmap, self, SlideClass=SlideClass, slide_options=slide_options)
        self.bounds = self.__powerpoint.bounds   # Sets bounds of MapSource
        self.__slides = self.__powerpoint.slides

    @property
    def transform(self):
        return self.__powerpoint.transform

    def process(self):
    #=================
        if self.source_range is None:
            slide_numbers = range(1, len(self.__slides)+1)
        else:
            slide_numbers = self.source_range
        for slide_number in slide_numbers:
            # Skip slides not in the presentation
            if slide_number < 1 or slide_number >= (len(self.__slides) + 1):
                continue
            slide = self.__slides[slide_number - 1]
            if slide_number == 1 and len(slide_numbers) == 1:
                id = self.id
            else:
                id = f'{self.id}/{slide.id}'
            slide_layer = PowerpointLayer(self, id, slide, slide_number)
            log(f'Slide {slide_number}, {slide_layer.id}')
            if settings.get('saveDrawML'):
                with open(self.flatmap.full_filename(f'{slide_layer.id}.xml'), 'w') as xml:
                    xml.write(slide.pptx_slide.element.xml)
            slide_layer.process()
            self.add_layer(slide_layer)

    def get_raster_source(self):
    #===========================
        if self.kind == 'base':  # Only rasterise base source layer
            return RasterSource('svg', self.get_raster_data)

    def get_raster_data(self):
    #=========================
        svg_maker = SvgFromShapes(self.__powerpoint)
        for slide in self.__powerpoint.slides:
            svg_maker.add_slide(slide, base_slide=(self.kind=='base'))   ## Options

        # slides to SVG is simply slide_to_svg for all slides in the PPT, using the GLOBAL svg shape filter
        # Do we need a local, secondary filter??
        # PowerpointSource.__slides is the list of PPTX Slide objects
        # Use slide number to access local FCSlideLayer (which has a svg_filter(shape) method??)

        ## Have option to keep intermediate SVG??
        svg = StringIO()
        svg_maker.save(svg)
        svg_bytes = svg.getvalue().encode('utf-8')
        svg.close()

        if settings.get('saveSVG', False):
            svg_file = pathlib_path(self.href).with_suffix('.raster.svg')
            with open(svg_file, 'wb') as fp:
                fp.write(svg_bytes)
                log.info(f'Saved intermediate SVG as {svg_file}')

        svg_data = BytesIO(svg_bytes)
        svg_data.seek(0)
        return svg_data

#===============================================================================
