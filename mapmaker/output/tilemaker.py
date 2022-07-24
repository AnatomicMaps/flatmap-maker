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
import multiprocess as mp
import numpy as np
import shapely.geometry
from svglib.svglib import svg2rlg

#===============================================================================

from mapmaker import MAX_ZOOM
from mapmaker.geometry import extent_to_bounds, Transform as GeometryTransform
from mapmaker.output.mbtiles import MBTiles, ExtractionError
from mapmaker.sources import add_alpha, blank_image, mask_image, not_empty
from mapmaker.sources.svg.rasteriser import SVGTiler
from mapmaker.utils import log, ProgressBar
from mapmaker.utils.image import *

#===============================================================================

TILE_SIZE = (512, 512)

#===============================================================================

class Rect(object):
    def __init__(self, *args):
        if not args:
            raise ValueError('Missing arguments for Rect constructor')
        if len(args) == 4:
            self.__coords = [float(args[0]), float(args[1]),
                             float(args[2]), float(args[3])]
        elif len(args) == 3:                  # Point and width, height provided
            self.__coords = [float(args[0][0]), float(args[0][1]),
                             float(args[0][0]) + float(args[1]),
                             float(args[0][1]) + float(args[2])]
        elif len(args) == 2:                  # 2 Points provided
            self.__coords = [float(args[0][0]), float(args[0][1]),
                             float(args[1][0]), float(args[1][1])]
        else:
            raise ValueError('Invalid arguments for Rect constructor')

    def __getitem__(self, index):
        return self.__coords[index]

    def __iter__(self):
        return iter(self.__coords)

    def __str__(self):
        return 'Rect: ({}, {}, {}, {})'.format(*self.__coords)

    @property
    def geometry(self):
        return shapely.geometry.box(*self.__coords)

    @property
    def height(self):
        return abs(self.__coords[3] - self.__coords[1])

    @property
    def size(self):
        return (self.width, self.height)

    @property
    def size_as_int(self):
        return (round(self.width), round(self.height))

    @property
    def width(self):
        return abs(self.__coords[2] - self.__coords[0])

    @property
    def x0(self):
        return self.__coords[0]

    @property
    def x1(self):
        return self.__coords[2]

    @property
    def y0(self):
        return self.__coords[1]

    @property
    def y1(self):
        return self.__coords[3]

#===============================================================================

class Transform(GeometryTransform):
    def __init__(self, scale=None, translateA=None, translateB=None):
        if scale is None: scale = (1, 1)
        if translateA is None: translateA = (0, 0)
        if translateB is None: translateB = (0, 0)
        super().__init__([[ scale[0], 0, -scale[0]*translateA[0] + translateB[0] ],
                          [ 0, scale[1], -scale[1]*translateA[1] + translateB[1] ],
                          [ 0,        0,                                       1 ]])

    def transform_rect(self, rect):
    #==============================
        return Rect(self.transform_point((rect.x0, rect.y0)),
                    self.transform_point((rect.x1, rect.y1)))

#===============================================================================

