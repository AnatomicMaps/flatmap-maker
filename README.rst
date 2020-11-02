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

Clone this repository.

pipenv
~~~~~~

::

    $ pipenv install


VERSUS setup.py
~~~~~~~~

::

    $ python setup.py develop

Running
-------

Command line help::

    $ pipenv run python mapmaker --help


::

    usage: mapmaker [-h] [-c CONF] [-b] [-t N] [--background-only]
                    [--anatomical-map ANATOMICAL_MAP] [--properties PROPERTIES]
                    [--check-errors] [-z N] [--max-zoom N] [--min-zoom N] [-d]
                    [-s] [--clear] [--refresh-labels] [-u USER@SERVER] [-v] -o
                    OUTPUT_DIR --id MAP_ID --slides POWERPOINT

    Args that start with '--' (eg. -b) can also be set in a config file (specified
    via -c). Config file syntax allows: key=value, flag=true, stuff=[a,b,c] (for
    details, see syntax at https://goo.gl/R74nmi). If an arg is specified in more
    than one place, then commandline values override config file values which
    override defaults.

    optional arguments:
      -h, --help            show this help message and exit
      -c CONF, --conf CONF  configuration file containing arguments
      -b, --background-tiles
                            generate image tiles of map's layers (may take a
                            while...)
      -t N, --tile N        only generate image tiles for this slide (1-origin);
                            sets --background-tiles
      --background-only     don't generate vector tiles (sets --background-tiles)
      --anatomical-map ANATOMICAL_MAP
                            Excel spreadsheet file for mapping shape classes to
                            anatomical entities
      --properties PROPERTIES
                            JSON file specifying additional properties of shapes
      --check-errors        check for errors without generating a map
      -z N, --initial-zoom N
                            initial zoom level (defaults to 4)
      --max-zoom N          maximum zoom level (defaults to 10)
      --min-zoom N          minimum zoom level (defaults to 2)
      -d, --debug           save a slide's DrawML for debugging
      -s, --save-geojson    Save GeoJSON files for each layer
      --clear               Remove all files from generated map's directory before
                            generating new map
      --refresh-labels      Clear the label text cache before map making
      -u USER@SERVER, --upload USER@SERVER
                            Upload generated map to server
      -v, --version         show program's version number and exit

    required arguments:
      -o OUTPUT_DIR, --output-dir OUTPUT_DIR
                            base directory for generated flatmaps
      --id MAP_ID           a unique identifier for the map
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
