#!/bin/bash
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
"$DIR/Simulation/Unity/Warehouse simulation/Builds/Linux/WarehouseSimulation.x86_64" "$@"