class TileSet(object):
    """
    The set of tiles covering a geographic extent.

    :param extent:
    :type extent: tuple(float, float, float, float)
    :param max_zoom:
    :type max_zoom: int
    """
    def __init__(self, extent, max_zoom):
        self.__extent = extent

        # Get the set of tiles that span the extent
        self.__tiles = list(mercantile.tiles(*extent, max_zoom))

        tile_0 = self.__tiles[0]
        tile_N = self.__tiles[-1]

        # Tile coordinates of first and last tiles
        self.__start_coords = (tile_0.x, tile_0.y)
        self.__end_coords = (tile_N.x, tile_N.y)

        # Tiled area in world coordinates (metres)
        bounds_0 = mercantile.xy_bounds(tile_0)
        bounds_N = mercantile.xy_bounds(tile_N)
        tile_world = Rect(bounds_0.left, bounds_0.top, bounds_N.right, bounds_N.bottom)

        # Size of a tile in pixels
        self.__tile_size = TILE_SIZE

        # Tile coordinates to tile pixels
        self.__tile_coords_to_pixels = Transform(self.__tile_size, self.__start_coords)

        # Transforms between world and tile pixel coordinates
        sx = TILE_SIZE[0]*(tile_N.x-tile_0.x+1)/tile_world.width   # px/m
        sy = TILE_SIZE[1]*(tile_N.y-tile_0.y+1)/tile_world.height  # px/m
        self.__world_to_tile_pixels = Transform((sx, -sy), (tile_world.x0, tile_world.y0), (0, 0))
        self.__tile_pixels_to_world = Transform((1.0/sx, -1.0/sy), (0, 0), (tile_world.x0, tile_world.y0))

        # Extent in world coordinates (metres)
        sw = mercantile.xy(*extent[:2])
        ne = mercantile.xy(*extent[2:])

        # Map extent in tile pixel coordinates
        self.__pixel_rect = self.__world_to_tile_pixels.transform_rect(Rect(sw[0], ne[1], ne[0], sw[1]))

    def __len__(self):
        return len(self.__tiles)

    def __iter__(self):
        return iter(self.__tiles)

    @property
    def end_coords(self):
        """
        :returns: Tile coordinates of the last tile.
        :rtype: tuple(int, int)
        """
        return self.__end_coords

    @property
    def extent(self):
        """
        :returns: The geographic extent covered by the tile set.
        :rtype: tuple(float, float, float, float)
        """
        return self.__extent

    @property
    def start_coords(self):
        """
        :returns: Tile coordinates of the first tile.
        :rtype: tuple(int, int)
        """
        return self.__start_coords

    @property
    def pixel_rect(self):
        """
        :returns: Extent as tile pixel coordinates.
        :rtype: :class:`Rect`
        """
        return self.__pixel_rect

    @property
    def tile_pixels_to_world(self):
        """
        :returns: Transform from tile pixel coordinates to world coordinates.
        :rtype: :class:`Transform`
        """
        return self.__tile_pixels_to_world

    @property
    def tile_size(self):
        """
        :returns: The size of a tile in pixels.
        :rtype: tuple(int, int)
        """
        return self.__tile_size

    @property
    def tiles(self):
        """
        :returns: List of :class:`mercantile.Tile` tiles spanning an extent.
        :rtype: list
        """
        mercantile.Tile
        return self.__tiles

    @property
    def tile_coords_to_pixels(self):
        """
        :returns: Transform from tile coordinates to tile pixel coordinates.
        :rtype: :class:`Transform`
        """
        return self.__tile_coords_to_pixels

    def tile_pixels_to_image(self, image_rect):
        """
        :param      image_rect:  The image rectangle
        :type       image_rect:  :rtype: :class:`Rect`
        :returns: Transform from tile pixel coordinates to imasge pixels.
        :rtype: :class:`Transform`
        """
        sx = image_rect.width/self.__pixel_rect.width
        sy = image_rect.height/self.__pixel_rect.height
        return Transform((sx, sy),
                         (self.__pixel_rect.x0, self.__pixel_rect.y0),
                         (image_rect.x0,        image_rect.y0))

    @property
    def world_to_tile_pixels(self):
        """
        :returns: Transform from world coordinates to tile pixel coordinates.
        :rtype: :class:`Transform`
        """
        return self.__world_to_tile_pixels

#===============================================================================

