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

* Download the latest released Python wheel from https://github.com/dbrnz/flatmap-maker/releases/latest, currently ``mapmaker-0.11.0b4-py3-none-any.whl``.
* Create a directory in which to install ``mapmaker`` and change into it.

::

    $ pipenv install mapmaker-0.11.0b4-py3-none-any.whl

Running
-------

Command line help::

    $ pipenv run python -m mapmaker --help

::

    usage: mapmaker [-h] [--background-tiles] [--background-only] [--check-errors] [--initialZoom N]
                    [--max-zoom N] [--min-zoom N] [--save-beziers] [--save-drawml] [--save-geojson]
                    [--tippecanoe] [--clean] [--refresh-labels] [--upload USER@SERVER]
                    [--log LOG_FILE] [-q] [--silent] [-v]
                    --output-dir OUTPUT_DIR --map MAP

    Generate a flatmap from its source manifest.

    optional arguments:
      -h, --help            show this help message and exit
      --background-tiles    generate image tiles of map's layers (may take a while...)
      --background-only     don't generate vector tiles (sets --background-tiles)
      --check-errors        check for errors without generating a map
      --initialZoom N       initial zoom level (defaults to 4)
      --max-zoom N          maximum zoom level (defaults to 10)
      --min-zoom N          minimum zoom level (defaults to 2)
      --save-beziers        Save Bezier curve segments as a feature property
      --save-drawml         save a slide's DrawML for debugging
      --save-geojson        Save GeoJSON files for each layer
      --tippecanoe          Show command used to run Tippecanoe
      --clean               Remove all files from generated map's directory before generating new map
      --refresh-labels      Clear the label text cache before map making
      --upload USER@SERVER  Upload generated map to server
      --log LOG_FILE        append messages to a log file
      -q, --quiet           don't show progress bars
      --silent              suppress all messages to screen
      -v, --version         show program's version number and exit

    required arguments:
      --output-dir OUTPUT_DIR
                            base directory for generated flatmaps
      --map MAP             URL or directory path containing a flatmap manifest

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