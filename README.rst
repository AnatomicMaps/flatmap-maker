========
Overview
========

Mapmaker is a Python application for generating `Mapbox <https://www.mapbox.com/>`_ compatible tilesets from a set of Powerpoint slides.

Requirements
------------

* Python 3.7 with `pipenv <https://pipenv.pypa.io/en/latest/#install-pipenv-today>`_.
* `Tippecanoe <https://github.com/mapbox/tippecanoe#installation>`_.

Installation
------------

Clone this repository and then run::

    pipenv installation


Running
-------

Command line help::

    $ pipenv run python mapmaker --help


::

    usage: mapmaker [-h] [-b] [-n] [-t N] [-z N] [--max N] [--min N] [-d] [-s]
                    [-v] --map-dir MAP_DIR --id MAP_ID --anatomical-map
                    ANATOMICAL_MAP --slides POWERPOINT

    Convert Powerpoint slides to a flatmap.

    optional arguments:
      -h, --help            show this help message and exit
      -b, --background-tiles
                            generate image tiles of map's layers (may take a
                            while...)
      -n, --no-vector-tiles
                            don't generate vector tiles database and style files
      -t N, --tile N        only generate image tiles for this slide (1-origin);
                            implies --background-tiles and --no-vector-tiles
      -z N, --initial-zoom N
                            initial zoom level (defaults to 4)
      --max N               maximum zoom level (defaults to 10)
      --min N               minimum zoom level (defaults to 2)
      -d, --debug           save a slide's DrawML for debugging
      -s, --save-geojson    Save GeoJSON files for each layer
      -v, --version         show program's version number and exit

    required arguments:
      --map-dir MAP_DIR     base directory for generated flatmaps
      --id MAP_ID           a unique identifier for the map
      --anatomical-map ANATOMICAL_MAP
                            Excel spreadsheet file for mapping shape classes to
                            anatomical entities
      --slides POWERPOINT   File or URL of Powerpoint slides


For instance::

    $ pipenv run python mapmaker --map-dir ./flatmaps --id rat-spine  \
                      --anatomical-map ./sources/rat/Flatmap_Annotation_Rat.xlsx  \
                      --slides ./sources/rat/Rat_flatmap_spinal_cord_V2.pptx


::

    Extracting layers...
    Slide 1, layer rat-spine
    Running tippecanoe...
    794 features, 1641757 bytes of geometry, 480 bytes of separate metadata, 130840 bytes of string pool
      99.9%  10/532/488
    Creating style files...
    Generated map for UBERON:2240
    Cleaning up...
