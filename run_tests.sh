#!/bin/sh

PYTHON=$(which python3)

die() {
    echo $@
    exit 1
}

for testscript in "$(dirname $0)"/test_*.py;
do
    echo "$PYTHON" "$testscript"
    "$PYTHON" "$testscript" || die "FAILED TEST RUN"
done
echo "SUCCESS"
exit 0
