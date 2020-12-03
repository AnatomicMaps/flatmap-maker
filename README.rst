========
Overview
========

Mapmaker is a Python application for generating `Mapbox <https://www.mapbox.com/>`_ compatible tilesets from a set of Powerpoint slides.

Requirements
------------

* Python 3.8 with `pipenv <https://pipenv.pypa.io/en/latest/#install-pipenv-today>`_.
* `Tippecanoe <https://github.com/mapbox/tippecanoe#installation>`_.

Installation
------------

* Download the latest released Python wheel from https://github.com/dbrnz/flatmap-maker/releases/latest, currently ``mapmaker-0.11.0b1-py3-none-any.whl``.
* Create a directory in which to install ``mapmaker`` and change into it.

::

    $ pipenv install mapmaker-0.11.0b1-py3-none-any.whl

Running
-------

Command line help::

    $ pipenv run python -m mapmaker --help

::

    usage: __main__.py [-h] [-c CONF] [-b] [--background-only] [--check-errors] [-z N] [--max-zoom N]
                       [--min-zoom N] [-d] [-s] [-t] [--clean] [--refresh-labels] [--upload USER@SERVER]
                       [-v] --output-dir OUTPUT_DIR --map MAP_DIR

    Args that start with '--' (eg. -b) can also be set in a config file (specified via -c). Config file
    syntax allows: key=value, flag=true, stuff=[a,b,c] (for details, see syntax at https://goo.gl/R74nmi).
    If an arg is specified in more than one place, then commandline values override config file values which
    override defaults.

    optional arguments:
      -h, --help            show this help message and exit
      -c CONF, --conf CONF  configuration file containing arguments
      -b, --background-tiles
                            generate image tiles of map's layers (may take a while...)
      --background-only     don't generate vector tiles (sets --background-tiles)
      --check-errors        check for errors without generating a map
      -z N, --initialZoom N
                            initial zoom level (defaults to 4)
      --max-zoom N          maximum zoom level (defaults to 10)
      --min-zoom N          minimum zoom level (defaults to 2)
      -d, --debug           save a slide's DrawML for debugging
      -s, --save-geojson    Save GeoJSON files for each layer
      -t, --tippecanoe      Show command used to run Tippecanoe
      --clean               Remove all files from generated map's directory before generating new map
      --refresh-labels      Clear the label text cache before map making
      --upload USER@SERVER  Upload generated map to server
      -v, --version         show program's version number and exit

    required arguments:
      --output-dir OUTPUT_DIR
                            base directory for generated flatmaps
      --map MAP_DIR         Directory containing a flatmap manifest specifying sources

For instance::

    $ pipenv run python -m mapmaker --output-dir ./flatmaps   \
                                    --map ../PMR/rat
::

    Mapmaker 0.11.0.b1
    100%|█████████████████████████▉| 678/679
     98%|███████████████████████████▌| 65/66
    Adding details...
    Outputting GeoJson features...
    Layer: whole-rat
    100%|████████████████████████| 2477/2477
    Layer: whole-rat_details
    100%|██████████████████████████| 180/180
    Running tippecanoe...
    2657 features, 6439698 bytes of geometry, 25397 bytes of separate metadata, 485295 bytes of string pool
      99.9%  10/528/531
    Creating index and style files...
    Generated map for NCBITaxon:10114