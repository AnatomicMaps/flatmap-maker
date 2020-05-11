#!/bin/sh

pipenv run python mapmaker --id $1  \
                           --slides ./map_sources/tests/$2 \
                           --map-dir ./maps
