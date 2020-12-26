#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2019  David Brooks
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

import io
import math
import os

#===============================================================================

import cv2
import fitz
import mercantile
import numpy as np
from reportlab.graphics import renderPDF
from svglib.svglib import svg2rlg

#===============================================================================

from mapmaker import MAX_ZOOM
import mapmaker.geometry
from mapmaker.output.mbtiles import MBTiles, ExtractionError
from mapmaker.sources.svg.rasteriser import SVGTiler
from mapmaker.utils import log, ProgressBar

#===============================================================================

TILE_SIZE = (512, 512)
WHITE     = (255, 255, 255)

#===============================================================================

# Based on https://stackoverflow.com/a/54148416/2159023

def make_transparent(img, colour=WHITE):
    transparent = img.copy()
    if colour == WHITE:
        transparent[:, :, 3] = (255*((transparent[:, :, :3] != 255).any(axis=2) * (transparent[:, :, 3] != 0))).astype(np.uint8)
    else:
        transparent[:, :, 3] = (255*((transparent[:,:,0:3] != tuple(colour)[0:3]).any(axis=2) * (transparent[:, :, 3] != 0))).astype(np.uint8)
    return transparent

#===============================================================================

def not_transparent(img):
    return np.any(img[:,:,3])

#===============================================================================

def transparent_image(size=(1, 1)):
    image = np.full(size + (4,), 255, dtype=np.uint8)
    image[:,:,3] = 0
    return image

#===============================================================================

def get_image_size(img):
    return tuple(reversed(img.shape[:2]))

def paste_image(destination, source, offset):
    destination[offset[1]:offset[1]+source.shape[0],
                offset[0]:offset[0]+source.shape[1]] = source
    return destination

#===============================================================================

class Transform(mapmaker.geometry.Transform):
    def __init__(self, scale, translateA=None, translateB=None):
        if translateA is None: translateA = (0, 0)
        if translateB is None: translateB = (0, 0)
        super().__init__([[ scale[0], 0, -scale[0]*translateA[0] + translateB[0] ],
                          [ 0, scale[1], -scale[1]*translateA[1] + translateB[1] ],
                          [ 0,        0,                                       1 ]])

    def transform_point(self, x, y):
    #===============================
        return super().transform_point((x, y))

#===============================================================================

class Rect(object):
    def __init__(self, *args):
        if not args:
            raise ValueError('Missing arguments for Rect constructor')
        if len(args) == 4:
            self.x0 = float(args[0])
            self.y0 = float(args[1])
            self.x1 = float(args[2])
            self.y1 = float(args[3])
        elif len(args) == 2:                  # 2 Points provided
            self.x0 = float(args[0][0])
            self.y0 = float(args[0][1])
            self.x1 = float(args[1][0])
            self.y1 = float(args[1][1])
        else:
            raise ValueError('Invalid arguments for Rect constructor')

    def __iter__(self):
        yield self.x0
        yield self.y0
        yield self.x1
        yield self.y1

    def __str__(self):
        return 'Rect: ({}, {}, {}, {})'.format(self.x0, self.y0,
                                               self.x1, self.y1)

    @property
    def height(self):
        return abs(self.y1 - self.y0)

    @property
    def width(self):
        return abs(self.x1 - self.x0)

    @property
    def x0(self):
        return self.__x0

    @property
    def x1(self):
        return self.__x1

    @property
    def y0(self):
        return self.__y0

    @property
    def y1(self):
        return self.__y1

    def to_fitz(self):
    #=================
        return fitz.Rect(self.x0, self.y0, self.x1, self.y1)

    def transform(self, matrix):
    #===========================
        return Rect(matrix.transform_point(self.x0, self.y0), matrix.transform_point(self.x1, self.y1))

#===============================================================================

def check_image_size(dimension, max_dim, lower, upper, bounds, scale):
    if dimension < max_dim:
        if lower < bounds[0]:
            if upper < bounds[1]:
                return max_dim - dimension
            else:
                return int(math.floor(0.5 - lower*scale))
    elif dimension != max_dim:
        raise AssertionError('Image size mismatch: {} != {}'.format(dimension, max_dim))
    return 0

#===============================================================================