class RasterTiler(object):
    """
    Extract tiles from a :class:`~mapmaker.sources.RasterSource`.

    :param raster_layer:
    :type raster_layer:
    :param tiles: the set of tiles spanning an extent
    :type tiles: :class:`TileSet`
    :param image_rect: source bounds in image pixel coordinates
    :type image_rect: :class:`Rect`
    """
    def __init__(self, raster_layer, tile_set, image_rect):
        self.__image_rect = image_rect
        self.__tile_pixels_to_image = tile_set.tile_pixels_to_image(self.__image_rect)
        self.__tile_coords_to_pixels = tile_set.tile_coords_to_pixels
        self.__tile_size = tile_set.tile_size

    @property
    def image_rect(self):
        return self.__image_rect

    @property
    def tile_coords_to_world(self):
        return self.__tile_coords_to_world

    @property
    def tile_size(self):
        return self.__tile_size

    def extract_tile_as_image(self, image_tile_rect):
    #================================================
        # Overridden by subclass
        return blank_image()

    def get_scaling(self, image_tile_rect):
    #======================================
        return (self.__tile_size[0]/image_tile_rect.width,
                self.__tile_size[1]/image_tile_rect.height)

    def get_tile(self, tile):
    #========================
        tile_pixel_rect = Rect(self.__tile_coords_to_pixels.transform_point((tile.x, tile.y)),
                               *self.__tile_size)
        image_tile_rect = self.__tile_pixels_to_image.transform_rect(tile_pixel_rect)
        tile_image = self.extract_tile_as_image(image_tile_rect)
        size = image_size(tile_image)
        if size == tuple(self.__tile_size):
            return tile_image
        else:
            padded = blank_image(self.__tile_size)
            scaling = self.get_scaling(image_tile_rect)
            offset = tuple(image_offset(size[i], self.__tile_size[i],
                                   (image_tile_rect[i], image_tile_rect[i+2]),
                                   (0, self.__image_rect[i+2]),
                                   scaling[i])
                        for i in range(0, 2))
            return paste_image(padded, tile_image, offset)

#===============================================================================

class RasterImageTiler(RasterTiler):
    def __init__(self, raster_layer, tile_set, image, image_to_local_world):
        if raster_layer.local_world_to_base is None:
            image_rect = Rect((0, 0), image_size(image))
        else:
            image_rect = Rect((0, 0), tile_set.pixel_rect.size)
            local_world_to_tile_image = (Transform(translateA=tile_set.pixel_rect[0:2])
                                        @tile_set.world_to_tile_pixels
                                        @raster_layer.local_world_to_base)
            image_to_tile_image = local_world_to_tile_image@image_to_local_world
            image = cv2.warpPerspective(image, image_to_tile_image.matrix,
                                        image_rect.size_as_int,
                                        flags=cv2.INTER_CUBIC)
            if raster_layer.map_source.boundary_geometry is not None:
                # Remove edge artifacts by masking with boundary
                image = mask_image(image, local_world_to_tile_image.transform_geometry(
                                            raster_layer.map_source.boundary_geometry))
        super().__init__(raster_layer, tile_set, image_rect)
        self.__source_image = image

    def extract_tile_as_image(self, image_tile_rect):
    #================================================
        X0 = max(0, round(image_tile_rect.x0))
        X1 = min(round(image_tile_rect.x1), self.__source_image.shape[1])
        Y0 = max(0, round(image_tile_rect.y0))
        Y1 = min(round(image_tile_rect.y1), self.__source_image.shape[0])
        if X0 >= X1 or Y0 >= Y1:
            return blank_image(self.tile_size)
        scaling = self.get_scaling(image_tile_rect)
        width = (self.tile_size[0] if image_tile_rect.x0 >= 0 and image_tile_rect.x1 < self.__source_image.shape[1]
            else round(scaling[0]*(X1 - X0)))
        height = (self.tile_size[1] if image_tile_rect.y0 >= 0 and image_tile_rect.y1 < self.__source_image.shape[0]
            else round(scaling[1]*(Y1 - Y0)))
        return cv2.resize(self.__source_image[Y0:Y1, X0:X1], (width, height), interpolation=cv2.INTER_CUBIC)

#===============================================================================

