#!/bin/sh

pipenv run python mapmaker --id $1  \
                           --slides ./tests/sources/$2 \
                           --map-dir ./maps