class TileExtractor(object):
    """
    Extract tiles from a :class:`~mapmaker.sources.RasterSource`.

    :param tiled_pixel_rect: tile bounds in tile pixel coordinates
    :type tiled_pixel_rect: :class:`Rect`
    :param tile_origin: origin of tile grid in base map's world coordinates
    :type tile_origin: tuple(x, y)
    :param image_rect: source bounds in image pixel coordinates
    :type image_rect: :class:`Rect`
    """
    def __init__(self, tiled_pixel_rect, tile_origin, image_rect):
        self.__tile_origin = tile_origin
        self.__image_rect = image_rect
        sx = image_rect.width/tiled_pixel_rect.width
        sy = image_rect.height/tiled_pixel_rect.height
        self.__tile_to_image = Transform((sx, sy), (tiled_pixel_rect.x0, tiled_pixel_rect.y0), (0, 0))

    def extract_tile_as_image(self, image_tile_rect):
    #================================================
        # Overridden by subclass
        return transparent_image()

    def get_tile(self, tile):
    #========================
        tile_x = tile.x - self.__tile_origin[0]
        tile_y = tile.y - self.__tile_origin[1]
        image_tile_rect = Rect(self.__tile_to_image.transform_point(TILE_SIZE[0]*tile_x,
                                                                    TILE_SIZE[1]*tile_y),
                               self.__tile_to_image.transform_point(TILE_SIZE[0]*(tile_x + 1),
                                                                    TILE_SIZE[1]*(tile_y + 1)))
        image = self.extract_tile_as_image(image_tile_rect)
        image_size = get_image_size(image)
        if image_size == tuple(TILE_SIZE):
            return make_transparent(image)
        else:
            # Pad out partial tiles
            tile = transparent_image(TILE_SIZE)
            x_start = check_image_size(image_size[0], TILE_SIZE[0], x0, x1, (0, self.__image_rect.x1), scaling[0])
            y_start = check_image_size(image_size[1], TILE_SIZE[1], y0, y1, (0, self.__image_rect.y1), scaling[1])
            paste_image(tile, image, (x_start, y_start))
            return make_transparent(tile)

#===============================================================================

class RasterTileExtractor(TileExtractor):
    def __init__(self, tiled_pixel_rect, tile_origin, image):
        if image.shape[2] == 3:
            image = cv2.cvtColor(image, cv2.COLOR_RGB2RGBA)
        self.__source_image = image
        super().__init__(tiled_pixel_rect, tile_origin, Rect((0, 0), get_image_size(image)))
    def __get_scaling(self, image_tile_rect):
    #========================================
        return (TILE_SIZE[0]/image_tile_rect.width,
                TILE_SIZE[1]/image_tile_rect.height)

    def extract_tile_as_image(self, image_tile_rect):
    #================================================
        X0 = max(0, round(image_tile_rect.x0))
        X1 = min(round(image_tile_rect.x1), self.__source_image.shape[1])
        Y0 = max(0, round(image_tile_rect.y0))
        Y1 = min(round(image_tile_rect.y1), self.__source_image.shape[0])
        scaling = self.__get_scaling(image_tile_rect)
        width = (TILE_SIZE[0] if image_tile_rect.x0 >= 0 and image_tile_rect.x1 < self.__source_image.shape[1]
            else round(scaling[0]*(X1 - X0)))
        height = (TILE_SIZE[1] if image_tile_rect.y0 >= 0 and image_tile_rect.y1 < self.__source_image.shape[0]
            else round(scaling[1]*(Y1 - Y0)))
        return cv2.resize(self.__source_image[Y0:Y1, X0:X1], (width, height), interpolation=cv2.INTER_CUBIC)

#===============================================================================

class SVGRasterTileExtractor(RasterTileExtractor):
    def __init__(self, tiled_pixel_rect, tile_origin, svg_data):
        self.__svg_tiler = SVGTiler(svg_data, tiled_pixel_rect)
        image = self.__svg_tiler.get_image()
        super().__init__(tiled_pixel_rect, cv2.cvtColor(image, cv2.COLOR_RGBA2BGRA))

#===============================================================================

class SVGTileExtractor(TileExtractor):
    def __init__(self, tiled_pixel_rect, tile_origin, svg_data, tiles):
        self.__svg_tiler = SVGTiler(svg_data, tiled_pixel_rect, tile_origin, tiles, TILE_SIZE)
        super().__init__(tiled_pixel_rect, tile_origin, Rect((0, 0), self.__svg_tiler.size))

    def get_tile(self, tile):
    #========================
        rgba = self.__svg_tiler.get_tile(tile)
        image = cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA)
        return make_transparent(image)

#===============================================================================