class ImageTiler(RasterImageTiler):
    def __init__(self, raster_layer, tile_set):
        image = raster_layer.source_data
        if image.shape[2] == 3:
            image = cv2.cvtColor(image, cv2.COLOR_RGB2RGBA)
        tile_bounds = extent_to_bounds(tile_set.extent)
        super().__init__(raster_layer, tile_set, image, raster_layer.map_source.image_to_world)

#===============================================================================

class SVGImageTiler(RasterImageTiler):
    def __init__(self, raster_layer, tile_set):
        svg_tiler = SVGTiler(raster_layer, tile_set)
        super().__init__(raster_layer, tile_set, svg_tiler.get_image(), svg_tiler.image_to_world)

#===============================================================================

class PDFTiler(RasterTiler):
    def __init__(self, raster_layer, tile_set):
        # Tile the first page of a PDF
        self.__pdf = fitz.Document(stream=raster_layer.source_data, filetype='application/pdf')
        if raster_layer.source_range is None:
            self.__page = self.__pdf[0]
        else:
            self.__page = self.__pdf[raster_layer.source_range[0] - 1]
        super().__init__(raster_layer, tile_set, self.__page.rect)

    def get_scaling(self, image_tile_rect):
    #======================================
        return ((TILE_SIZE[0] - 1)/image_tile_rect.width,    # Fitz includes RH edge pixel
                (TILE_SIZE[1] - 1)/image_tile_rect.height)   # so scale to 1px smaller...

    def extract_tile_as_image(self, image_tile_rect):
    #================================================
        scaling = self.get_scaling(image_tile_rect)
        # We now clip to avoid a black line if region outside of page...
        width = min(image_tile_rect.x1, self.image_rect.width - 1)
        height = min(image_tile_rect.y1, self.image_rect.height - 1)
        pixmap = self.__page.get_pixmap(clip=fitz.Rect(image_tile_rect.x0, image_tile_rect.y0,
                                                       width, height),
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

    :param raster_layer: The raster layer to tile
    :type raster_layer: :class:`~mapmaker.layers.RasterLayer`
    :param output_dir: The directory in which to store image tiles
    :type output_dir: str
    :param max_zoom: The range of zoom levels to generate tiles.
                     Optional, defaults to ``MAX_ZOOM``
    :type max_zoom: int
    """
    def __init__(self, raster_layer, output_dir, max_zoom=MAX_ZOOM):
        self.__raster_layer = raster_layer
        self.__max_zoom = max_zoom
        self.__id = raster_layer.id
        self.__database_path = os.path.join(output_dir, '{}.mbtiles'.format(raster_layer.id))
        self.__min_zoom = raster_layer.min_zoom
        self.__tile_set = TileSet(raster_layer.extent, max_zoom)

    @property
    def raster_layer(self):
        return self.__raster_layer

    def __make_zoomed_tiles(self, tile_extractor):
    #=============================================
        mbtiles = MBTiles(self.__database_path, True, True)
        mbtiles.add_metadata(id=self.__id)
        zoom = self.__max_zoom
        log('Tiling zoom level {} for {}'.format(zoom, self.__id))
        progress_bar = ProgressBar(total=len(self.__tile_set),
            unit='tiles', ncols=40,
            bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt}')
        for tile in self.__tile_set:
            tile_image = tile_extractor.get_tile(tile)
            alpha_image = add_alpha(tile_image)
            if not_empty(alpha_image):
                mbtiles.save_tile_as_png(zoom, tile.x, tile.y, alpha_image)
            progress_bar.update(1)
        progress_bar.close()
        self.__make_overview_tiles(mbtiles, zoom, self.__tile_set.start_coords,
                                                  self.__tile_set.end_coords)
        mbtiles.close(compress=True)

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
                    overview_tile = blank_image(TILE_SIZE)
                    for i in range(2):
                        for j in range(2):
                            try:
                                tile = mbtiles.get_tile(zoom+1, 2*x+i, 2*y+j)
                                half_tile = cv2.resize(tile, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
                                paste_image(overview_tile, half_tile, (i*HALF_SIZE[0], j*HALF_SIZE[1]))
                            except ExtractionError:
                                pass
                    if not_empty(overview_tile):
                        mbtiles.save_tile_as_png(zoom, x, y, overview_tile)
                    progress_bar.update(1)
            progress_bar.close()
            self.__make_overview_tiles(mbtiles, zoom, half_start, half_end)

    def have_tiles(self):
    #====================
        return os.path.exists(self.__database_path)

    def make_tiles(self):
    #====================
        log('Tiling {}...'.format(self.__id))
        kind = self.__raster_layer.source_kind
        if kind == 'image':
            tile_extractor = ImageTiler(self.__raster_layer, self.__tile_set)
        elif kind == 'pdf':
            tile_extractor = PDFTiler(self.__raster_layer, self.__tile_set)
        elif kind == 'svg':
            if self.__raster_layer.local_world_to_base is None:
                tile_extractor = SVGTiler(self.__raster_layer, self.__tile_set)
            else:
                tile_extractor = SVGImageTiler(self.__raster_layer, self.__tile_set)
        else:
            raise TypeError('Unsupported kind of background tile source: {}'.format(source_kind))
        return mp.Process(target=self.__make_zoomed_tiles, args=(tile_extractor, ), name=self.__id)

#===============================================================================

if __name__ == '__main__':
    import argparse
    import os, sys

    from mapmaker.sources import RasterSource
    from mapmaker.flatmap.layers import RasterLayer

    parser = argparse.ArgumentParser(description='Convert a PDF or JPEG image to a flatmap.')

    parser.add_argument('--initial-zoom', metavar='N', type=int, default=4,
                        help='initial zoom level (defaults to 4)')
    parser.add_argument('--max-zoom', dest='max_zoom', metavar='N', type=int, default=10,
                        help='maximum zoom level (defaults to 10)')
    parser.add_argument('--min-zoom', dest='min_zoom', metavar='N', type=int, default=2,
                        help='minimum zoom level (defaults to 2)')
    parser.add_argument('--map-dir', dest='map_base', metavar='MAP_DIR', required=True,
                        help='base directory for generated flatmaps')
    parser.add_argument('--id', dest='map_id', metavar='MAP_ID', required=True,
                        help='a unique identifier for the map')
    parser.add_argument('--mode', default='PDF', choices=['PDF', 'JPEG'],
                        help='Type of SOURCE file')
    parser.add_argument('source', metavar='SOURCE',
                        help='PDF or JPEG file')

    args = parser.parse_args()

    if args.min_zoom < 0 or args.min_zoom > args.max_zoom:
        sys.exit('--min-zoom must be between 0 and {}'.format(args.max_zoom))
    if args.max_zoom < args.min_zoom or args.max_zoom > 15:
        sys.exit('--max-zoom must be between {} and 15'.format(args.min_zoom))
    if args.initial_zoom < args.min_zoom or args.initial_zoom > args.max_zoom:
        sys.exit('--initial-zoom must be between {} and {}'.format(args.min_zoom, args.max_zoom))

    #map_zoom = (args.min_zoom, args.max_zoom, args.initial_zoom)

    map_dir = os.path.join(args.map_base, args.map_id)
    if not os.path.exists(map_dir):
        os.makedirs(map_dir)

    map_extent = [-10, -20, 10, 20]

    if args.mode == 'PDF':
        with open(args.source, 'rb') as f:
            source = RasterSource('pdf', lambda: f.read())
    else:
        source = RasterSource('image', lambda: Image.open(args.source))

    tile_layer = RasterLayer(args.map_id, map_extent, source)
    tile_maker = RasterTileMaker(tile_layer, args.map_base, args.max_zoom)
    tile_maker.make_tiles()

#===============================================================================