class PDFTileExtractor(TileExtractor):
    def __init__(self, tiled_pixel_rect, pdf_page):
        super().__init__(tiled_pixel_rect, pdf_page.rect)
        self.__pdf_page = pdf_page

    def __get_scaling(self, image_tile_rect):
    #========================================
        return ((TILE_SIZE[0] - 1)/image_tile_rect.width,    # Fitz includes RH edge pixel
                (TILE_SIZE[1] - 1)/image_tile_rect.height)   # so scale to 1px smaller...

    def extract_tile_as_image(self, image_tile_rect):
    #================================================
        scaling = self.__get_scaling(image_tile_rect)
        # We now clip to avoid a black line if region outside of page...
        if image_tile_rect.x1 >= self.__pdf_page.rect.width:
            image_tile_rect.x1 = self.__pdf_page.rect.width - 1
        if image_tile_rect.y1 >= self.__pdf_page.rect.height:
            image_tile_rect.y1 = self.__pdf_page.rect.height - 1
        pixmap = self.__pdf_page.getPixmap(clip=fitz.Rect(image_tile_rect.x0, image_tile_rect.y0,
                                                          image_tile_rect.x1, image_tile_rect.y1),
                                           matrix=fitz.Matrix(*scaling),
                                           alpha=False)
        image = np.frombuffer(pixmap.samples, 'B').reshape(pixmap.height, pixmap.width, pixmap.n)
        return cv2.cvtColor(image, cv2.COLOR_BGR2RGBA)

#===============================================================================

class RasterTileMaker(object):
    """
    A class for generating image tiles for a map

    Image tiles are stored as ``mbtiles`` in a SQLite3 database.

    The raster layer's extent together with the map's maximum zoom level
    is used to determine the set of tiles that cover the layer, the transform
    from map world coordinates to tile pixel coordinates, and the the
    location of the layer in terms of tile pixels.

    :param raster_tile_layer: The raster layer to tile
    :type raster_tile_layer: :class:`~mapmaker.layers.RasterTileLayer`
    :param output_dir: The directory in which to store image tiles
    :type output_dir: str
    :param max_zoom: The range of zoom levels to generate tiles.
                     Optional, defaults to ``MAX_ZOOM``
    :type max_zoom: int
    """
    def __init__(self, raster_tile_layer, output_dir, max_zoom=MAX_ZOOM):
        self.__id = raster_tile_layer.id
        self.__raster_source = raster_tile_layer.raster_source
        self.__output_dir = output_dir
        self.__min_zoom = raster_tile_layer.min_zoom
        self.__max_zoom = max_zoom
        self.__local_world_to_base = raster_tile_layer.local_world_to_base

        # Get the set of tiles that span the map

        extent = raster_tile_layer.extent
        self.__tiles = list(mercantile.tiles(*extent, self.__max_zoom))
        tile_0 = self.__tiles[0]
        tile_N = self.__tiles[-1]
        self.__tile_start_coords = (tile_0.x, tile_0.y)
        self.__tile_end_coords = (tile_N.x, tile_N.y)

        # Tiled area in world coordinates (metres)

        bounds_0 = mercantile.xy_bounds(tile_0)
        bounds_N = mercantile.xy_bounds(tile_N)
        tile_world = Rect(bounds_0.left, bounds_0.top, bounds_N.right, bounds_N.bottom)

        # Tiled area in tile pixel coordinates

        tile_extent = Rect(0, 0, TILE_SIZE[0]*(tile_N.x-tile_0.x+1), TILE_SIZE[1]*(tile_N.y-tile_0.y+1))

        # Transform between world and tile pixel coordinates

        sx = tile_extent.width/tile_world.width
        sy = tile_extent.height/tile_world.height
        self.__world_to_tile = Transform((sx, -sy), (tile_world.x0, tile_world.y0), (0, 0))
        self.__tile_to_world = Transform((1.0/sx, -1.0/sy), (0, 0), (tile_world.x0, tile_world.y0))

        # Extent in world coordinates (metres)

        sw = mercantile.xy(*extent[:2])
        ne = mercantile.xy(*extent[2:])

        # Map extent in tile pixel coordinates

        self.__tiled_pixel_rect = Rect(sw[0], ne[1], ne[0], sw[1]).transform(self.__world_to_tile)

    def __make_zoomed_tiles(self, tile_extractor):
    #=============================================
        raster_database_name = '{}.mbtiles'.format(self.__id)
        mbtiles = MBTiles(os.path.join(self.__output_dir, raster_database_name), True, True)
        mbtiles.add_metadata(id=self.__id)
        zoom = self.__max_zoom
        log('Tiling zoom level {} for {}'.format(zoom, self.__id))
        progress_bar = ProgressBar(total=len(self.__tiles),
            unit='tiles', ncols=40,
            bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt}')
        for tile in self.__tiles:
            image = tile_extractor.get_tile(tile)
            if not_transparent(image):
                mbtiles.save_tile_as_png(zoom, tile.x, tile.y, image)
            progress_bar.update(1)
        progress_bar.close()
        self.__make_overview_tiles(mbtiles, zoom, self.__tile_start_coords, self.__tile_end_coords)
        return raster_database_name

    def __make_overview_tiles(self, mbtiles, zoom, start_coords, end_coords):
    #========================================================================
        if zoom > self.__min_zoom:
            zoom -= 1
            log('Tiling zoom level {} for {}'.format(zoom, self.__id))
            HALF_SIZE = (TILE_SIZE[0]//2, TILE_SIZE[1]//2)
            half_start = (start_coords[0]//2, start_coords[1]//2)
            half_end = (end_coords[0]//2, end_coords[1]//2)
            progress_bar = ProgressBar(total=(half_end[0]-half_start[0]+1)
                                     *(half_end[1]-half_start[1]+1),
                unit='tiles', ncols=40,
                bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt}')
            for x in range(half_start[0], half_end[0] + 1):
                for y in range(half_start[1], half_end[1] + 1):
                    overview_tile = transparent_image(TILE_SIZE)
                    for i in range(2):
                        for j in range(2):
                            try:
                                tile = mbtiles.get_tile(zoom+1, 2*x+i, 2*y+j)
                                half_tile = cv2.resize(tile, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
                                paste_image(overview_tile, half_tile, (i*HALF_SIZE[0], j*HALF_SIZE[1]))
                            except ExtractionError:
                                pass
                    if not_transparent(overview_tile):
                        mbtiles.save_tile_as_png(zoom, x, y, overview_tile)
                    progress_bar.update(1)
            progress_bar.close()
            self.__make_overview_tiles(mbtiles, zoom, half_start, half_end)

    def make_tiles(self):
    #====================
        log('Tiling {}...'.format(self.__id))
        source_data = self.__raster_source.source_data
        source_kind = self.__raster_source.source_kind
        if source_kind == 'raster':
            tile_extractor = RasterTileExtractor(self.__tiled_pixel_rect, self.__tile_start_coords,
                                                 source_data,
                                                 local_world_to_base=self.__local_world_to_base)
        elif source_kind == 'pdf':
            pdf = fitz.Document(stream=source_data, filetype='application/pdf')
            # Tile the first page of a PDF
            tile_extractor = PDFTileExtractor(self.__tiled_pixel_rect, self.__tile_start_coords,
                                              pdf[0])
        elif source_kind == 'svg':
            ## Lots of memory...
            #tile_extractor = SVGRasterTileExtractor(self.__tiled_pixel_rect, self.__tile_start_coords,
            #                                        source_data)
            tile_extractor = SVGTileExtractor(self.__tiled_pixel_rect, self.__tile_start_coords,
                                              source_data, self.__tiles)
        else:
            raise TypeError('Unsupported kind of background tile source: {}'.format(source_kind))
        return self.__make_zoomed_tiles(tile_extractor)

#===============================================================================

if __name__ == '__main__':
    import sys
    from mapmaker.sources import RasterSource
    from mapmaker.layers import RasterTileLayer

    map_extent = [-10, -20, 10, 20]
    max_zoom = 6
    mode = 'PDF' if len(sys.argv) < 2 else sys.argv[1].upper()

    if mode == 'PDF':
        pdf_file = '../../tests/sources/rat-test.pdf'
        with open(pdf_file, 'rb') as f:
            tile_layer = RasterTileLayer('test', RasterSource('pdf', f.read()), map_extent)
    elif mode == 'JPEG':
        jpeg_file = './mbf/pig/sub-10sam-1P10-1Slide2p3MT10x.jp2'
        tile_layer = RasterTileLayer('test', RasterSource('raster', Image.open(jpeg_file)), map_extent)
    else:
        sys.exit('Unknown mode of test -- must be "JPEG" or "PDF"')
    tile_maker = RasterTileMaker(tile_layer, '../../maps', max_zoom)
    tile_maker.make_tiles()

#===============================================================================
